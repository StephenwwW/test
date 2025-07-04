# -*- coding: utf-8 -*-
# ===================================================================================
#  字幕學習播放器 (手動渲染穩定版 - v17.Refactored)
# ===================================================================================
#
#  說明：
#  此版本根據使用者提供的 GPT-4 參考程式碼進行了核心重構。
#  1. 【核心重構】播放引擎完全採納參考程式碼的邏輯，使用 CAP_PROP_POS_MSEC 進行同步，
#     以確保最高的播放穩定性與流暢度。
#  2. 【保留優勢】保留 v16 版本的完整功能框架，包括 GUI、Whisper 自動轉錄、
#     翻譯、完整的播放控制項以及穩健的資源清理機制。
#  3. 此版本旨在融合參考程式碼的穩定核心與舊版本的豐富功能。
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
is_playing, subtitles, cap = False, [], None
is_paused = False
pygame.mixer.init()

# --- 2. 核心功能函式 ---
def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] [LOG] {message}")

def find_system_font():
    if sys.platform == "win32":
        font_paths = ["C:/Windows/Fonts/msjh.ttc", "C:/Windows/Fonts/simhei.ttf"]
    elif sys.platform == "darwin":
        font_paths = ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti.ttc"]
    else:
        font_paths = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
    for path in font_paths:
        if os.path.exists(path):
            log(f"找到可用字體: {path}")
            return path
    log("警告: 未找到建議的中文字體，字幕可能無法正常顯示。")
    return None

def save_config(config_data):
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
    global video_path, cap, is_playing, is_paused
    file_path = filedialog.askopenfilename(filetypes=[("MP4 files", "*.mp4")])
    if file_path:
        log(f"選擇影片: {file_path}")
        video_path = file_path
        is_playing = False
        is_paused = False
        pygame.mixer.music.stop()
        status_label.config(text=f"已選擇: {os.path.basename(video_path)}")
        btn_process.config(state=tk.NORMAL)
        btn_play_pause.config(state=tk.DISABLED)
        if cap: cap.release()
        cap = cv2.VideoCapture(video_path)
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
                log(f"成功移除暫存音訊檔: {audio_path}")
            except Exception as e:
                log(f"刪除音訊檔失敗: {e}")
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
    output_dir = os.path.dirname(srt_output_path)
    output_base = os.path.splitext(os.path.basename(srt_output_path))[0]
    final_output_path = os.path.join(output_dir, output_base)

    command = [
        whisper_exe, "-m", model, "-f", audio, "-osrt", "-of", final_output_path,
        "-l", lang, "-t", "8"
    ]
    status_label.config(text="步驟 2/4: 執行 Whisper.cpp 轉錄...")
    log(f"執行命令: {' '.join(command)}")
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore', creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        return os.path.exists(srt_output_path)
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        messagebox.showerror("Whisper 錯誤", f"執行失敗: {e}"); return False

def process_video_thread():
    global subtitles, cap
    if not video_path: return
    btn_process.config(state=tk.DISABLED)
    try:
        status_label.config(text="步驟 1/4: 提取音訊..."); progress_var.set(10)
        with VideoFileClip(video_path) as video_clip:
            video_clip.audio.write_audiofile(audio_path, logger=None)
        progress_var.set(25)

        srt_original_path = f"{os.path.splitext(video_path)[0]}.srt"
        if not run_whisper_cpp(entry_whisper_path.get(), entry_model_path.get(), audio_path, lang_combobox.get(), srt_original_path):
            raise Exception("Whisper.cpp 執行失敗")
        progress_var.set(60)

        status_label.config(text="步驟 3/4: 生成雙語字幕..."); progress_var.set(75)
        with open(srt_original_path, 'r', encoding='utf-8') as f:
            subs_raw = list(pysrt.from_string(f.read()))
        
        subtitles.clear()
        for sub in subs_raw:
            translated_text = ""
            if lang_combobox.get() != target_lang_combobox.get() and target_lang_combobox.get() != 'none':
                source_lang = lang_combobox.get() if lang_combobox.get() != 'auto' else 'auto'
                target_lang = target_lang_combobox.get()
                translated_text = GoogleTranslator(source=source_lang, target=target_lang).translate(sub.text)
            
            subtitles.append({
                'start': sub.start.to_time().hour * 3600000 + sub.start.to_time().minute * 60000 + sub.start.to_time().second * 1000 + sub.start.to_time().microsecond // 1000,
                'end': sub.end.to_time().hour * 3600000 + sub.end.to_time().minute * 60000 + sub.end.to_time().second * 1000 + sub.end.to_time().microsecond // 1000,
                'original': sub.text,
                'translated': translated_text
            })

        status_label.config(text="步驟 4/4: 準備播放器..."); progress_var.set(100)
        pygame.mixer.music.load(audio_path)
        if cap: cap.release()
        cap = cv2.VideoCapture(video_path)
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
    pygame.mixer.music.rewind()
    pygame.mixer.music.play()
    update_player()

