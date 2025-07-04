# -*- coding: utf-8 -*-
# ===================================================================================
#  字幕學習播放器 (手動渲染穩定版 - v16.Fix)
# ===================================================================================
#
#  說明：
#  此版本為重大問題修復版，旨在徹底解決使用者回報的核心問題。
#  1. 【修復】影像卡死問題：採用強制同步策略，確保影像絕對跟隨音訊時間，解決卡在固定畫面的問題。
#  2. 【修復】字幕不顯示問題：採用智慧型跨平台字體搜尋機制，解決因找不到字體而無法顯示字幕的問題。
#  3. 【修復】暫存檔未刪除問題：優化程式關閉流程，確保音訊暫存檔能被成功移除。
#
# ===================================================================================

import tkinter as tk
from tkinter import filedialog, ttk, messagebox, Frame, Label, Entry
import threading, os, sys, json, subprocess, cv2, pysrt
from deep_translator import GoogleTranslator
from moviepy.editor import VideoFileClip
from PIL import Image, ImageTk, ImageFont, ImageDraw
import pygame
import numpy as np
import time

# --- 1. 全域變數與初始化 ---
CONFIG_FILE, video_path, audio_path = "config.json", None, "temp_audio.wav"
is_playing, subtitles, cap, fps = False, [], None, 30
is_paused = False
pygame.mixer.init()

# --- 2. 核心功能函式 ---
def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] [LOG] {message}")

def find_system_font():
    """
    【新】智慧型字體搜尋函式，用於解決字幕無法顯示的問題。
    它會搜尋常見的跨平台中文字體。
    """
    if sys.platform == "win32":
        font_paths = ["C:/Windows/Fonts/msjh.ttc", "C:/Windows/Fonts/simhei.ttf"] # 微軟正黑體, 黑體
    elif sys.platform == "darwin": # macOS
        font_paths = ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti.ttc"]
    else: # Linux
        font_paths = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]

    for path in font_paths:
        if os.path.exists(path):
            log(f"找到可用字體: {path}")
            return path
    
    log("警告: 未找到建議的中文字體，字幕可能無法正常顯示。將使用預設字體。")
    return None

def save_config(config_data):
    log(f"儲存設定檔: {config_data}")
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(config_data, f, indent=4)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except json.JSONDecodeError: return {}
    return {}

def browse_file(entry_widget):
    path = filedialog.askopenfilename()
    if path:
        entry_widget.delete(0, tk.END)
        entry_widget.insert(0, path)

def select_video():
    global video_path, cap, fps, is_playing, is_paused
    file_path = filedialog.askopenfilename(filetypes=[("MP4 files", "*.mp4")])
    if file_path:
        log(f"使用者選擇影片: {file_path}")
        video_path = file_path
        is_playing = False
        is_paused = False
        pygame.mixer.music.stop()
        status_label.config(text=f"已選擇影片: {os.path.basename(video_path)}")
        btn_process.config(state=tk.NORMAL)
        btn_play_pause.config(state=tk.DISABLED)
        if cap: cap.release()
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) if cap.get(cv2.CAP_PROP_FPS) > 0 else 30
        if cap.isOpened():
            ret, frame = cap.read()
            if ret: show_frame(frame)

def show_frame(frame):
    img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    canvas_w, canvas_h = video_canvas.winfo_width(), video_canvas.winfo_height()
    if canvas_w > 1 and canvas_h > 1: img.thumbnail((canvas_w, canvas_h), Image.Resampling.LANCZOS)
    imgtk = ImageTk.PhotoImage(image=img)
    video_canvas.create_image(0, 0, anchor=tk.NW, image=imgtk)
    video_canvas.image = imgtk

