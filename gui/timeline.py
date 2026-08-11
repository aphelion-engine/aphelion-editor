
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from core.project import Project


class TimelineWidget(QWidget):
    frame_changed = pyqtSignal(int)

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        self.is_playing = False

        self.timer = QTimer()
        self.timer.timeout.connect(self.advance_frame)

        self.load_icons()
        self.setup_ui()
        self.project.subscribe(self._on_project_changed)

    def load_icons(self) -> None:
        style = self.style()
        assert style is not None
        self.icon_media_play = style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        self.icon_media_pause = style.standardIcon(QStyle.StandardPixmap.SP_MediaPause)

    def setup_ui(self) -> None:
        layout = QVBoxLayout()

        controls_layout = QHBoxLayout()
        self.play_button = QPushButton()
        self.play_button.setIcon(self.icon_media_play)
        self.play_button.clicked.connect(self.toggle_playback)
        controls_layout.addWidget(self.play_button)

        self.frame_label = QLabel("Frame: 0")
        controls_layout.addWidget(self.frame_label)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(self.project.max_frame)
        self.slider.sliderMoved.connect(self.on_slider_moved)
        self.slider.sliderPressed.connect(self.pause_playback)
        controls_layout.addWidget(self.slider)

        layout.addLayout(controls_layout)
        self.setLayout(layout)

    def _on_project_changed(self, event, data) -> None:
        from core.events import ObserverEvent

        if event == ObserverEvent.FrameChanged:
            self._sync_slider(data)

    def _sync_slider(self, frame_num: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(frame_num)
        self.slider.blockSignals(False)
        self.frame_label.setText(f"Frame: {frame_num}")

    def toggle_playback(self) -> None:
        if self.is_playing:
            self.pause_playback()
        else:
            self.timer.start(max(1, 1000 // self.project.fps))
            self.is_playing = True
            self.play_button.setIcon(self.icon_media_pause)
            self.frame_changed.emit(-1)  # signal: playback started

    def pause_playback(self) -> None:
        self.timer.stop()
        self.is_playing = False
        self.play_button.setIcon(self.icon_media_play)
        self.frame_changed.emit(-2)  # signal: playback stopped

    def advance_frame(self) -> None:
        frame = self.project.current_frame + 1
        if frame > self.project.max_frame:
            frame = 0
        self.set_frame(frame)

    def on_slider_moved(self, value: int) -> None:
        self.set_frame(value)

    def set_frame(self, frame_num: int) -> None:
        self.project.set_frame(frame_num)
        self.frame_changed.emit(frame_num)