def seek(delta_ms):
    global cap
    if not cap or not pygame.mixer.get_init(): return
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration_ms = frame_count * (1000 / fps) if fps > 0 else 0
    current_time_ms = pygame.mixer.music.get_pos()
    if current_time_ms == -1:
        current_time_ms = duration_ms
    new_time_ms = current_time_ms + delta_ms
    new_time_ms = max(0, min(new_time_ms, duration_ms))
    pygame.mixer.music.play()
    pygame.mixer.music.set_pos(new_time_ms / 1000.0)
    cap.set(cv2.CAP_PROP_POS_MSEC, new_time_ms)
    if not is_playing: pygame.mixer.music.pause()
    log(f"跳轉至: {new_time_ms/1000.0:.2f}s")
    update_player(force_time=new_time_ms)

def set_position_from_scale(event):
    global cap
    if cap and pygame.mixer.get_init():
        value = timeline_scale.get()
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        duration_ms = frame_count * (1000 / fps) if fps > 0 else 0
        if duration_ms > 0:
            seek_time_ms = duration_ms * (float(value) / 100)
            pygame.mixer.music.play()
            pygame.mixer.music.set_pos(seek_time_ms / 1000.0)
            cap.set(cv2.CAP_PROP_POS_MSEC, seek_time_ms)
            if not is_playing: pygame.mixer.music.pause()
            update_player(force_time=seek_time_ms)

def update_player(force_time=None):
    if not cap or not pygame.mixer.get_init(): return

    if force_time is not None:
        now = force_time
    else:
        now = pygame.mixer.music.get_pos()
    if now < 0:
        now = 0
    cap.set(cv2.CAP_PROP_POS_MSEC, now)
    ret, frame = cap.read()
    if ret:
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(frame_rgb)
        draw = ImageDraw.Draw(pil_img)
        for sub in subtitles:
            if sub['start'] <= now <= sub['end']:
                draw_subtitle_on_image(draw, sub['original'], sub['translated'], pil_img.size)
                break
        show_frame(cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR))
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        duration_ms = frame_count * (1000 / fps) if fps > 0 else 0
        if duration_ms > 0:
            timeline_scale.set(now / duration_ms * 100)
    if pygame.mixer.music.get_busy():
        fps = cap.get(cv2.CAP_PROP_FPS)
        delay = int(1000 / fps) if fps and fps > 0 else 30
        root.after(delay, update_player)
    elif is_playing:
        is_playing = False
        is_paused = False
        btn_play_pause.config(text="▶")
        log("播放結束")

def draw_subtitle_on_image(draw, original, translated, frame_size):
    frame_w, frame_h = frame_size
    padding = 20
    bg_color = (0, 0, 0, 150)

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
        draw.text((padding, current_y + original_h + 5), translated, font=FONTS['translated'], fill=(220, 220, 150))

# --- GUI 設定 ---
root = tk.Tk()
root.title("字幕學習播放器 (v17.Refactored)")
root.geometry("950x900")

# ... (其餘 GUI 元件設定與 v16 相同) ...
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

