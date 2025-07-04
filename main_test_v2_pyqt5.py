import sys, os, time
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog, QSlider, QComboBox)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtCore import Qt, QUrl, QTimer
from PyQt5.QtGui import QFont, QPainter, QColor
import pysrt
from deep_translator import GoogleTranslator
from moviepy.editor import VideoFileClip

CONFIG_FILE = "config.json"
AUDIO_PATH = "temp_audio.wav"

class SubtitleWidget(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: rgba(0,0,0,0);")
        self.setAlignment(Qt.AlignBottom | Qt.AlignLeft)
        self.setFont(QFont("Arial", 24))
        self.subs = []
        self.translated = []
        self.current_text = ""
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

class VideoPlayer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("字幕學習播放器 (PyQt5)")
        self.resize(950, 900)
        self.mediaPlayer = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        self.videoWidget = QVideoWidget()
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
        self.mediaPlayer.setVideoOutput(self.videoWidget)
    def connect_signals(self):
        self.selectButton.clicked.connect(self.select_video)
        self.processButton.clicked.connect(self.process_video)
        self.playButton.clicked.connect(self.play_pause)
        self.replayButton.clicked.connect(self.replay)
        self.rewindButton.clicked.connect(lambda: self.seek(-5000))
        self.forwardButton.clicked.connect(lambda: self.seek(5000))
        self.progressSlider.sliderReleased.connect(self.slider_seek)
        self.mediaPlayer.positionChanged.connect(self.on_position_changed)
        self.mediaPlayer.durationChanged.connect(self.on_duration_changed)
    def select_video(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "選擇影片", "", "MP4 files (*.mp4)")
        if file_path:
            self.statusLabel.setText(f"已選擇: {os.path.basename(file_path)}")
            self.video_path = file_path
            self.mediaPlayer.stop()
            self.mediaPlayer.setVideoOutput(self.videoWidget)
            self.mediaPlayer.setMedia(QMediaContent(QUrl.fromLocalFile(file_path)))
            self.processButton.setEnabled(True)
            self.srt_path = os.path.splitext(file_path)[0] + "_combined.srt"
            self.progressSlider.setValue(0)
            self.subtitleWidget.setText("")
            self.subs = []
            self.translated = []
            if os.path.exists(AUDIO_PATH):
                try:
                    os.remove(AUDIO_PATH)
                except Exception: pass
    def process_video(self):
        if not self.video_path: return
        self.statusLabel.setText("步驟 1/3: 提取音訊...")
        QApplication.processEvents()
        with VideoFileClip(self.video_path) as video_clip:
            video_clip.audio.write_audiofile(AUDIO_PATH, logger=None)
        self.statusLabel.setText("步驟 2/3: 載入字幕...")
        QApplication.processEvents()
        if os.path.exists(self.srt_path):
            with open(self.srt_path, 'r', encoding='utf-8') as f:
                self.subs = list(pysrt.from_string(f.read()))
            self.translated = []
            if self.langCombo.currentText() != self.targetLangCombo.currentText() and self.targetLangCombo.currentText() != 'none':
                for sub in self.subs:
                    translated = GoogleTranslator(source=self.langCombo.currentText(), target=self.targetLangCombo.currentText()).translate(sub.text)
                    self.translated.append(translated)
        self.subtitleWidget.set_subtitles(self.subs, self.translated)
        self.statusLabel.setText("步驟 3/3: 準備播放器...")
        QApplication.processEvents()
        self.mediaPlayer.setVideoOutput(self.videoWidget)
        self.mediaPlayer.setMedia(QMediaContent(QUrl.fromLocalFile(self.video_path)))
        self.mediaPlayer.play()
        self.mediaPlayer.pause()
        self.duration = self.mediaPlayer.duration()
        self.progressSlider.setValue(0)
        self.playButton.setEnabled(True)
        self.timer.start()
        self.statusLabel.setText("處理完成！可以播放影片。")
    def play_pause(self):
        if self.mediaPlayer.state() == QMediaPlayer.PlayingState:
            self.mediaPlayer.pause()
            self.playButton.setText("▶")
        else:
            self.mediaPlayer.play()
            self.playButton.setText("❚❚")
            self.timer.start()
    def replay(self):
        self.mediaPlayer.setPosition(0)
        self.mediaPlayer.play()
        self.playButton.setText("❚❚")
        self.timer.start()
    def seek(self, delta_ms):
        pos = self.mediaPlayer.position() + delta_ms
        pos = max(0, min(pos, self.mediaPlayer.duration()))
        self.mediaPlayer.setPosition(pos)
        self.timer.start()
    def slider_seek(self):
        if self.duration > 0:
            pos = int(self.progressSlider.value() / 100 * self.duration)
            self.mediaPlayer.setPosition(pos)
            self.timer.start()
    def on_position_changed(self, pos):
        if self.duration > 0:
            self.progressSlider.setValue(int(pos / self.duration * 100))
    def on_duration_changed(self, duration):
        self.duration = duration
    def update_ui(self):
        pos = self.mediaPlayer.position()
        self.subtitleWidget.update_subtitle(pos)
        # 動態根據FPS調整timer
        fps = self.get_video_fps()
        if fps > 0:
            self.timer.setInterval(int(1000 / fps))
        if self.mediaPlayer.state() != QMediaPlayer.PlayingState:
            self.timer.stop()
    def get_video_fps(self):
        # 用 moviepy 取得FPS
        try:
            with VideoFileClip(self.video_path) as clip:
                return clip.fps
        except Exception:
            return 30

if __name__ == "__main__":
    app = QApplication(sys.argv)
    player = VideoPlayer()
    player.show()
    sys.exit(app.exec_()) 
