# -*- coding: utf-8 -*-
# ===================================================================================
#  字幕學習播放器 (VLC 穩定版 - v8.Final)
# ===================================================================================
#
#  說明：
#  此版本使用 VLC 作為後端播放引擎，並提供硬體解碼開關以解決播放卡頓問題。
#
#  如何使用：
#  1. 安裝 VLC 播放器主程式 (https://www.videolan.org/vlc/)
#  2. pip install Pillow tkinter opencv-python moviepy pysrt deep_translator python-vlc
#  3. 從命令提示字元 (cmd) 執行 `python your_script_name.py` 以查看後台日誌。
#  4. 若播放時暫停或拖曳後卡頓，請勾選「停用硬體解碼」後再重新處理影片。
#
# ===================================================================================

import tkinter as tk
from tkinter import filedialog, ttk, messagebox, Frame, Label, Entry, Checkbutton, BooleanVar
import threading, os, sys, json, subprocess, cv2, pysrt, vlc
from deep_translator import GoogleTranslator
from moviepy.editor import VideoFileClip
from PIL import Image, ImageTk

# --- 1. 全域變數與初始化 ---
CONFIG_FILE, video_path, audio_path = "config.json", None, "temp_audio.wav"
srt_original_path_global, srt_backup_path_global = None, None
vlc_instance, vlc_player = None, None

# --- 2. 核心功能函式 ---
def log(message): print(f"[LOG] {message}")

def save_config(config_data):
    log(f"儲存設定檔: {config_data}")
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(config_data, f, indent=4)

def load_config():
    if os.path.exists(CONFIG_FILE):
        log(f"找到設定檔: {CONFIG_FILE}")
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except json.JSONDecodeError: return {}
    log("未找到設定檔。")
    return {}

def auto_detect_vlc_path():
    if sys.platform != "win32": return None
    for p_env in ["ProgramFiles", "ProgramFiles(x86)"]:
        path = os.path.join(os.environ.get(p_env, ""), "VideoLAN", "VLC")
        if os.path.isdir(path) and os.path.exists(os.path.join(path, "vlc.exe")):
            log(f"自動偵測到 VLC 路徑: {path}")
            return path
    log("自動偵測 VLC 路徑失敗。")
    return None

def select_video():
    global video_path
    file_path = filedialog.askopenfilename(filetypes=[("MP4 files", "*.mp4")])
    if file_path:
        log(f"使用者選擇影片: {file_path}")
        video_path = file_path
        status_label.config(text=f"已選擇影片: {os.path.basename(video_path)}")
        progress_var.set(0)
        btn_process.config(state=tk.NORMAL)
        if vlc_player and vlc_player.is_playing(): vlc_player.stop()
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret: show_preview_frame(frame)
            cap.release()

def show_preview_frame(frame):
    img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    canvas_w, canvas_h = video_canvas.winfo_width(), video_canvas.winfo_height()
    if canvas_w > 1 and canvas_h > 1: img.thumbnail((canvas_w, canvas_h), Image.Resampling.LANCZOS)
    imgtk = ImageTk.PhotoImage(image=img)
    video_canvas.create_image(0, 0, anchor=tk.NW, image=imgtk)
    video_canvas.image = imgtk

def run_whisper_cpp(whisper_exe, model, audio, lang, srt_output_path):
    output_dir, output_base = os.path.dirname(srt_output_path), os.path.splitext(os.path.basename(srt_output_path))[0]
    command = [whisper_exe, "-m", model, "-f", audio, "-osrt", "-of", os.path.join(output_dir, output_base), "-l", lang, "-t", "8"]
    status_label.config(text="步驟 2/4: 正在執行 whisper.cpp 辨識...")
    log(f"執行 Whisper.cpp 命令: {' '.join(command)}")
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore', creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        return os.path.exists(srt_output_path)
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        messagebox.showerror("Whisper 錯誤", f"whisper.cpp 執行失敗: {e}")
        return False