def run_whisper_cpp(whisper_exe, model, audio, lang, srt_output_path):
    output_dir, output_base = os.path.dirname(srt_output_path), os.path.splitext(os.path.basename(srt_output_path))[0]
    command = [
        whisper_exe, "-m", model, "-f", audio, "-osrt", "-of", os.path.join(output_dir, output_base),
        "-l", lang, "-t", "8", "-bs", "8", "-bo", "8", "-et", "2.2", "-nth", "0.65", "-nf", "-tdrz"
    ]
    status_label.config(text="步驟 2/4: 正在執行 whisper.cpp 辨識...")
    log(f"執行 Whisper.cpp 命令: {' '.join(command)}")
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore', creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        return os.path.exists(srt_output_path)
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        messagebox.showerror("Whisper 錯誤", f"whisper.cpp 執行失敗: {e}"); return False

def process_video_thread():
    global subtitles, cap, fps
    if not video_path: return
    btn_process.config(state=tk.DISABLED)
    try:
        status_label.config(text="步驟 1/4: 正在提取音訊..."); progress_var.set(10)
        with VideoFileClip(video_path) as video_clip:
            video_clip.audio.write_audiofile(audio_path, logger=None)
        progress_var.set(25)

        srt_original_path = f"{os.path.splitext(video_path)[0]}.srt"
        if not run_whisper_cpp(entry_whisper_path.get(), entry_model_path.get(), audio_path, lang_combobox.get(), srt_original_path):
            raise Exception("whisper.cpp 執行失敗")
        progress_var.set(60)

        status_label.config(text="步驟 3/4: 正在使用 Google Translate 生成雙語字幕..."); progress_var.set(75)
        subs_raw = pysrt.open(srt_original_path, encoding='utf-8')
        subtitles.clear()
        for sub in subs_raw:
            translated_text = ""
            if lang_combobox.get() != target_lang_combobox.get() and target_lang_combobox.get() != 'none':
                source_lang = lang_combobox.get() if lang_combobox.get() != 'auto' else 'auto'
                target_lang = target_lang_combobox.get()
                translated_text = GoogleTranslator(source=source_lang, target=target_lang).translate(sub.text)
            subtitles.append({'start': sub.start.ordinal, 'end': sub.end.ordinal, 'original': sub.text, 'translated': translated_text})

        status_label.config(text="步驟 4/4: 準備播放器..."); progress_var.set(100)
        pygame.mixer.music.load(audio_path)
        if cap: cap.release()
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        status_label.config(text="處理完成！可以播放影片。")
        controls_frame.pack(pady=10)
        btn_play_pause.config(state=tk.NORMAL)
    except Exception as e:
        messagebox.showerror("處理錯誤", f"發生錯誤: {e}")
        status_label.config(text="處理失敗，請重試。")
    finally:
        btn_process.config(state=tk.NORMAL)

def start_processing():
    threading.Thread(target=process_video_thread, daemon=True).start()

def play_pause():
    global is_playing, is_paused
    if is_playing:
        is_playing = False
        is_paused = True
        pygame.mixer.music.pause()
        btn_play_pause.config(text="▶")
        log("動作: 暫停")
    else:
        is_playing = True
        if is_paused:
            is_paused = False
            pygame.mixer.music.unpause()
            log("動作: 恢復播放")
        else:
            log("動作: 從頭播放")
            if cap: cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            pygame.mixer.music.play()
        btn_play_pause.config(text="❚❚")
        update_player()

def replay():
    log("動作: 重新播放")
    global is_playing, is_paused
    is_paused = False
    if not is_playing:
        is_playing = True
        btn_play_pause.config(text="❚❚")
    if cap: cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    pygame.mixer.music.rewind()
    pygame.mixer.music.play()
    update_player()

def seek(delta_ms):
    if not cap or not pygame.mixer.get_init(): return
    duration_ms = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps * 1000
    current_time_ms = pygame.mixer.music.get_pos()
    if current_time_ms == -1: current_time_ms = duration_ms
    new_time_ms = current_time_ms + delta_ms
    new_time_ms = max(0, min(new_time_ms, duration_ms))
    pygame.mixer.music.play(start=new_time_ms / 1000.0)
    if not is_playing: pygame.mixer.music.pause()
    log(f"動作: 跳轉至 {new_time_ms/1000.0:.2f}s")
    # 強制立即更新一次畫面以反映跳轉
    update_player(force_update=True)