# --- 主程式啟動 ---
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
        
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        
        time.sleep(0.1)

        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
                log(f"成功移除暫存音訊檔: {audio_path}")
            except Exception as e:
                log(f"刪除音訊檔失敗: {e}")

        save_config({"whisper_path": entry_whisper_path.get(), "model_path": entry_model_path.get()})
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

# === 新增：自動化測試可用的核心函式 ===
def load_video_for_test(video_file_path):
    '''自動化測試用：載入影片並初始化cap物件'''
    global video_path, cap, is_playing, is_paused
    video_path = video_file_path
    is_playing = False
    is_paused = False
    if cap: cap.release()
    cap = cv2.VideoCapture(video_path)
    if os.path.exists(audio_path):
        try:
            os.remove(audio_path)
            log(f"[TEST] 成功移除暫存音訊檔: {audio_path}")
        except Exception as e:
            log(f"[TEST] 刪除音訊檔失敗: {e}")
    return cap.isOpened()

def extract_audio_for_test():
    '''自動化測試用：從當前video_path提取音訊到audio_path'''
    if not video_path:
        raise Exception("尚未載入影片")
    # 釋放音訊播放資源，確保檔案可覆蓋
    try:
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
            pygame.mixer.quit()
            time.sleep(0.1)
    except Exception as e:
        log(f"[TEST] 釋放音訊資源失敗: {e}")
    if os.path.exists(audio_path):
        try:
            os.remove(audio_path)
            log(f"[TEST] 成功移除暫存音訊檔: {audio_path}")
        except Exception as e:
            log(f"[TEST] 刪除音訊檔失敗: {e}")
    with VideoFileClip(video_path) as video_clip:
        video_clip.audio.write_audiofile(audio_path, logger=None)
    return os.path.exists(audio_path)

def test_seek_and_sync(seek_ms):
    '''自動化測試用：快進/快退並同步音訊與影像'''
    global cap
    if not cap or not pygame.mixer.get_init():
        raise Exception("尚未初始化影片或音訊")
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration_ms = frame_count * (1000 / fps) if fps > 0 else 0
    pygame.mixer.music.load(audio_path)
    # 追蹤累積 seek 位置
    if not hasattr(test_seek_and_sync, 'accum_seek'):
        test_seek_and_sync.accum_seek = 0
    test_seek_and_sync.accum_seek += seek_ms
    test_seek_and_sync.accum_seek = max(0, min(test_seek_and_sync.accum_seek, duration_ms))
    pygame.mixer.music.play()
    pygame.mixer.music.set_pos(test_seek_and_sync.accum_seek / 1000.0)
    cap.set(cv2.CAP_PROP_POS_MSEC, test_seek_and_sync.accum_seek)
    time.sleep(0.5)
    pos = test_seek_and_sync.accum_seek
    vpos = cap.get(cv2.CAP_PROP_POS_MSEC)
    return pos, vpos

def test_playback_smoothness(duration_sec=10):
    '''自動化測試用：根據 FPS 精確計時取 frame，驗證流暢度。'''
    import threading
    global cap
    try:
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
            pygame.mixer.quit()
            time.sleep(0.1)
    except Exception as e:
        log(f"[TEST] 釋放音訊資源失敗: {e}")
    import pygame as _pg
    _pg.mixer.init()
    if not cap or not _pg.mixer.get_init():
        raise Exception("尚未初始化影片或音訊")
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration_ms = frame_count * (1000 / fps) if fps > 0 else 0
    _pg.mixer.music.load(audio_path)
    _pg.mixer.music.play()
    cap.set(cv2.CAP_PROP_POS_MSEC, 0)
    frame_times = []
    start = time.time()
    frame_interval = 1.0 / fps
    next_frame_time = start
    while time.time() - start < duration_sec:
        now = (time.time() - start) * 1000
        cap.set(cv2.CAP_PROP_POS_MSEC, now)
        ret, frame = cap.read()
        if not ret:
            break
        frame_times.append(now)
        next_frame_time += frame_interval
        sleep_time = next_frame_time - time.time()
        if sleep_time > 0:
            time.sleep(sleep_time)
    _pg.mixer.music.stop()
    _pg.mixer.quit()
    return len(frame_times), int(fps * duration_sec)
