import os
import sys

# === 1. CRITICAL FIX: macOS 16+ Version Crash (Ignored on Windows) ===
os.environ['SYSTEM_VERSION_COMPAT'] = '0'

import tkinter as tk
import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading
import yt_dlp
import stat
import certifi
import re
import json

# === 2. CRITICAL FIX: SSL Certificates ===
os.environ["SSL_CERT_FILE"] = certifi.where()

# === CONFIG FILE LOCATION ===
# Saves to User Home folder (Cross-platform)
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".yt_downloader_config.json")

# === HELPERS ===
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_ffmpeg_path():
    """Finds the path to ffmpeg (Handles .exe for Windows automatically)"""
    # Detect OS: 'nt' means Windows
    if os.name == 'nt':
        binary_name = "ffmpeg.exe"
    else:
        binary_name = "ffmpeg" # Mac/Linux

    ffmpeg_path = binary_name # Default system path

    if getattr(sys, 'frozen', False):
        ffmpeg_path = resource_path(binary_name)
        
        # Permission fix (Only really needed on Mac/Linux, harmless on Windows)
        if os.path.exists(ffmpeg_path):
            try:
                st = os.stat(ffmpeg_path)
                os.chmod(ffmpeg_path, st.st_mode | stat.S_IEXEC)
            except Exception:
                pass
    return ffmpeg_path

def center_window(window, width, height):
    """Centers the window on the screen"""
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    x = int((screen_width / 2) - (width / 2))
    y = int((screen_height / 2) - (height / 2))
    window.geometry(f'{width}x{height}+{x}+{y}')