def set_position_from_scale(event):
    if cap and pygame.mixer.get_init():
        value = timeline_scale.get()
        duration_ms = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps * 1000
        if duration_ms > 0:
            seek_time_ms = duration_ms * (float(value) / 100)
            pygame.mixer.music.play(start=seek_time_ms / 1000.0)
            if not is_playing: pygame.mixer.music.pause()
            # 強制立即更新一次畫面以反映跳轉
            update_player(force_update=True)

def update_player(force_update=False):
    if (not is_playing and not force_update) or not cap:
        return

    current_time_ms = pygame.mixer.music.get_pos()
    if current_time_ms == -1 and is_playing:
        is_playing = False
        is_paused = False
        btn_play_pause.config(text="▶")
        log("播放結束")
        return

    # --- 【核心修復】強制影音同步 ---
    target_frame_num = int((current_time_ms / 1000.0) * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame_num)
    ret, frame = cap.read()
    
    if ret:
        subtitle_layer_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(subtitle_layer_img)
        for sub in subtitles:
            if sub['start'] <= current_time_ms <= sub['end']:
                # 【新】增加日誌，用於除錯字幕是否觸發
                log(f"顯示字幕: {sub['original']}")
                draw_subtitle_on_image(draw, sub['original'], sub['translated'], (frame.shape[1], frame.shape[0]))
                break
        
        show_frame(cv2.cvtColor(np.array(subtitle_layer_img), cv2.COLOR_RGB2BGR))
        
        duration_ms = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps * 1000
        if duration_ms > 0:
            timeline_scale.set(current_time_ms / duration_ms * 100)
    
    if is_playing:
        delay = max(1, int(1000 / fps))
        root.after(delay, update_player)

def draw_subtitle_on_image(draw, original, translated, frame_size):
    frame_w, frame_h = frame_size
    padding = 20
    bg_color = (0, 0, 0, 150) # 半透明黑色背景

    original_bbox = draw.textbbox((0, 0), original, font=FONTS['original'])
    original_h = original_bbox[3] - original_bbox[1]
    
    translated_h = 0
    if translated:
        translated_bbox = draw.textbbox((0, 0), translated, font=FONTS['translated'])
        translated_h = translated_bbox[3] - translated_bbox[1]

    total_h = original_h + translated_h + 30
    
    draw.rectangle(((0, frame_h - total_h), (frame_w, frame_h)), fill=bg_color)
    
    current_y = frame_h - total_h + 15
    draw.text((padding, current_y), original, font=FONTS['original'], fill=(255, 255, 255))
    if translated:
        draw.text((padding, current_y + original_h + 5), translated, font=FONTS['translated'], fill=(220, 220, 150)) # 翻譯使用淡黃色以區分

# --- GUI ---
root = tk.Tk()
root.title("字幕學習播放器 (v16.Fix)")
root.geometry("950x900")

settings_frame = ttk.LabelFrame(root, text="路徑設定", padding=(10, 5)); settings_frame.pack(padx=10, pady=10, fill="x")
entries = {}
for i, (key, text, cmd) in enumerate([("whisper", "whisper.cpp 執行檔:", browse_file), ("model", "模型檔案路徑:", browse_file)]):
    Label(settings_frame, text=text).grid(row=i, column=0, sticky="w", padx=5, pady=2)
    entry = Entry(settings_frame, width=70); entry.grid(row=i, column=1, padx=5, pady=2)
    ttk.Button(settings_frame, text="瀏覽...", command=lambda e=entry, c=cmd: c(e)).grid(row=i, column=2, padx=5, pady=2)
    entries[key] = entry
entry_whisper_path, entry_model_path = entries["whisper"], entries["model"]