def process_video_thread():
    global srt_original_path_global, srt_backup_path_global
    if not video_path: return
    whisper_exe_path, model_path = entry_whisper_path.get(), entry_model_path.get()
    source_lang, target_lang = lang_combobox.get(), target_lang_combobox.get()
    if not all(os.path.exists(p) for p in [whisper_exe_path, model_path]):
        messagebox.showerror("設定錯誤", "請檢查 whisper.cpp 執行檔與模型之路徑。")
        return

    btn_process.config(state=tk.DISABLED)
    try:
        status_label.config(text="步驟 1/4: 正在提取音訊..."); progress_var.set(10)
        VideoFileClip(video_path).audio.write_audiofile(audio_path, logger=None)
        progress_var.set(25)

        srt_original_path_global = f"{os.path.splitext(video_path)[0]}.srt"
        if not run_whisper_cpp(whisper_exe_path, model_path, audio_path, source_lang, srt_original_path_global):
            raise Exception("whisper.cpp 執行失敗")
        progress_var.set(60)

        status_label.config(text="步驟 3/4: 正在生成雙語字幕檔...")
        subs = pysrt.open(srt_original_path_global, encoding='utf-8')
        combined_srt_path = f"{os.path.splitext(video_path)[0]}_combined.srt"
        with open(combined_srt_path, 'w', encoding='utf-8') as f:
            for i, sub in enumerate(subs):
                translated_text = GoogleTranslator(source=source_lang if source_lang != 'auto' else 'auto', target=target_lang).translate(sub.text) if source_lang != target_lang and target_lang != 'none' else ""
                f.write(f"{i+1}\n{sub.start} --> {sub.end}\n{sub.text}\n")
                if translated_text: f.write(f"{translated_text}\n")
                f.write("\n")
                progress_var.set(60 + ((i + 1) / len(subs) * 35))
        
        srt_backup_path_global = f"{srt_original_path_global}.bak"
        if os.path.exists(srt_backup_path_global): os.remove(srt_backup_path_global)
        os.rename(srt_original_path_global, srt_backup_path_global)
        log(f"已將 '{os.path.basename(srt_original_path_global)}' 更名為 '{os.path.basename(srt_backup_path_global)}'")

        status_label.config(text="步驟 4/4: 準備播放器..."); progress_var.set(100)
        setup_vlc_player(combined_srt_path)
        status_label.config(text="處理完成！可以播放影片。")
        controls_frame.pack(pady=10)

    except Exception as e:
        messagebox.showerror("處理錯誤", f"發生錯誤: {e}")
        status_label.config(text="處理失敗，請重試。")
    finally:
        if os.path.exists(audio_path):
            try: os.remove(audio_path); log(f"已刪除暫存檔: {audio_path}")
            except OSError as e: log(f"刪除暫存檔失敗: {e}")
        btn_process.config(state=tk.NORMAL)

def start_processing():
    threading.Thread(target=process_video_thread, daemon=True).start()

def setup_vlc_player(subtitle_path=None):
    global vlc_instance, vlc_player
    vlc_install_path = entry_vlc_path.get()
    if not vlc_install_path or not os.path.isdir(vlc_install_path):
        messagebox.showerror("VLC 錯誤", "請先在上方設定有效的 VLC 安裝資料夾！"); return
    
    if vlc_player: vlc_player.stop()
    
    if sys.platform.startswith('win'):
        try: os.add_dll_directory(vlc_install_path)
        except (AttributeError, FileNotFoundError): os.environ['VLC_PLUGIN_PATH'] = vlc_install_path
    
    vlc_instance_args = ["--no-sub-autodetect-file"]
    if hw_decode_disabled.get():
        vlc_instance_args.append("--avcodec-hw=none")
        log("硬體解碼已停用。")

    try:
        vlc_instance = vlc.Instance(vlc_instance_args)
        log(f"VLC 實例已建立，參數: {vlc_instance_args}")
    except Exception as e:
        messagebox.showerror("VLC 錯誤", f"無法初始化 VLC 實例。\n錯誤訊息: {e}"); return
    
    vlc_player = vlc_instance.media_player_new()
    media = vlc_instance.media_new(video_path)
    vlc_player.set_media(media)
    
    if subtitle_path and os.path.exists(subtitle_path):
        vlc_player.video_set_subtitle_file(subtitle_path)
        log(f"已強制設定字幕檔: {subtitle_path}")
    
    if sys.platform == "win32": vlc_player.set_hwnd(video_canvas.winfo_id())
    else: vlc_player.set_xwindow(video_canvas.winfo_id())

