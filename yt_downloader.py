import os
import sys
import ctypes

# ================================
# SINGLE INSTANCE LOCK (Windows)
# ================================
_mutex = None

def acquire_single_instance_lock():
    global _mutex
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "YTDownloader_SingleInstance")
    last_error = ctypes.windll.kernel32.GetLastError()
    return last_error != 183  # ERROR_ALREADY_EXISTS = 183

if not acquire_single_instance_lock():
    sys.exit(0)

# ================================
# IMPORTS
# ================================
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog
import yt_dlp
import threading
import re
import json
import subprocess

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".ytdl_config.json")

# ================================
# CONFIG SAVE / LOAD
# ================================
def save_config(data: dict):
    try:
        existing = load_config_raw()
        existing.update(data)
        with open(CONFIG_FILE, "w") as f:
            json.dump(existing, f)
    except:
        pass


def load_config_raw() -> dict:
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
    except:
        pass
    return {}


def load_save_path() -> str:
    data = load_config_raw()
    path = data.get("save_path", "")
    if path and os.path.exists(path):
        return path
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    if os.path.exists(downloads):
        return downloads
    return ""


# ================================
# FFMPEG DETECTION (Windows)
# ================================
def get_base_dir():
    """Returns the directory where the exe (or script) lives."""
    if getattr(sys, "frozen", False):
        # Running as PyInstaller bundle
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def get_ffmpeg_path():
    # 1. Bundled alongside the app (PyInstaller _MEIPASS)
    bundled = os.path.join(get_base_dir(), "ffmpeg.exe")
    if os.path.exists(bundled):
        return bundled

    # 2. Next to the .exe on disk
    exe_dir = os.path.dirname(sys.executable)
    next_to_exe = os.path.join(exe_dir, "ffmpeg.exe")
    if os.path.exists(next_to_exe):
        return next_to_exe

    # 3. Common manual install locations
    candidates = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        os.path.join(os.path.expanduser("~"), "ffmpeg", "bin", "ffmpeg.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p

    # 4. Try PATH
    try:
        result = subprocess.run(
            ["where", "ffmpeg"],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        path = result.stdout.strip().split("\n")[0].strip()
        if path and os.path.exists(path):
            return path
    except:
        pass

    return None


# ================================
# YT-DLP AUTO UPDATE
# ================================
def check_ytdlp_update(callback):
    def run():
        try:
            import importlib.metadata
            current = importlib.metadata.version("yt-dlp")
        except:
            current = "unknown"

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "index", "versions", "yt-dlp"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            match = re.search(r"yt-dlp \(([^\)]+)\)", result.stdout)
            latest = match.group(1) if match else None
        except:
            latest = None

        if latest and current != "unknown" and latest != current:
            callback("update_available", current, latest)
        else:
            callback("up_to_date", current, current)

    threading.Thread(target=run, daemon=True).start()


def perform_update(callback):
    def run():
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                capture_output=True, text=True, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                callback("success")
            else:
                callback("error", result.stderr)
        except Exception as e:
            callback("error", str(e))

    threading.Thread(target=run, daemon=True).start()


# ================================
# FETCH VIDEO INFO
# ================================
def fetch_resolutions():
    url = url_entry.get().strip()
    if not url:
        show_toast("Please enter a YouTube URL", "error")
        return

    check_button.configure(state="disabled", text="Checking...")
    update_status("Fetching video info...", "muted")
    title_label.configure(text="")

    threading.Thread(target=run_fetch, args=(url,), daemon=True).start()


def run_fetch(url):
    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = info.get("formats", [])
        heights = {
            f["height"]
            for f in formats
            if f.get("height") and f.get("vcodec") != "none"
        }

        options = ["Best Quality"]
        for h in sorted(heights, reverse=True):
            options.append(f"{h}p")

        def update_ui():
            quality_menu.configure(values=options)
            quality_var.set(options[0])
            raw_title = info.get("title", "")
            display = raw_title[:55] + "..." if len(raw_title) > 55 else raw_title
            title_label.configure(text=display)
            check_button.configure(state="normal", text="Check")
            update_status("Video info loaded - ready to download", "success")

        root.after(0, update_ui)

    except Exception as e:
        def error_ui():
            check_button.configure(state="normal", text="Check")
            update_status("Could not fetch video info", "error")
            show_toast(str(e)[:120], "error")
        root.after(0, error_ui)


# ================================
# DOWNLOAD
# ================================
def start_download():
    url = url_entry.get().strip()
    folder = save_path_var.get().strip()
    fmt = format_var.get()
    quality_str = quality_var.get()

    if not url:
        show_toast("Please enter a YouTube URL", "error")
        return
    if not folder:
        show_toast("Please choose a save folder", "error")
        return

    download_button.configure(state="disabled", text="Downloading...")
    progress_bar.set(0)
    update_status("Starting download...", "muted")

    threading.Thread(
        target=download_video,
        args=(url, folder, fmt, quality_str),
        daemon=True
    ).start()


def download_video(url, folder, fmt, quality_str):
    try:
        ffmpeg_loc = get_ffmpeg_path()

        if not ffmpeg_loc and fmt == "mp4":
            root.after(0, lambda: show_toast(
                "FFmpeg not found. Download from ffmpeg.org and add to PATH", "error"
            ))
            root.after(0, lambda: download_button.configure(state="normal", text="Download"))
            return

        ydl_opts = {
            "outtmpl": os.path.join(folder, "%(title)s.%(ext)s"),
            "progress_hooks": [progress_hook],
            "quiet": True,
            "postprocessor_args": ["-hide_banner", "-loglevel", "error"],
        }
        if ffmpeg_loc:
            # yt-dlp needs the folder containing ffmpeg.exe, not the full path
            ydl_opts["ffmpeg_location"] = os.path.dirname(ffmpeg_loc)

        if fmt == "mp3":
            ydl_opts.update({
                "format": "bestaudio[acodec^=mp4a]/bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            if quality_str == "Best Quality":
                format_string = (
                    "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]"
                    "/bestvideo+bestaudio/best[ext=mp4]/best"
                )
            else:
                match = re.search(r"\d+", quality_str)
                if match:
                    height = match.group()
                    format_string = (
                        f"bestvideo[height<={height}][vcodec^=avc1]+"
                        f"bestaudio[acodec^=mp4a]"
                        f"/bestvideo[height<={height}]+bestaudio"
                        f"/best[height<={height}][ext=mp4]/best"
                    )
                else:
                    format_string = "bestvideo+bestaudio/best"

            ydl_opts.update({
                "format": format_string,
                "merge_output_format": "mp4",
            })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        def on_done():
            progress_bar.set(1)
            update_status("Download complete!", "success")
            download_button.configure(state="normal", text="Download")
            show_toast("Download complete!", "success")

        root.after(0, on_done)

    except Exception as e:
        def on_error():
            update_status("Download failed", "error")
            show_toast(str(e)[:120], "error")
            progress_bar.set(0)
            download_button.configure(state="normal", text="Download")
        root.after(0, on_error)


def progress_hook(d):
    if d["status"] == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if total:
            percent = d["downloaded_bytes"] / total
            speed = d.get("speed") or 0
            speed_str = f"{speed/1024/1024:.1f} MB/s" if speed else ""
            eta = d.get("eta") or 0
            eta_str = f"  ETA {eta}s" if eta else ""

            def upd(p=percent, s=speed_str, e=eta_str):
                progress_bar.set(p)
                update_status(f"Downloading... {p:.0%}  {s}{e}", "muted")
            root.after(0, upd)

    elif d["status"] == "finished":
        root.after(0, lambda: update_status("Merging streams...", "muted"))


# ================================
# COLORS
# ================================
YT_RED       = "#FF0000"
YT_RED_HOVER = "#CC0000"
YT_BG        = "#0F0F0F"
YT_SURFACE   = "#1A1A1A"
YT_SURFACE2  = "#272727"
YT_BORDER    = "#303030"
YT_TEXT      = "#FFFFFF"
YT_MUTED     = "#AAAAAA"
YT_SUCCESS   = "#2BA640"
YT_ERROR     = "#FF4444"

_toast_job = None


def show_toast(msg: str, kind: str = "info"):
    global _toast_job
    colors = {"error": YT_ERROR, "success": YT_SUCCESS, "info": YT_MUTED}
    toast_label.configure(text=msg, text_color=colors.get(kind, YT_MUTED))
    toast_frame.place(relx=0.5, rely=0.97, anchor="s")
    if _toast_job:
        root.after_cancel(_toast_job)
    _toast_job = root.after(4000, lambda: toast_frame.place_forget())


def update_status(msg: str, kind: str = "muted"):
    colors = {"muted": YT_MUTED, "success": YT_SUCCESS, "error": YT_ERROR}
    status_label.configure(text=msg, text_color=colors.get(kind, YT_MUTED))


# ================================
# BUILD UI
# ================================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

root = ctk.CTk()
root.title("YouTube Downloader")
root.resizable(False, False)

W, H = 620, 660
sw = root.winfo_screenwidth()
sh = root.winfo_screenheight()
root.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 2}")
root.configure(fg_color=YT_BG)

# ── HEADER ───────────────────────────────────────────────
header = ctk.CTkFrame(root, fg_color=YT_SURFACE, corner_radius=0, height=64)
header.pack(fill="x")
header.pack_propagate(False)

logo_frame = ctk.CTkFrame(header, fg_color="transparent")
logo_frame.place(relx=0.5, rely=0.5, anchor="center")

yt_box = ctk.CTkFrame(logo_frame, fg_color=YT_RED, corner_radius=6,
                       width=38, height=26)
yt_box.pack(side="left", padx=(0, 8))
yt_box.pack_propagate(False)
ctk.CTkLabel(yt_box, text="▶", font=("Georgia", 14, "bold"),
             text_color="white").place(relx=0.5, rely=0.5, anchor="center")

ctk.CTkLabel(logo_frame, text="YouTube  ", font=("Georgia", 18, "bold"),
             text_color=YT_TEXT).pack(side="left")
ctk.CTkLabel(logo_frame, text="Downloader", font=("Georgia", 18),
             text_color=YT_MUTED).pack(side="left")

update_badge = ctk.CTkButton(
    header, text="Checking...", width=140, height=28,
    fg_color="transparent", hover_color=YT_SURFACE2,
    text_color=YT_MUTED, font=("Helvetica", 11),
    corner_radius=14, command=lambda: None
)
update_badge.place(relx=0.97, rely=0.5, anchor="e")

# ── BODY ─────────────────────────────────────────────────
body = ctk.CTkFrame(root, fg_color=YT_BG)
body.pack(fill="both", expand=True, padx=28, pady=20)

# URL Row
url_row = ctk.CTkFrame(body, fg_color=YT_SURFACE, corner_radius=10,
                        border_width=1, border_color=YT_BORDER)
url_row.pack(fill="x", pady=(0, 10))

url_entry = ctk.CTkEntry(
    url_row,
    placeholder_text="Paste YouTube link here...",
    fg_color="transparent",
    border_width=0,
    text_color=YT_TEXT,
    placeholder_text_color=YT_MUTED,
    font=("Helvetica", 13),
    height=46,
)
url_entry.pack(side="left", fill="x", expand=True, padx=(14, 0))

check_button = ctk.CTkButton(
    url_row, text="Check",
    fg_color=YT_RED, hover_color=YT_RED_HOVER,
    text_color="white", font=("Helvetica", 13, "bold"),
    width=90, height=36, corner_radius=8,
    command=fetch_resolutions
)
check_button.pack(side="right", padx=6)

title_label = ctk.CTkLabel(body, text="", font=("Helvetica", 12),
                            text_color=YT_MUTED, wraplength=540,
                            justify="left", anchor="w")
title_label.pack(fill="x", pady=(0, 10))

# ── FORMAT / QUALITY ─────────────────────────────────────
fq_row = ctk.CTkFrame(body, fg_color="transparent")
fq_row.pack(fill="x", pady=(0, 10))

fmt_card = ctk.CTkFrame(fq_row, fg_color=YT_SURFACE, corner_radius=10,
                         border_width=1, border_color=YT_BORDER)
fmt_card.pack(side="left", fill="both", expand=True, padx=(0, 8))

ctk.CTkLabel(fmt_card, text="FORMAT", font=("Helvetica", 10, "bold"),
             text_color=YT_MUTED).pack(anchor="w", padx=14, pady=(12, 4))

format_var = tk.StringVar(value="mp4")
fmt_inner = ctk.CTkFrame(fmt_card, fg_color="transparent")
fmt_inner.pack(fill="x", padx=14, pady=(0, 12))

for label, val in [("Video  MP4", "mp4"), ("Audio  MP3", "mp3")]:
    ctk.CTkRadioButton(
        fmt_inner, text=label, variable=format_var, value=val,
        fg_color=YT_RED, hover_color=YT_RED_HOVER,
        text_color=YT_TEXT, font=("Helvetica", 12),
        border_color=YT_BORDER
    ).pack(anchor="w", pady=3)

q_card = ctk.CTkFrame(fq_row, fg_color=YT_SURFACE, corner_radius=10,
                       border_width=1, border_color=YT_BORDER)
q_card.pack(side="left", fill="both", expand=True)

ctk.CTkLabel(q_card, text="QUALITY", font=("Helvetica", 10, "bold"),
             text_color=YT_MUTED).pack(anchor="w", padx=14, pady=(12, 6))

quality_var = tk.StringVar(value="Best Quality")
quality_menu = ctk.CTkOptionMenu(
    q_card,
    values=["Best Quality", "1080p", "720p", "480p", "360p"],
    variable=quality_var,
    fg_color=YT_SURFACE2,
    button_color=YT_RED,
    button_hover_color=YT_RED_HOVER,
    text_color=YT_TEXT,
    font=("Helvetica", 12),
    dropdown_fg_color=YT_SURFACE2,
    dropdown_text_color=YT_TEXT,
    dropdown_hover_color=YT_BORDER,
    width=200, height=34, corner_radius=8
)
quality_menu.pack(padx=14, pady=(0, 14), anchor="w")

# ── SAVE PATH ────────────────────────────────────────────
path_card = ctk.CTkFrame(body, fg_color=YT_SURFACE, corner_radius=10,
                          border_width=1, border_color=YT_BORDER)
path_card.pack(fill="x", pady=(0, 10))

path_top = ctk.CTkFrame(path_card, fg_color="transparent")
path_top.pack(fill="x", padx=14, pady=(12, 4))

ctk.CTkLabel(path_top, text="SAVE LOCATION", font=("Helvetica", 10, "bold"),
             text_color=YT_MUTED).pack(side="left")

choose_btn = ctk.CTkButton(
    path_top, text="Browse...",
    fg_color=YT_SURFACE2, hover_color=YT_BORDER,
    text_color=YT_TEXT, font=("Helvetica", 11),
    width=80, height=26, corner_radius=6,
    command=lambda: None
)
choose_btn.pack(side="right")

save_path_var = tk.StringVar(value=load_save_path())
_saved = save_path_var.get()

path_display = ctk.CTkLabel(
    path_card,
    text=("..." + _saved[-50:] if len(_saved) > 52 else _saved) if _saved else "No folder selected",
    font=("Courier", 11),
    text_color=YT_TEXT if _saved else YT_MUTED,
    anchor="w"
)
path_display.pack(fill="x", padx=14, pady=(0, 12))


def choose_save_path():
    folder = filedialog.askdirectory()
    if folder:
        save_path_var.set(folder)
        save_config({"save_path": folder})
        path_display.configure(
            text=folder if len(folder) <= 52 else "..." + folder[-50:],
            text_color=YT_TEXT
        )


choose_btn.configure(command=choose_save_path)

# ── PROGRESS ─────────────────────────────────────────────
progress_bar = ctk.CTkProgressBar(
    body, height=6, corner_radius=3,
    fg_color=YT_SURFACE2, progress_color=YT_RED
)
progress_bar.set(0)
progress_bar.pack(fill="x", pady=(0, 4))

status_label = ctk.CTkLabel(
    body, text="Enter a URL and press Check to begin",
    font=("Helvetica", 11), text_color=YT_MUTED, anchor="w"
)
status_label.pack(fill="x", pady=(0, 12))

# ── DOWNLOAD BUTTON ──────────────────────────────────────
download_button = ctk.CTkButton(
    body,
    text="Download",
    fg_color=YT_RED,
    hover_color=YT_RED_HOVER,
    text_color="white",
    font=("Helvetica", 15, "bold"),
    height=50, corner_radius=10,
    command=start_download,
)
download_button.pack(fill="x")

# ── TOAST ────────────────────────────────────────────────
toast_frame = ctk.CTkFrame(root, fg_color=YT_SURFACE2, corner_radius=8,
                             border_width=1, border_color=YT_BORDER)
toast_label = ctk.CTkLabel(toast_frame, text="", font=("Helvetica", 11),
                            text_color=YT_MUTED, padx=16, pady=8)
toast_label.pack()
toast_frame.place_forget()

# ── YT-DLP UPDATE CHECK ──────────────────────────────────
def on_update_check(status, current, latest):
    def update_ui():
        if status == "update_available":
            update_badge.configure(
                text="Update available",
                text_color=YT_RED,
                fg_color=YT_SURFACE2,
                command=do_update
            )
        else:
            update_badge.configure(
                text=f"yt-dlp {current[:12]}",
                text_color=YT_SUCCESS
            )
    root.after(0, update_ui)


def do_update():
    update_badge.configure(text="Updating...", text_color=YT_MUTED, state="disabled")

    def on_done(status, *args):
        def upd():
            if status == "success":
                update_badge.configure(text="Updated!", text_color=YT_SUCCESS, state="normal")
                show_toast("yt-dlp updated successfully", "success")
            else:
                update_badge.configure(text="Update failed", text_color=YT_ERROR, state="normal")
                show_toast("Update failed — try: pip install --upgrade yt-dlp", "error")
        root.after(0, upd)

    perform_update(on_done)


check_ytdlp_update(on_update_check)

root.mainloop()