lang_options_frame = ttk.LabelFrame(root, text="語言選項", padding=(10, 5)); lang_options_frame.pack(padx=10, pady=5, fill="x")
Label(lang_options_frame, text="辨識:").pack(side="left")
lang_combobox = ttk.Combobox(lang_options_frame, values=['auto', 'ja', 'en', 'zh'], width=10, state="readonly"); lang_combobox.set('auto')
lang_combobox.pack(side="left", padx=5)
Label(lang_options_frame, text="翻譯成:").pack(side="left", padx=(10, 5))
target_lang_combobox = ttk.Combobox(lang_options_frame, values=['zh-TW', 'en', 'ja', 'ko', 'none'], width=10, state="readonly"); target_lang_combobox.set('zh-TW')
target_lang_combobox.pack(side="left", padx=5)

main_frame = Frame(root); main_frame.pack(pady=10, padx=10, fill="both", expand=True)
video_canvas = tk.Canvas(main_frame, bg="black"); video_canvas.pack(fill="both", expand=True)
status_label = tk.Label(main_frame, text="請設定路徑並選擇影片檔案", font=("Arial", 12)); status_label.pack(pady=5)
progress_var = tk.DoubleVar()
progress_bar = ttk.Progressbar(main_frame, variable=progress_var, maximum=100); progress_bar.pack(pady=5, fill="x", padx=10)

controls_frame = tk.Frame(root)
timeline_scale = ttk.Scale(controls_frame, from_=0, to=100, orient="horizontal")
timeline_scale.bind("<ButtonRelease-1>", set_position_from_scale)
timeline_scale.pack(fill="x", expand=True, padx=10, pady=(0,5))
buttons_frame = tk.Frame(controls_frame); buttons_frame.pack()
btn_replay = ttk.Button(buttons_frame, text="|◀", command=replay, width=5); btn_replay.pack(side="left", padx=5)
btn_rewind = ttk.Button(buttons_frame, text="◀◀ 5s", command=lambda: seek(-5000), width=8); btn_rewind.pack(side="left", padx=5)
btn_play_pause = ttk.Button(buttons_frame, text="▶", command=play_pause, width=5, state=tk.DISABLED); btn_play_pause.pack(side="left", padx=5)
btn_forward = ttk.Button(buttons_frame, text="5s ▶▶", command=lambda: seek(5000), width=8); btn_forward.pack(side="left", padx=5)

top_buttons_frame = tk.Frame(root); top_buttons_frame.pack(pady=(5,10))
btn_select = ttk.Button(top_buttons_frame, text="選擇影片", command=select_video); btn_select.pack(side="left", padx=5)
btn_process = ttk.Button(top_buttons_frame, text="處理影片", command=start_processing, state=tk.DISABLED); btn_process.pack(side="left", padx=5)

if __name__ == "__main__":
    config = load_config()
    if config:
        entry_whisper_path.insert(0, config.get("whisper_path", ""))
        entry_model_path.insert(0, config.get("model_path", ""))
    
    final_font_path = find_system_font()
    FONTS = {
        'original': ImageFont.truetype(final_font_path, 36) if final_font_path else ImageFont.load_default(size=36),
        'translated': ImageFont.truetype(final_font_path, 32) if final_font_path else ImageFont.load_default(size=32)
    }

    def on_closing():
        global is_playing
        log("正在關閉程式...")
        is_playing = False
        if cap: cap.release()
        
        # --- 【核心修復】確保音訊檔被釋放和刪除 ---
        if pygame.mixer.get_init():
            pygame.mixer.music.stop() # 1. 先停止音樂
            pygame.mixer.quit()       # 2. 再退出 mixer
        
        # 等待一小段時間確保檔案控制碼被釋放
        time.sleep(0.1)

        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
                log(f"成功移除暫存音訊檔: {audio_path}")
            except Exception as e:
                log(f"關閉時刪除音訊檔失敗: {e}")

        save_config({"whisper_path": entry_whisper_path.get(), "model_path": entry_model_path.get()})
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()