# === MAIN APP ===
try:
    ctk.set_appearance_mode("dark")
    
    root = ctk.CTk()
    root.title("YT Downloader")
    
    # === YOUTUBE DARK MODE PALETTE ===
    YT_BG = "#0f0f0f"           
    YT_SURFACE = "#272727"      
    YT_SURFACE_HOVER = "#3f3f3f"
    YT_RED = "#ff0000"          
    YT_TEXT_PRI = "#f1f1f1"     
    YT_TEXT_SEC = "#aaaaaa"     
    YT_INPUT_BG = "#121212"     
    YT_BUTTON_FG = "#f1f1f1"    
    YT_BUTTON_TEXT = "#0f0f0f"  

    root.configure(fg_color=YT_BG) 

    window_width = 600
    window_height = 650
    center_window(root, window_width, window_height)
    root.resizable(False, False)

    # Icon Loading (Tries .png first, useful for dev)
    try:
        icon_file = resource_path("icon.png")
        if os.path.exists(icon_file):
            icon_img = tk.PhotoImage(file=icon_file)
            root.iconphoto(True, icon_img)
    except Exception:
        pass

    # --- Logic ---
    def save_config(path):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump({"save_path": path}, f)
        except Exception as e:
            print(f"Could not save config: {e}")

    def load_config():
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    path = data.get("save_path", "")
                    if os.path.exists(path):
                        return path
        except Exception as e:
            print(f"Could not load config: {e}")
        return ""

    def update_path_label(path):
        if path:
            display_path = path
            if len(display_path) > 40:
                display_path = "..." + display_path[-37:]
            path_label.configure(text=f"Saving to: {display_path}")
        else:
            path_label.configure(text="No folder selected")

    def choose_save_path():
        folder = filedialog.askdirectory()
        if folder:
            save_path.set(folder)
            save_config(folder)
            update_path_label(folder)

    def fetch_resolutions():
        url = url_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a URL first.")
            return

        check_button.configure(state="disabled", text="Checking...")
        progress_label.configure(text="Fetching video info...")
        threading.Thread(target=run_fetch, args=(url,), daemon=True).start()

    def run_fetch(url):
        try:
            ydl_opts = {'quiet': True, 'no_warnings': True, 'nocheckcertificate': False}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            
            formats = info.get('formats', [])
            available_heights = set()
            for f in formats:
                if f.get('height') and f.get('vcodec') != 'none':
                    available_heights.add(f['height'])

            sorted_heights = sorted(list(available_heights), reverse=True)
            options = ["Best"] 
            for h in sorted_heights:
                label = f"{h}p"
                if h == 2160: label += " (4K)"
                elif h == 1440: label += " (2K)"
                elif h == 4320: label += " (8K)"
                options.append(label)

            def update_ui():
                quality_menu.configure(values=options)
                quality_var.set(options[0]) 
                check_button.configure(state="normal", text="Check Qualities")
                progress_label.configure(text="Select quality and download.")
                title_label_dynamic.configure(text=f"{info.get('title', 'Video')[:50]}...")

            root.after(0, update_ui)
        except Exception as e:
            def error_ui():
                check_button.configure(state="normal", text="Check Qualities")
                messagebox.showerror("Error", f"Could not fetch info:\n{str(e)}")
                progress_label.configure(text="Error fetching info.")
            root.after(0, error_ui)

    def start_download():
        url = url_entry.get().strip()
        folder = save_path.get().strip()
        fmt = format_var.get()
        quality_str = quality_var.get()

        if not url:
            messagebox.showerror("Error", "Please enter a YouTube URL.")
            return
        if not folder:
            messagebox.showerror("Error", "Please select a save location.")
            return

        download_button.configure(state="disabled", text="Starting...")
        progress_bar.set(0)
        progress_label.configure(text="Initializing...")
        threading.Thread(target=download_video, args=(url, folder, fmt, quality_str), daemon=True).start()

    def download_video(url, folder, fmt, quality_str):
        try:
            ffmpeg_loc = get_ffmpeg_path()
            ydl_opts = {
                "outtmpl": f"{folder}/%(title)s.%(ext)s",
                "progress_hooks": [progress_hook],
                "ffmpeg_location": ffmpeg_loc,
                "quiet": True, "no_warnings": True, "nocheckcertificate": False,
            }

            if fmt == "mp3":
                ydl_opts.update({
                    "format": "bestaudio/best",
                    "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
                })
            else:
                format_string = ""
                if quality_str == "Best": format_string = "bestvideo+bestaudio/best" 
                else:
                    match = re.search(r'\d+', quality_str)
                    if match: format_string = f"bestvideo[height={match.group()}]+bestaudio/best"
                    else: format_string = "bestvideo+bestaudio/best"

                ydl_opts.update({
                    "format": format_string,
                    "merge_output_format": "mp4",
                    "postprocessor_args": {
                        "merger": ["-c:v", "libx264", "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p", "-preset", "fast", "-movflags", "+faststart"] 
                    },
                })

            progress_label.configure(text="Downloading...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            progress_label.configure(text="Download complete!")
            progress_bar.set(1.0)
        except Exception as e:
            err = str(e)
            if "HTTP Error 403" in err: messagebox.showerror("Error", "YouTube 403 Forbidden.")
            else: messagebox.showerror("Error", f"Details: {err}")
            progress_label.configure(text="Error occurred.")
            progress_bar.set(0)
        finally:
            download_button.configure(state="normal", text="Download")

    def progress_hook(d):
        if d['status'] == 'downloading':
            if d.get('total_bytes'):
                p = d['downloaded_bytes'] / d['total_bytes']
                progress_bar.set(p)
                progress_label.configure(text=f"Downloading... {p:.0%}")
        elif d['status'] == 'finished':
            progress_label.configure(text="Converting to H.264...")

    # --- UI LAYOUT ---
    FONT_TITLE = ("Roboto", 22, "bold")
    FONT_TEXT = ("Roboto", 14)
    
    ctk.CTkLabel(root, text="YouTube Downloader", font=FONT_TITLE, text_color=YT_TEXT_PRI).pack(pady=(25,5))
    title_label_dynamic = ctk.CTkLabel(root, text="", font=("Roboto", 12), text_color=YT_TEXT_SEC)
    title_label_dynamic.pack(pady=(0, 15))

    url_frame = ctk.CTkFrame(root, fg_color="transparent")
    url_frame.pack(pady=10)
    
    url_entry = ctk.CTkEntry(
        url_frame, placeholder_text="Paste YouTube Link", width=340, height=40,
        font=FONT_TEXT, fg_color=YT_INPUT_BG, border_color="#303030",
        text_color=YT_TEXT_PRI, corner_radius=20
    )
    url_entry.pack(side="left", padx=(0, 10))
    
    check_button = ctk.CTkButton(
        url_frame, text="Check", width=100, height=40, command=fetch_resolutions, 
        fg_color=YT_SURFACE, text_color=YT_TEXT_PRI, hover_color=YT_SURFACE_HOVER,
        corner_radius=20, font=("Roboto", 13, "bold")
    )
    check_button.pack(side="left")

    format_var = tk.StringVar(value="mp4")
    fr = ctk.CTkFrame(root, fg_color="transparent")
    fr.pack(pady=15)
    ctk.CTkRadioButton(fr, text="Video (MP4)", variable=format_var, value="mp4", fg_color=YT_RED, hover_color=YT_RED, text_color=YT_TEXT_PRI, font=FONT_TEXT).pack(side="left", padx=20)
    ctk.CTkRadioButton(fr, text="Audio (MP3)", variable=format_var, value="mp3", fg_color=YT_RED, hover_color=YT_RED, text_color=YT_TEXT_PRI, font=FONT_TEXT).pack(side="left", padx=20)

    quality_var = tk.StringVar(value="Best")
    ctk.CTkLabel(root, text="Quality Preference", font=("Roboto", 12, "bold"), text_color=YT_TEXT_SEC).pack(pady=(10,5))
    quality_menu = ctk.CTkOptionMenu(
        root, values=["Best", "1080p", "720p"], variable=quality_var, 
        fg_color=YT_SURFACE, button_color=YT_SURFACE, button_hover_color=YT_SURFACE_HOVER,
        text_color=YT_TEXT_PRI, width=250, height=35, corner_radius=18
    )
    quality_menu.pack(pady=5)

    save_path = tk.StringVar()
    previous_path = load_config()
    if previous_path:
        save_path.set(previous_path)

    ctk.CTkButton(
        root, text="Choose Save Folder", fg_color=YT_SURFACE, text_color=YT_TEXT_PRI,
        hover_color=YT_SURFACE_HOVER, command=choose_save_path,
        height=35, width=250, corner_radius=18, font=("Roboto", 13)
    ).pack(pady=(15, 5))

    path_label = ctk.CTkLabel(root, text="No folder selected", font=("Roboto", 11), text_color=YT_TEXT_SEC)
    path_label.pack(pady=(0, 10))
    update_path_label(previous_path)

    progress_bar = ctk.CTkProgressBar(root, width=450, height=8, progress_color=YT_RED, fg_color=YT_SURFACE)
    progress_bar.set(0)
    progress_bar.pack(pady=(15, 5))
    progress_label = ctk.CTkLabel(root, text="Ready to download", font=("Roboto", 12), text_color=YT_TEXT_SEC)
    progress_label.pack(pady=5)

    download_button = ctk.CTkButton(
        root, text="Download", command=start_download, fg_color=YT_BUTTON_FG, 
        text_color=YT_BUTTON_TEXT, hover_color="#e0e0e0", font=("Roboto", 15, "bold"), 
        height=45, width=250, corner_radius=25
    )
    download_button.pack(pady=25)

    root.mainloop()

except Exception as e:
    import tkinter.messagebox
    root = tk.Tk()
    root.withdraw()
    tkinter.messagebox.showerror("Startup Error", str(e))