def play_pause():
    if not vlc_player: return
    # 【修正】使用 set_pause() 來精確控制播放與暫停，避免卡頓
    if vlc_player.is_playing():
        vlc_player.set_pause(1)
        btn_play_pause.config(text="▶")
        log("動作: 暫停")
    else:
        # 如果是停止或結束狀態，則從頭播放
        if vlc_player.get_state() in [vlc.State.Stopped, vlc.State.Ended]:
             vlc_player.play()
        else: # 如果是暫停狀態，則恢復播放
             vlc_player.set_pause(0)
        btn_play_pause.config(text="❚❚")
        update_timeline()
        log("動作: 播放 / 恢復")

def replay():
    if vlc_player:
        log("動作: 重新播放")
        vlc_player.stop()
        vlc_player.play()
        btn_play_pause.config(text="❚❚")
        update_timeline()

def seek(delta):
    if vlc_player:
        new_time = vlc_player.get_time() + delta * 1000
        vlc_player.set_time(new_time)
        log(f"動作: 跳轉 {delta}s 至 {new_time}ms")

def set_position(value):
    if vlc_player and vlc_player.get_media():
        vlc_player.set_position(float(value) / 100)
        log(f"動作: 拖曳進度條至 {float(value):.1f}%")

def update_timeline():
    if vlc_player and vlc_player.is_playing():
        timeline_scale.set(vlc_player.get_position() * 100)
        root.after(500, update_timeline)

def browse_directory(entry_widget):
    path = filedialog.askdirectory()
    if path: entry_widget.delete(0, tk.END); entry_widget.insert(0, path)

def browse_file(entry_widget):
    path = filedialog.askopenfilename()
    if path: entry_widget.delete(0, tk.END); entry_widget.insert(0, path)

# --- GUI ---
root = tk.Tk()
root.title("字幕學習播放器 (VLC 穩定版 - v8.Final)")
root.geometry("950x900")

settings_frame = ttk.LabelFrame(root, text="路徑設定", padding=(10, 5))
settings_frame.pack(padx=10, pady=10, fill="x")
# GUI widgets setup...
entries = {}
for i, (key, text, cmd) in enumerate([("vlc", "VLC 安裝資料夾:", browse_directory), 
                                     ("whisper", "whisper.cpp 執行檔:", browse_file), 
                                     ("model", "模型檔案路徑:", browse_file)]):
    Label(settings_frame, text=text).grid(row=i, column=0, sticky="w", padx=5, pady=2)
    entry = Entry(settings_frame, width=70)
    entry.grid(row=i, column=1, padx=5, pady=2)
    ttk.Button(settings_frame, text="瀏覽...", command=lambda e=entry, c=cmd: c(e)).grid(row=i, column=2, padx=5, pady=2)
    entries[key] = entry
entry_vlc_path, entry_whisper_path, entry_model_path = entries["vlc"], entries["whisper"], entries["model"]

# 硬體解碼開關
hw_decode_disabled = BooleanVar()
Checkbutton(settings_frame, text="停用硬體解碼 (若播放卡頓請勾選)", variable=hw_decode_disabled).grid(row=0, column=3, padx=10, sticky="w")

