import sys, os, time
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog, QSlider, QComboBox, QMessageBox, QInputDialog)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont
import pysrt
from deep_translator import GoogleTranslator
from moviepy.editor import VideoFileClip
import vlc
import subprocess

CONFIG_FILE = r"C:/Users/H/Desktop/video/Noto_Sans_JP/config.json"
AUDIO_PATH = "temp_audio.wav"

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
            if sub.start.ordinal <= ms <= sub.end.ordinal:
                text = sub.text
                if self.translated and i < len(self.translated):
                    text += "\n" + self.translated[i]
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
        import subprocess, os
        try:
            if os.path.exists(AUDIO_PATH):
                try: os.remove(AUDIO_PATH)
                except Exception: pass
            with VideoFileClip(self.video_path) as video_clip:
                video_clip.audio.write_audiofile(AUDIO_PATH, logger=None)
            srt_path = os.path.splitext(self.video_path)[0] + ".srt"
            command = [
                self.whisper_path, "-m", self.model_path, "-f", AUDIO_PATH, "-osrt", "-of", os.path.splitext(srt_path)[0],
                "-l", self.lang, "-t", "8"
            ]
            subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            subs_raw = []
            if os.path.exists(srt_path):
                with open(srt_path, 'r', encoding='utf-8') as f:
                    subs_raw = list(pysrt.from_string(f.read()))
            translated = []
            if self.lang != self.target_lang and self.target_lang != 'none':
                for sub in subs_raw:
                    translated.append(GoogleTranslator(source=self.lang, target=self.target_lang).translate(sub.text))
            self.finished.emit(subs_raw, translated, "處理完成！可以播放影片。")
        except Exception as e:
            self.error.emit(str(e))

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
        self.subs = []
        self.translated = []
        self.srt_path = None
        self.video_path = None
        self.duration = 0
        config = load_config()
        self.whisper_path = config.get("whisper_path", "whisper.cpp.exe")
        self.model_path = config.get("model_path", "ggml-base.bin")
        self.setup_ui()
        self.connect_signals()
    def setup_ui(self):
        vbox = QVBoxLayout()
        vbox.addWidget(self.videoWidget)
        vbox.addWidget(self.subtitleWidget)
        vbox.addWidget(self.statusLabel)
        vbox.addWidget(self.progressSlider)
        hbox = QHBoxLayout()
        hbox.addWidget(self.replayButton)
        hbox.addWidget(self.rewindButton)
        hbox.addWidget(self.playButton)
        hbox.addWidget(self.forwardButton)
        vbox.addLayout(hbox)
        hbox2 = QHBoxLayout()
        hbox2.addWidget(self.selectButton)
        hbox2.addWidget(self.processButton)
        hbox2.addWidget(QLabel("辨識:"))
        hbox2.addWidget(self.langCombo)
        hbox2.addWidget(QLabel("翻譯成:"))
        hbox2.addWidget(self.targetLangCombo)
        vbox.addLayout(hbox2)
        self.setLayout(vbox)
    def connect_signals(self):
        self.selectButton.clicked.connect(self.select_video)
        self.processButton.clicked.connect(self.process_video)
        self.playButton.clicked.connect(self.play_pause)
        self.replayButton.clicked.connect(self.replay)
        self.rewindButton.clicked.connect(lambda: self.seek(-5000))
        self.forwardButton.clicked.connect(lambda: self.seek(5000))
        self.progressSlider.sliderReleased.connect(self.slider_seek)
        self.timer.timeout.connect(self.update_ui)
    def select_video(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "選擇影片", "", "MP4 files (*.mp4)")
        if file_path:
            abs_path = os.path.abspath(file_path)
            self.statusLabel.setText(f"已選擇: {os.path.basename(abs_path)}")
            self.video_path = abs_path
            self.media_player.stop()
            self.set_vlc_video_output()
            self.processButton.setEnabled(True)
            self.srt_path = os.path.splitext(abs_path)[0] + ".srt"
            self.progressSlider.setValue(0)
            self.subtitleWidget.setText("")
            self.subs = []
            self.translated = []
            self.playButton.setEnabled(False)
            self.replayButton.setEnabled(False)
            self.rewindButton.setEnabled(False)
            self.forwardButton.setEnabled(False)
    def set_vlc_video_output(self):
        if sys.platform.startswith('win'):
            self.media_player.set_hwnd(int(self.videoWidget.winId()))
        elif sys.platform.startswith('linux'):
            self.media_player.set_xwindow(int(self.videoWidget.winId()))
        elif sys.platform == 'darwin':
            self.media_player.set_nsobject(int(self.videoWidget.winId()))
    def process_video(self):
        if not self.video_path: return
        self.statusLabel.setText("步驟 1/4: 提取音訊...")
        QApplication.processEvents()
        # 讓用戶手動設定 whisper 路徑與模型
        config_changed = False
        if not os.path.exists(self.whisper_path):
            self.whisper_path, _ = QFileDialog.getOpenFileName(self, "選擇 whisper.cpp 執行檔", "", "執行檔 (*.exe)")
            config_changed = True
        if not os.path.exists(self.model_path):
            self.model_path, _ = QFileDialog.getOpenFileName(self, "選擇 Whisper 模型檔", "", "模型 (*.bin)")
            config_changed = True
        if not self.whisper_path or not os.path.exists(self.whisper_path):
            QMessageBox.critical(self, "Whisper 錯誤", "找不到 whisper.cpp 執行檔，請手動設定！")
            self.statusLabel.setText("Whisper.cpp 執行失敗")
            return
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
    def on_process_finished(self, subs, translated, msg):
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
    def on_process_error(self, err):
        QMessageBox.critical(self, "處理錯誤", f"發生錯誤: {err}")
        self.statusLabel.setText("處理失敗，請重試。")
        self.processButton.setEnabled(True)
    def play_pause(self):
        if self.media_player.is_playing():
            self.media_player.pause()
            self.playButton.setText("▶")
            self.timer.stop()
        else:
            self.media_player.play()
            self.playButton.setText("❚❚")
            self.timer.start()
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
    def slider_seek(self):
        if self.media_player.get_length() > 0:
            pos = int(self.progressSlider.value() / 100 * self.media_player.get_length())
            self.media_player.set_time(pos)
            self.timer.start()
    def update_ui(self):
        pos = self.media_player.get_time()
        self.subtitleWidget.update_subtitle(pos)
        if self.media_player.get_length() > 0:
            self.progressSlider.setValue(int(pos / self.media_player.get_length() * 100))
        if not self.media_player.is_playing():
            self.timer.stop()
    def get_video_fps(self):
        try:
            with VideoFileClip(self.video_path) as clip:
                return clip.fps
        except Exception:
            return 30

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
