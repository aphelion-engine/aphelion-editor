"""Timeline transport UI backed by ``timeline.controller``."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config.theme import TIMELINE_STYLE
from core.events import ObserverEvent
from core.project import Project
from timeline.controller import (
    DEFAULT_PLAYBACK_SPEED,
    PLAYBACK_SPEEDS,
    PlaybackController,
)
from ui.icons import (
    ACTIVE_ICON_COLOR,
    AppIcon,
    DEFAULT_ICON_COLOR,
    LOOP_ACTIVE_COLOR,
    icon_size,
    make_icon,
)
from ui.timeline.scrubber import TimelineScrubber


class TimelineWidget(QWidget):
    """Timeline panel: transport controls, interactive scrubber, work range."""

    frame_changed = pyqtSignal(int)
    playback_changed = pyqtSignal(bool)

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.setObjectName("TimelineWidget")
        self.setStyleSheet(TIMELINE_STYLE)

        self.project = project
        self.controller = PlaybackController(project.max_frame)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._advance_frame)

        self._build_ui()
        self._sync_from_project()
        self.project.subscribe(self._on_project_changed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    @property
    def is_playing(self) -> bool:
        return self.controller.is_playing

    @property
    def is_looping(self) -> bool:
        return self.controller.is_looping

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)
        root.addWidget(self._build_toolbar())
        self.scrubber = TimelineScrubber(self)
        self.scrubber.set_range(self.project.max_frame)
        self.scrubber.set_in_point(self.controller.in_point)
        self.scrubber.set_out_point(self.controller.out_point)
        self.scrubber.frame_scrubbed.connect(self._on_scrubbed)
        self.scrubber.in_point_changed.connect(self._on_in_changed)
        self.scrubber.out_point_changed.connect(self._on_out_changed)
        root.addWidget(self.scrubber)

    def _build_toolbar(self) -> QFrame:
        bar = QFrame(self)
        bar.setObjectName("TimelineToolbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(6)

        self.timecode_label = QLabel("00:00:00:00")
        self.timecode_label.setObjectName("TimelineTimecodeLabel")
        self.timecode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.timecode_label)

        self.frame_label = QLabel("Frame 0")
        self.frame_label.setObjectName("TimelineFrameLabel")
        layout.addWidget(self.frame_label)

        layout.addSpacing(8)
        self._add_transport_buttons(layout)
        layout.addSpacing(8)
        self._add_range_buttons(layout)
        layout.addStretch(1)
        self._add_options(layout)
        return bar

    def _add_transport_buttons(self, layout: QHBoxLayout) -> None:
        self.btn_start = self._icon_button(AppIcon.TO_START, "Go to start (Home)")
        self.btn_prev = self._icon_button(AppIcon.STEP_BACK, "Previous frame (Left)")
        self.btn_play = self._icon_button(
            AppIcon.PLAY, "Play / Pause (Space)", play=True
        )
        self.btn_next = self._icon_button(AppIcon.STEP_FORWARD, "Next frame (Right)")
        self.btn_end = self._icon_button(AppIcon.TO_END, "Go to end (End)")

        self.btn_start.clicked.connect(self.go_to_start)
        self.btn_prev.clicked.connect(self.step_backward)
        self.btn_play.clicked.connect(self.toggle_playback)
        self.btn_next.clicked.connect(self.step_forward)
        self.btn_end.clicked.connect(self.go_to_end)

        for button in (
            self.btn_start,
            self.btn_prev,
            self.btn_play,
            self.btn_next,
            self.btn_end,
        ):
            layout.addWidget(button)

    def _add_range_buttons(self, layout: QHBoxLayout) -> None:
        self.btn_set_in = self._icon_button(AppIcon.MARK_IN, "Set in point (I)")
        self.btn_set_out = self._icon_button(AppIcon.MARK_OUT, "Set out point (O)")
        self.btn_go_in = self._icon_button(AppIcon.GO_IN, "Jump to in point")
        self.btn_go_out = self._icon_button(AppIcon.GO_OUT, "Jump to out point")
        self.btn_clear_range = self._icon_button(
            AppIcon.CLEAR_RANGE, "Clear in/out range"
        )

        self.btn_set_in.clicked.connect(self.set_in_at_playhead)
        self.btn_set_out.clicked.connect(self.set_out_at_playhead)
        self.btn_go_in.clicked.connect(self.go_to_in)
        self.btn_go_out.clicked.connect(self.go_to_out)
        self.btn_clear_range.clicked.connect(self.clear_range)

        for button in (
            self.btn_set_in,
            self.btn_set_out,
            self.btn_go_in,
            self.btn_go_out,
            self.btn_clear_range,
        ):
            layout.addWidget(button)

    def _add_options(self, layout: QHBoxLayout) -> None:
        self.btn_loop = self._icon_button(
            AppIcon.LOOP, "Loop within in/out range", toggle=True
        )
        self.btn_loop.setChecked(True)
        self.btn_loop.setIcon(make_icon(AppIcon.LOOP, color=LOOP_ACTIVE_COLOR))
        self.btn_loop.toggled.connect(self._on_loop_toggled)
        layout.addWidget(self.btn_loop)

        self.speed_combo = QComboBox()
        self.speed_combo.setObjectName("TimelineSpeedCombo")
        self.speed_combo.setToolTip("Playback speed")
        for speed in PLAYBACK_SPEEDS:
            self.speed_combo.addItem(f"{speed:g}x", speed)
        self.speed_combo.setCurrentIndex(PLAYBACK_SPEEDS.index(DEFAULT_PLAYBACK_SPEED))
        self.speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        layout.addWidget(self.speed_combo)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("TimelineMetaLabel")
        self.meta_label.setSizePolicy(
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Preferred,
        )
        layout.addWidget(self.meta_label)

    def _icon_button(
        self,
        icon: AppIcon,
        tooltip: str,
        *,
        play: bool = False,
        toggle: bool = False,
    ) -> QPushButton:
        button = QPushButton()
        if play:
            button.setObjectName("TimelinePlayButton")
            button.setProperty("playing", "false")
        elif toggle:
            button.setObjectName("TimelineToggleButton")
            button.setCheckable(True)
        else:
            button.setObjectName("TimelineTransportButton")
        button.setIcon(make_icon(icon))
        button.setIconSize(icon_size())
        button.setToolTip(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return button

    def _on_project_changed(self, event: ObserverEvent, data: Any) -> None:
        if event == ObserverEvent.FrameChanged and isinstance(data, int):
            self._sync_frame_ui(data)
        elif event == ObserverEvent.ProjectModified:
            # Media load / project settings may change fps and duration.
            was_playing = self.controller.is_playing
            self._sync_from_project()
            if was_playing:
                self.start_playback()

    def _sync_from_project(self) -> None:
        self.controller.set_max_frame(self.project.max_frame)
        self.scrubber.set_range(self.project.max_frame)
        self.scrubber.set_in_point(self.controller.in_point)
        self.scrubber.set_out_point(self.controller.out_point)
        self._sync_frame_ui(self.project.current_frame)
        self._update_meta()

    def _sync_frame_ui(self, frame_num: int) -> None:
        self.scrubber.set_frame(frame_num)
        self.frame_label.setText(f"Frame {frame_num}")
        self.timecode_label.setText(
            self.controller.format_timecode(frame_num, self.project.fps)
        )

    def _update_meta(self) -> None:
        self.meta_label.setText(
            f"{self.project.fps:g} fps  ·  {self.project.max_frame} frames  ·  "
            f"In {self.controller.in_point}  Out {self.controller.out_point}"
        )

    def toggle_playback(self) -> None:
        if self.controller.is_playing:
            self.pause_playback()
        else:
            self.start_playback()

    def start_playback(self) -> None:
        self.timer.start(self.controller.timer_interval_ms(self.project.fps))
        self.controller.is_playing = True
        self._set_play_button_state(playing=True)
        self.playback_changed.emit(True)
        self.frame_changed.emit(-1)

    def pause_playback(self) -> None:
        self.timer.stop()
        self.controller.is_playing = False
        self._set_play_button_state(playing=False)
        self.playback_changed.emit(False)
        self.frame_changed.emit(-2)

    def _set_play_button_state(self, *, playing: bool) -> None:
        if playing:
            self.btn_play.setIcon(make_icon(AppIcon.PAUSE, color=ACTIVE_ICON_COLOR))
        else:
            self.btn_play.setIcon(make_icon(AppIcon.PLAY, color=DEFAULT_ICON_COLOR))
        self.btn_play.setProperty("playing", "true" if playing else "false")
        style = self.btn_play.style()
        if style is not None:
            style.unpolish(self.btn_play)
            style.polish(self.btn_play)

    def _advance_frame(self) -> None:
        nxt = self.controller.next_frame(self.project.current_frame)
        if nxt is None:
            self.pause_playback()
            return
        self.set_frame(nxt)

    def set_frame(self, frame_num: int) -> None:
        self.project.set_frame(frame_num)
        self.frame_changed.emit(frame_num)

    def go_to_start(self) -> None:
        self.set_frame(0)

    def go_to_end(self) -> None:
        self.set_frame(self.project.max_frame)

    def step_forward(self) -> None:
        self.pause_playback()
        self.set_frame(self.project.current_frame + 1)

    def step_backward(self) -> None:
        self.pause_playback()
        self.set_frame(self.project.current_frame - 1)

    def go_to_in(self) -> None:
        self.set_frame(self.controller.in_point)

    def go_to_out(self) -> None:
        self.set_frame(self.controller.out_point)

    def set_in_at_playhead(self) -> None:
        self._on_in_changed(self.project.current_frame)

    def set_out_at_playhead(self) -> None:
        self._on_out_changed(self.project.current_frame)

    def clear_range(self) -> None:
        self.controller.clear_range()
        self.scrubber.set_in_point(self.controller.in_point)
        self.scrubber.set_out_point(self.controller.out_point)
        self._update_meta()

    def _on_scrubbed(self, frame: int) -> None:
        self.pause_playback()
        self.set_frame(frame)

    def _on_in_changed(self, frame: int) -> None:
        self.controller.set_in_point(frame)
        self.scrubber.set_in_point(self.controller.in_point)
        self._update_meta()

    def _on_out_changed(self, frame: int) -> None:
        self.controller.set_out_point(frame)
        self.scrubber.set_out_point(self.controller.out_point)
        self._update_meta()

    def _on_loop_toggled(self, checked: bool) -> None:
        self.controller.is_looping = checked
        color = LOOP_ACTIVE_COLOR if checked else DEFAULT_ICON_COLOR
        self.btn_loop.setIcon(make_icon(AppIcon.LOOP, color=color))

    def _on_speed_changed(self, _index: int) -> None:
        speed = self.speed_combo.currentData()
        if not isinstance(speed, float):
            return
        self.controller.playback_speed = speed
        if self.controller.is_playing:
            self.start_playback()

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        if event is None:
            return
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.toggle_playback()
        elif key == Qt.Key.Key_Left:
            self.step_backward()
        elif key == Qt.Key.Key_Right:
            self.step_forward()
        elif key == Qt.Key.Key_Home:
            self.go_to_start()
        elif key == Qt.Key.Key_End:
            self.go_to_end()
        elif key == Qt.Key.Key_I:
            self.set_in_at_playhead()
        elif key == Qt.Key.Key_O:
            self.set_out_at_playhead()
        else:
            super().keyPressEvent(event)
            return
        event.accept()