lang_options_frame = ttk.LabelFrame(root, text="語言選項", padding=(10, 5))
lang_options_frame.pack(padx=10, pady=5, fill="x")
Label(lang_options_frame, text="辨識:").pack(side="left")
lang_combobox = ttk.Combobox(lang_options_frame, values=['auto', 'ja', 'en', 'zh'], width=10, state="readonly"); lang_combobox.set('auto')
lang_combobox.pack(side="left", padx=5)
Label(lang_options_frame, text="翻譯成:").pack(side="left", padx=(10, 5))
target_lang_combobox = ttk.Combobox(lang_options_frame, values=['zh-TW', 'en', 'ja', 'ko', 'none'], width=10, state="readonly"); target_lang_combobox.set('zh-TW')
target_lang_combobox.pack(side="left", padx=5)

main_frame = Frame(root)
main_frame.pack(pady=10, padx=10, fill="both", expand=True)
video_canvas = tk.Canvas(main_frame, bg="black"); video_canvas.pack(fill="both", expand=True)
status_label = tk.Label(main_frame, text="請設定路徑並選擇影片檔案", font=("Arial", 12)); status_label.pack(pady=5)
progress_var = tk.DoubleVar()
progress_bar = ttk.Progressbar(main_frame, variable=progress_var, maximum=100); progress_bar.pack(pady=5, fill="x", padx=10)

controls_frame = tk.Frame(root)
timeline_scale = ttk.Scale(controls_frame, from_=0, to=100, orient="horizontal", command=set_position)
timeline_scale.pack(fill="x", expand=True, padx=10, pady=(0,5))
buttons_frame = tk.Frame(controls_frame); buttons_frame.pack()
btn_replay = ttk.Button(buttons_frame, text="|◀", command=replay, width=5); btn_replay.pack(side="left", padx=5)
btn_rewind = ttk.Button(buttons_frame, text="◀◀ 5s", command=lambda: seek(-5), width=8); btn_rewind.pack(side="left", padx=5)
btn_play_pause = ttk.Button(buttons_frame, text="▶", command=play_pause, width=5); btn_play_pause.pack(side="left", padx=5)
btn_forward = ttk.Button(buttons_frame, text="5s ▶▶", command=lambda: seek(5), width=8); btn_forward.pack(side="left", padx=5)

top_buttons_frame = tk.Frame(root)
top_buttons_frame.pack(pady=(5,10))
btn_select = ttk.Button(top_buttons_frame, text="選擇影片", command=select_video); btn_select.pack(side="left", padx=5)
btn_process = ttk.Button(top_buttons_frame, text="處理影片", command=start_processing, state=tk.DISABLED); btn_process.pack(side="left", padx=5)

if __name__ == "__main__":
    config = load_config()
    if config:
        entry_vlc_path.insert(0, config.get("vlc_path", ""))
        entry_whisper_path.insert(0, config.get("whisper_path", ""))
        entry_model_path.insert(0, config.get("model_path", ""))
        hw_decode_disabled.set(config.get("hw_decode_disabled", False))
        if not config.get("vlc_path") or not os.path.isdir(config.get("vlc_path")):
            detected_vlc_path = auto_detect_vlc_path()
            if detected_vlc_path: entry_vlc_path.delete(0, tk.END); entry_vlc_path.insert(0, detected_vlc_path)
    else:
        detected_vlc_path = auto_detect_vlc_path()
        if detected_vlc_path: entry_vlc_path.insert(0, detected_vlc_path)

    def on_closing():
        log("正在關閉程式...")
        config_to_save = {
            "vlc_path": entry_vlc_path.get(), 
            "whisper_path": entry_whisper_path.get(), 
            "model_path": entry_model_path.get(),
            "hw_decode_disabled": hw_decode_disabled.get()
        }
        save_config(config_to_save)
        if vlc_player: vlc_player.stop()
        if srt_backup_path_global and os.path.exists(srt_backup_path_global):
            if os.path.exists(srt_original_path_global): os.remove(srt_original_path_global)
            os.rename(srt_backup_path_global, srt_original_path_global)
            log(f"已將字幕檔還原為: {os.path.basename(srt_original_path_global)}")
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
