import sys, os, time
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog, QSlider, QComboBox, QMessageBox, QInputDialog)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont
import pysrt
from deep_translator import GoogleTranslator
from moviepy.editor import VideoFileClip
import vlc
import subprocess
import shlex
import traceback

# 使用腳本所在目錄作為基準目錄
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

class SubtitleWidget(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: rgba(0,0,0,0);")
        self.setAlignment(Qt.AlignBottom | Qt.AlignLeft)
        self.setFont(QFont("Arial", 24))
        self.subs = []
        self.translated = []
    def set_subtitles(self, subs, translated):
        self.subs = subs
        self.translated = translated
    def update_subtitle(self, ms):
        text = ""
        for i, sub in enumerate(self.subs):
            start = sub[3] if len(sub) > 3 else 0
            end = sub[4] if len(sub) > 4 else 0
            if start <= ms <= end:
                text = sub[0] if len(sub) > 0 else ''
                break
        self.setText(text)

class VideoProcessThread(QThread):
    finished = pyqtSignal(list, list, str)
    error = pyqtSignal(str)
    def __init__(self, video_path, lang, target_lang, whisper_path, model_path):
        super().__init__()
        self.video_path = video_path
        self.lang = lang
        self.target_lang = target_lang
        self.whisper_path = whisper_path
        self.model_path = model_path
    def run(self):
        import pysrt
        from deep_translator import GoogleTranslator
        from moviepy.editor import VideoFileClip
        import subprocess, os, traceback
        try:
            audio_path = os.path.abspath("temp_audio.wav")
            if os.path.exists(audio_path):
                try: os.remove(audio_path)
                except Exception: pass
            with VideoFileClip(self.video_path) as video_clip:
                video_clip.audio.write_audiofile(audio_path, logger=None)
            srt_base = os.path.splitext(self.video_path)[0]
            srt_path_orig = srt_base + "_orig.srt"
            # 只產生原文字幕
            command_transcribe = [
                os.path.abspath(self.whisper_path),
                "-m", os.path.abspath(self.model_path),
                "-f", audio_path,
                "-osrt",
                "-of", srt_base + "_orig",
                "-l", self.lang,
                "-t", "8"
            ]
            result1 = subprocess.run(command_transcribe, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            if result1.returncode != 0:
                raise RuntimeError(f"whisper-cli transcribe 失敗\n命令: {command_transcribe}\nstdout: {result1.stdout}\nstderr: {result1.stderr}")
            subs_raw = []
            if os.path.exists(srt_path_orig):
                with open(srt_path_orig, 'r', encoding='utf-8') as f:
                    subs_raw = list(pysrt.from_string(f.read()))
            else:
                raise RuntimeError(f"找不到原文字幕檔案: {srt_path_orig}")
            # Google 翻譯原文
            translated = []
            if subs_raw and self.lang != self.target_lang and self.target_lang != 'none':
                for sub in subs_raw:
                    try:
                        translated.append(GoogleTranslator(source=self.lang, target=self.target_lang).translate(sub.text))
                    except Exception as e:
                        translated.append("")
            # 對齊原文與翻譯
            max_len = max(len(subs_raw), len(translated))
            combined = []
            for i in range(max_len):
                orig = subs_raw[i].text if i < len(subs_raw) else ''
                trans = translated[i] if i < len(translated) else ''
                if i < len(subs_raw):
                    start = subs_raw[i].start.ordinal
                    end = subs_raw[i].end.ordinal
                else:
                    start = 0
                    end = 0
                combined.append((orig, trans, '', start, end))
            self.finished.emit(combined, [], "處理完成！可以播放影片。")
        except Exception as e:
            tb = traceback.format_exc()
            self.error.emit(f"{str(e)}\n{tb}")

class VideoPlayer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("字幕學習播放器 (VLC+PyQt5)")
        self.resize(1200, 900)
        self.vlc_instance = vlc.Instance()
        self.media_player = self.vlc_instance.media_player_new()
        self.videoWidget = QLabel()
        self.videoWidget.setStyleSheet("background: black;")
        self.videoWidget.setMinimumHeight(600)
        self.subtitleWidget = SubtitleWidget()
        self.statusLabel = QLabel("請選擇影片檔案")
        self.statusLabel.setFont(QFont("Arial", 24))
        self.progressSlider = QSlider(Qt.Horizontal)
        self.progressSlider.setRange(0, 100)
        self.playButton = QPushButton("▶")
        self.replayButton = QPushButton("|◀")
        self.rewindButton = QPushButton("◀◀ 5s")
        self.forwardButton = QPushButton("5s ▶▶")
        self.selectButton = QPushButton("選擇影片")
        self.processButton = QPushButton("處理影片")
        self.processButton.setEnabled(False)
        self.langCombo = QComboBox(); self.langCombo.addItems(['auto', 'ja', 'en', 'zh'])
        self.targetLangCombo = QComboBox(); self.targetLangCombo.addItems(['zh-TW', 'en', 'ja', 'ko', 'none'])
        self.targetLangCombo.setCurrentText('zh-TW')
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.update_ui)
        self.vlc_events = self.media_player.event_manager()
        self.vlc_events.event_attach(vlc.EventType.MediaPlayerPlaying, self.on_vlc_playing)
        self.subs = []
        self.translated = []
        self.srt_path = None
        self.video_path = None
        self.duration = 0
        config = load_config()
        # 預設直接使用 v3 版本模型
        self.whisper_path = config.get("whisper_path", "C:/Users/H/Desktop/whisper.cpp_v1/whisper.cpp/whisper-cli.exe")
        self.model_path = "C:/Users/H/Desktop/whisper.cpp_v1/whisper.cpp/models/ggml-large-v3.bin"
        self.volumeSlider = QSlider(Qt.Horizontal)
        self.volumeSlider.setRange(0, 100)
        self.volumeSlider.setValue(70)
        self.volumeSlider.setFixedWidth(120)
        self.setup_ui()
        self.connect_signals()
        self.media_player.audio_set_volume(70)
    def setup_ui(self):
        vbox = QVBoxLayout()
        vbox.addWidget(self.videoWidget)
        vbox.addWidget(self.subtitleWidget)
        vbox.addWidget(self.statusLabel)
        vbox.addWidget(self.progressSlider)
        # 控制列（播放、快退、快進、重播、音量）
        hbox = QHBoxLayout()
        btn_group = QHBoxLayout()
        btn_group.setSpacing(15)  # 調整按鈕間距適中
        self.replayButton.setToolTip("重播到開頭")
        self.rewindButton.setToolTip("倒退5秒")
        self.playButton.setToolTip("播放/暫停")
        self.forwardButton.setToolTip("快轉5秒")
        btn_group.addWidget(self.replayButton)
        btn_group.addWidget(QLabel("重播"))
        btn_group.addWidget(self.rewindButton)
        btn_group.addWidget(QLabel("倒退"))
        btn_group.addWidget(self.playButton)
        btn_group.addWidget(QLabel("播放/暫停"))
        btn_group.addWidget(self.forwardButton)
        btn_group.addWidget(QLabel("快轉"))
        hbox.addLayout(btn_group)
        # 音量文字移到音量條右側
        volume_layout = QHBoxLayout()
        volume_layout.setSpacing(0)
        volume_layout.setContentsMargins(0, 0, 0, 0)
        volume_layout.addWidget(self.volumeSlider)
        volume_label = QLabel("音量")
        volume_label.setContentsMargins(0, 0, 0, 0)
        volume_layout.addWidget(volume_label)
        hbox.addLayout(volume_layout)
        vbox.addLayout(hbox)
        # 影片選擇與處理（移除多餘Label）
        hbox2 = QHBoxLayout()
        self.selectButton.setToolTip("選擇要播放的影片檔案")
        self.processButton.setToolTip("進行語音辨識與字幕生成")
        hbox2.addWidget(self.selectButton)
        hbox2.addWidget(self.processButton)
        # 新增複製字幕按鈕
        self.copyButton = QPushButton("複製字幕")
        self.copyButton.setToolTip("複製當前字幕和翻譯文字到剪貼板")
        hbox2.addWidget(self.copyButton)
        # 辨識與翻譯橫向對齊
        lang_layout = QHBoxLayout()
        lang_label = QLabel("辨識:")
        lang_layout.addWidget(lang_label)
        lang_layout.addWidget(self.langCombo)
        target_label = QLabel("翻譯成:")
        lang_layout.addWidget(target_label)
        lang_layout.addWidget(self.targetLangCombo)
        hbox2.addLayout(lang_layout)
        vbox.addLayout(hbox2)
        self.setLayout(vbox)
    def connect_signals(self):
        self.selectButton.clicked.connect(self.select_video)
        self.processButton.clicked.connect(self.process_video)
        self.playButton.clicked.connect(self.play_pause)
        self.replayButton.clicked.connect(self.replay)
        self.rewindButton.clicked.connect(lambda: self.seek(-5000))
        self.forwardButton.clicked.connect(lambda: self.seek(5000))
        self.progressSlider.sliderReleased.connect(self.on_seek_slider_released)
        self.progressSlider.sliderPressed.connect(self.on_seek_slider_pressed)
        self.timer.timeout.connect(self.update_ui)
        self.volumeSlider.valueChanged.connect(self.on_volume_changed)
        # 連接複製字幕按鈕
        self.copyButton.clicked.connect(self.copy_subtitles)
    def select_video(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "選擇影片", "", "MP4 files (*.mp4)")
        if file_path:
            abs_path = os.path.abspath(file_path)
            print(f"[LOG] 正在播放: {os.path.basename(abs_path)}")
            self.statusLabel.setText(f"已選擇: {os.path.basename(abs_path)}")
            self.video_path = abs_path
            self.media_player.stop()
            self.set_vlc_video_output()
            self.processButton.setEnabled(True)
            self.srt_path = os.path.splitext(abs_path)[0] + "_orig.srt"
            self.progressSlider.setValue(0)
            self.subtitleWidget.setText("")
            self.subs = []
            self.translated = []
            self.playButton.setEnabled(False)
            self.replayButton.setEnabled(False)
            self.rewindButton.setEnabled(False)
            self.forwardButton.setEnabled(False)
            # 清空字幕顯示區域
            self.subtitleWidget.setText("")
            self.statusLabel.setText("")
            # 停止 timer 並重設
            if self.timer.isActive():
                self.timer.stop()
            self.timer = QTimer(self)
            self.timer.setInterval(30)
            self.timer.timeout.connect(self.update_ui)
            # 嘗試自動載入對應字幕檔
            if os.path.exists(self.srt_path):
                import pysrt
                with open(self.srt_path, 'r', encoding='utf-8') as f:
                    subs_raw = list(pysrt.from_string(f.read()))
                print(f"[LOG] 載入字幕: {self.srt_path}")
                print(f"[LOG] 字幕條數: {len(subs_raw)}")
                self.subs = [(sub.text, '', '', sub.start.ordinal, sub.end.ordinal) for sub in subs_raw]
                self.subtitleWidget.set_subtitles(self.subs, [])
            else:
                print(f"[LOG] 找不到字幕檔: {self.srt_path}")
                self.subs = []
                self.subtitleWidget.set_subtitles([], [])
    def set_vlc_video_output(self):
        if sys.platform.startswith('win'):
            self.media_player.set_hwnd(int(self.videoWidget.winId()))
        elif sys.platform.startswith('linux'):
            self.media_player.set_xwindow(int(self.videoWidget.winId()))
        elif sys.platform == 'darwin':
            self.media_player.set_nsobject(int(self.videoWidget.winId()))
    def process_video(self):
        if not self.video_path: 
            return
        self.statusLabel.setText("準備處理影片...")
        QApplication.processEvents()
        config_changed = False
        if not os.path.exists(self.whisper_path):
            self.whisper_path, _ = QFileDialog.getOpenFileName(self, "選擇 whisper.cpp 執行檔", "", "執行檔 (*.exe)")
            config_changed = True
        if not self.model_path or not os.path.exists(self.model_path):
            QMessageBox.critical(self, "Whisper 錯誤", "找不到 Whisper 模型檔，請手動設定！")
            self.statusLabel.setText("Whisper.cpp 執行失敗")
            return
        if config_changed:
            save_config({"whisper_path": self.whisper_path, "model_path": self.model_path})
        lang = self.langCombo.currentText()
        target_lang = self.targetLangCombo.currentText()
        self.statusLabel.setText("影片處理中，請稍候...")
        QApplication.processEvents()
        self.processThread = VideoProcessThread(self.video_path, lang, target_lang, self.whisper_path, self.model_path)
        self.processThread.finished.connect(self.on_process_finished)
        self.processThread.error.connect(self.on_process_error)
        self.processButton.setEnabled(False)
        self.processThread.start()
    def on_process_error(self, err):
        QMessageBox.critical(self, "處理錯誤", f"發生錯誤: {err}")
        self.statusLabel.setText("處理失敗，請重試。")
        self.processButton.setEnabled(True)
        self.selectButton.setEnabled(True)
        
    def on_process_finished(self, subs, translated, msg):
        print(f"[LOG] 處理完成，字幕條數: {len(subs)}")
        self.subs = subs
        self.translated = translated
        self.subtitleWidget.set_subtitles(self.subs, self.translated)
        self.statusLabel.setText(msg)
        self.set_vlc_video_output()
        self.media_player.set_media(self.vlc_instance.media_new(self.video_path))
        self.progressSlider.setValue(0)
        self.playButton.setEnabled(True)
        self.replayButton.setEnabled(True)
        self.rewindButton.setEnabled(True)
        self.forwardButton.setEnabled(True)
        self.processButton.setEnabled(True)
        # 處理完成後 Timer 重新啟動
        if not self.timer.isActive():
            self.timer.start()
    def play_pause(self):
        if self.media_player.is_playing():
            self.media_player.pause()
            self.playButton.setText("▶")
            self.timer.stop()
        else:
            self.media_player.play()
            self.playButton.setText("❚❚")
            self.timer.start()
            self.update_ui()  # 確保字幕立即更新
    def replay(self):
        self.media_player.set_time(0)
        self.media_player.play()
        self.playButton.setText("❚❚")
        self.timer.start()
    def seek(self, delta_ms):
        pos = self.media_player.get_time() + delta_ms
        pos = max(0, min(pos, self.media_player.get_length()))
        self.media_player.set_time(pos)
        self.timer.start()
    def on_seek_slider_pressed(self):
        # 拖曳時暫停timer，避免跳動
        if self.timer.isActive():
            self.timer.stop()
    def on_seek_slider_released(self):
        length = self.media_player.get_length()
        if length > 0:
            pos = int(self.progressSlider.value() / 100 * length)
            self.media_player.set_time(pos)
            self.update_ui()  # 確保字幕立即更新
            self.timer.start()
    def update_ui(self):
        pos = self.media_player.get_time()
        self.subtitleWidget.update_subtitle(pos)
        # 狀態欄只顯示一組原文+翻譯，不重複
        gui_text = ""
        for i, sub in enumerate(self.subs):
            start = sub[3] if len(sub) > 3 else 0
            end = sub[4] if len(sub) > 4 else 0
            if start <= pos <= end:
                orig = sub[0] if len(sub) > 0 else ''
                trans = sub[1] if len(sub) > 1 else ''
                if orig and trans and orig.strip() == trans.strip():
                    gui_text = orig
                elif orig and trans:
                    gui_text = orig + "\n" + trans
                elif orig:
                    gui_text = orig
                elif trans:
                    gui_text = trans
                break
        self.statusLabel.setFont(QFont("Arial", 24))
        self.statusLabel.setText(gui_text if gui_text else "")
        if self.media_player.get_length() > 0:
            self.progressSlider.setValue(int(pos / self.media_player.get_length() * 100))
        if not self.media_player.is_playing():
            self.timer.stop()
        else:
            self.timer.start()  # 確保計時器持續運行
    def get_video_fps(self):
        try:
            with VideoFileClip(self.video_path) as clip:
                return clip.fps
        except Exception:
            return 30
    def on_vlc_playing(self, event):
        if not self.timer.isActive():
            self.timer.start()
            self.update_ui()  # 確保字幕立即更新
    def on_volume_changed(self, value):
        self.media_player.audio_set_volume(value)
    def copy_subtitles(self):
        # 複製當前字幕和翻譯文字到剪貼板
        current_text = self.subtitleWidget.text()
        clipboard = QApplication.clipboard()
        clipboard.setText(current_text)

def save_config(config_data):
    import json
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=4)
def load_config():
    import json
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

if __name__ == "__main__":
    app = QApplication(sys.argv)
    player = VideoPlayer()
    player.show()
    sys.exit(app.exec_()) 
