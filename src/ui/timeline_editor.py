"""CapCut-style multi-track timeline editor for the Timeline Input node.

The widget edits the :class:`~core.timeline.Timeline` owned by the currently
selected :class:`~core.nodes.timeline_input.TimelineInputNode`. Video clips
live on V1..Vn tracks and audio clips on A1..An tracks; drag a clip to move
it in time (horizontally) or to another track of the same kind (vertically).
"""

from __future__ import annotations

import os
from typing import Any

from core.events import ObserverEvent
from core.timeline import ClipKind, Timeline, TimelineClip
from PyQt6.QtCore import QEvent, QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPolygon
from PyQt6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel,
                             QMenu, QPushButton, QScrollArea, QVBoxLayout,
                             QWidget)
from render.audio_decoder import AudioDecoder
from render.media_probe import probe_media_cached
from render.video_decoder import probe_video
from ui.icons import AppIcon, make_icon

_PIXELS_PER_FRAME: float = 3.0
_TRACK_HEIGHT: int = 56
_RULER_HEIGHT: int = 32
_LEFT_GUTTER: int = 104
_TRIM_HIT_WIDTH: float = 12.0

_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
)
_DEFAULT_IMAGE_SECONDS: float = 5.0

# Theme colors (match the editor dark theme).
_BG = QColor("#1e1e1e")
_PANEL = QColor("#252526")
_PANEL_ALT = QColor("#2a2a2c")
_BORDER = QColor("#3e3e42")
_RULER_BG = QColor("#2d2d30")
_GRID = QColor("#3a3a3d")
_TEXT = QColor("#c8c8c8")
_TEXT_DIM = QColor("#8a8a8a")
_VIDEO_COLOR = QColor("#3d6b99")
_VIDEO_COLOR_DARK = QColor("#2c4f70")
_AUDIO_COLOR = QColor("#4f8a5b")
_AUDIO_COLOR_DARK = QColor("#3a6544")
_IMAGE_COLOR = QColor("#8a5ca8")
_IMAGE_COLOR_DARK = QColor("#66427e")
_SELECT_COLOR = QColor("#e8b34b")
# Same playhead blue as the main timeline scrubber (selection accent).
_PLAYHEAD = QColor(0, 150, 255)
_PLAYHEAD_GLOW = QColor(0, 150, 255, 60)
_HANDLE = QColor(235, 235, 235, 190)

_BTN_STYLE = """
QPushButton {
    background-color: #2d2d30;
    color: #cccccc;
    border: 1px solid #3e3e42;
    border-radius: 4px;
    padding: 5px 10px;
}
QPushButton:hover {
    background-color: #3e3e42;
    border-color: #4e4e54;
}
QPushButton:pressed {
    background-color: #245f91;
}
QPushButton:disabled {
    color: #5f5f5f;
    background-color: #252526;
    border-color: #2e2e31;
}
"""


def _is_image_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _IMAGE_EXTENSIONS


def _clip_name(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1] or path


def _is_visual_kind(kind: ClipKind) -> bool:
    return kind in (ClipKind.VIDEO, ClipKind.IMAGE)


class TimelineTrackView(QWidget):
    """Painted multi-track view with click-to-select and drag-to-move."""

    timeline_changed = pyqtSignal()
    command_requested = pyqtSignal(str)
    context_menu_requested = pyqtSignal(object)
    seek_requested = pyqtSignal(int)
    zoom_requested = pyqtSignal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._timeline: Timeline | None = None
        self._current_frame: int = 0
        self._selected_ids: set[str] = set()
        self._snap_enabled = True
        self._pixels_per_frame = _PIXELS_PER_FRAME
        self._hover_edge: str | None = None
        self._hover_clip_id: str | None = None
        # (clip_id, grab_offset_frames, kind, mode, original_start,
        # original_duration, original_source_in, original_source_sec).
        self._drag: tuple[str, int, ClipKind, str, int, int, int, float] | None = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(600, 220)

    # ------------------------------------------------------------------
    def set_timeline(self, timeline: Timeline | None) -> None:
        self._timeline = timeline
        self._selected_ids.clear()
        self._drag = None
        self._resize_to_content()
        self.update()

    def set_current_frame(self, frame: int) -> None:
        frame = max(0, int(frame))
        if frame == self._current_frame:
            return
        self._current_frame = frame
        self.update()

    def selected_clip_id(self) -> str | None:
        return next(iter(self._selected_ids), None)

    def selected_clip_ids(self) -> tuple[str, ...]:
        return tuple(self._selected_ids)

    def selected_clip(self) -> TimelineClip | None:
        if self._timeline is None:
            return None
        clip_id = self.selected_clip_id()
        return self._timeline.clip_by_id(clip_id) if clip_id else None

    def select_clip(self, clip_id: str | None) -> None:
        self._selected_ids = {clip_id} if clip_id else set()
        self.update()

    def set_snap_enabled(self, enabled: bool) -> None:
        self._snap_enabled = bool(enabled)

    def set_zoom(self, zoom: float) -> None:
        self._pixels_per_frame = max(0.75, min(12.0, float(zoom)))
        self._resize_to_content()
        self.update()

    def zoom(self) -> float:
        return self._pixels_per_frame

    def select_all(self) -> None:
        self._selected_ids = {clip.id for clip in (self._timeline.clips if self._timeline else ())}
        self.update()

    def _resize_to_content(self) -> None:
        self.resize(self.sizeHint())
        self.updateGeometry()

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------
    def _visual_tracks(self) -> list[TimelineClip]:
        if self._timeline is None:
            return []
        return [c for c in self._timeline.clips if _is_visual_kind(c.kind)]

    def _audio_tracks(self) -> list[TimelineClip]:
        if self._timeline is None:
            return []
        return [c for c in self._timeline.clips if c.kind == ClipKind.AUDIO]

    def _video_track_count(self) -> int:
        clips = self._visual_tracks()
        return max((c.track for c in clips), default=0) + 1 if clips else 1

    def _audio_track_count(self) -> int:
        clips = self._audio_tracks()
        return max((c.track for c in clips), default=0) + 1 if clips else 1

    def _audio_start_y(self) -> int:
        return _RULER_HEIGHT + self._video_track_count() * _TRACK_HEIGHT

    def _content_height(self) -> int:
        return _RULER_HEIGHT + (
            self._video_track_count() + self._audio_track_count()
        ) * _TRACK_HEIGHT

    def _content_width(self) -> int:
        frames = self._timeline.duration_frames() if self._timeline else 300
        width = _LEFT_GUTTER + int(frames * self._pixels_per_frame) + 160
        viewport = self.parentWidget()
        if viewport is not None and viewport.width() > width:
            width = viewport.width()
        return max(600, width)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._content_width(), max(220, self._content_height()))

    def _clip_rect(self, clip: TimelineClip) -> tuple[float, float, float, float]:
        x = _LEFT_GUTTER + clip.start_frame * self._pixels_per_frame
        w = max(8.0, clip.duration_frames * self._pixels_per_frame)
        if _is_visual_kind(clip.kind):
            y = _RULER_HEIGHT + clip.track * _TRACK_HEIGHT
        else:
            y = self._audio_start_y() + clip.track * _TRACK_HEIGHT
        return x, y, w, float(_TRACK_HEIGHT - 8)

    def _clip_at(self, pos) -> TimelineClip | None:
        if self._timeline is None:
            return None
        for clip in reversed(self._timeline.clips):
            x, y, w, h = self._clip_rect(clip)
            if x <= pos.x() <= x + w and y <= pos.y() <= y + h:
                return clip
        return None

    def _clip_colors(self, kind: ClipKind) -> tuple[QColor, QColor]:
        if kind == ClipKind.AUDIO:
            return _AUDIO_COLOR, _AUDIO_COLOR_DARK
        if kind == ClipKind.IMAGE:
            return _IMAGE_COLOR, _IMAGE_COLOR_DARK
        return _VIDEO_COLOR, _VIDEO_COLOR_DARK

    def _track_label(self, kind: ClipKind, track: int) -> str:
        prefix = "A" if kind == ClipKind.AUDIO else "V"
        return f"{prefix}{track + 1}"

    # ------------------------------------------------------------------
    # Keyboard shortcuts (scoped: only when a timeline is being edited)
    # ------------------------------------------------------------------
    def event(self, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.ShortcutOverride and self._timeline is not None:
            if self._is_shortcut(event.key(), event.modifiers()):
                event.accept()
                return True
        return super().event(event)

    @staticmethod
    def _is_shortcut(key: int, mods: Qt.KeyboardModifier) -> bool:
        ctrl = bool(mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))
        no_mod = not mods
        if no_mod and key in (Qt.Key.Key_S, Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            return True
        if no_mod and key in (Qt.Key.Key_Plus, Qt.Key.Key_Minus):
            return True
        if ctrl and key in (
            Qt.Key.Key_A,
            Qt.Key.Key_D,
            Qt.Key.Key_C,
            Qt.Key.Key_V,
            Qt.Key.Key_X,
        ):
            return True
        return False

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._timeline is None:
            super().keyPressEvent(event)
            return
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))
        if ctrl and key == Qt.Key.Key_A:
            self.command_requested.emit("select_all")
        elif key == Qt.Key.Key_Plus and not mods:
            self.command_requested.emit("zoom_in")
        elif key == Qt.Key.Key_Minus and not mods:
            self.command_requested.emit("zoom_out")
        elif key == Qt.Key.Key_S and not mods:
            self.command_requested.emit("split")
        elif ctrl and key == Qt.Key.Key_D:
            self.command_requested.emit("duplicate")
        elif ctrl and key == Qt.Key.Key_C:
            self.command_requested.emit("copy")
        elif ctrl and key == Qt.Key.Key_V:
            self.command_requested.emit("paste")
        elif ctrl and key == Qt.Key.Key_X:
            self.command_requested.emit("cut")
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and not mods:
            self.command_requested.emit("delete")
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), _BG)

        if self._timeline is None:
            painter.setPen(_TEXT_DIM)
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Select a “Timeline Input” node in the Node Graph to edit its timeline.",
            )
            painter.end()
            return

        width = self._content_width()
        video_count = self._video_track_count()
        audio_count = self._audio_track_count()
        audio_start_y = self._audio_start_y()

        self._paint_ruler(painter, width)
        self._paint_tracks(painter, width, ClipKind.VIDEO, video_count, _RULER_HEIGHT)
        self._paint_tracks(painter, width, ClipKind.AUDIO, audio_count, audio_start_y)
        self._paint_clips(painter)
        self._paint_playhead(painter)
        painter.end()

    def _paint_ruler(self, painter: QPainter, width: int) -> None:
        painter.fillRect(0, 0, width, _RULER_HEIGHT, _RULER_BG)
        painter.setPen(_BORDER)
        painter.drawLine(0, _RULER_HEIGHT - 1, width, _RULER_HEIGHT - 1)

        frames = self._timeline.duration_frames() if self._timeline else 300
        step = max(1, int(round(30 / self._pixels_per_frame)))
        # Some platform styles expose the painter font with only a pixel size
        # and an unset point size (-1). Copying it and changing the point size
        # makes Qt emit a warning, so start from a concrete UI font instead.
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        for f in range(0, frames + step, step):
            x = _LEFT_GUTTER + f * self._pixels_per_frame
            major = f % 30 == 0
            tick_h = _RULER_HEIGHT if major else _RULER_HEIGHT - 10
            painter.setPen(_GRID if not major else _TEXT)
            painter.drawLine(int(x), _RULER_HEIGHT - tick_h, int(x), _RULER_HEIGHT)
            painter.setPen(_TEXT_DIM if not major else _TEXT)
            painter.drawText(int(x) + 4, 11, str(f))

    def _paint_tracks(
        self,
        painter: QPainter,
        width: int,
        kind: ClipKind,
        count: int,
        start_y: int,
    ) -> None:
        for track in range(count):
            y = start_y + track * _TRACK_HEIGHT
            painter.fillRect(0, y, width, _TRACK_HEIGHT, _PANEL if track % 2 == 0 else _PANEL_ALT)
            # Gutter
            painter.fillRect(0, y, _LEFT_GUTTER, _TRACK_HEIGHT, _RULER_BG)
            painter.setPen(_BORDER)
            painter.drawLine(_LEFT_GUTTER, y, _LEFT_GUTTER, y + _TRACK_HEIGHT)
            painter.drawLine(0, y + _TRACK_HEIGHT - 1, width, y + _TRACK_HEIGHT - 1)
            # Kind color chip + label
            chip = _AUDIO_COLOR if kind == ClipKind.AUDIO else _VIDEO_COLOR
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(chip)
            painter.drawRoundedRect(8, y + 17, 4, 14, 2, 2)
            painter.setPen(_TEXT)
            painter.drawText(20, y + _TRACK_HEIGHT // 2 + 4, self._track_label(kind, track))

    def _paint_clips(self, painter: QPainter) -> None:
        for clip in self._timeline.clips:
            x, y, w, h = self._clip_rect(clip)
            selected = clip.id in self._selected_ids
            base, dark = self._clip_colors(clip.kind)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(base)
            painter.drawRoundedRect(int(x), int(y), int(w), int(h), 4, 4)

            # Inner top highlight
            painter.setBrush(dark)
            painter.drawRoundedRect(int(x) + 2, int(y) + 2, int(w) - 4, int(h) - 4, 3, 3)

            # A compact thumbnail/waveform treatment keeps clip type readable even
            # when media thumbnails are unavailable or too expensive to decode here.
            painter.setPen(Qt.PenStyle.NoPen)
            if clip.kind == ClipKind.AUDIO:
                painter.setBrush(QColor(base.red(), base.green(), base.blue(), 110))
                for i in range(max(2, int(w // 8))):
                    bar = 4 + ((i * 17 + len(clip.path) * 3) % 15)
                    painter.drawRect(int(x) + 5 + i * 8, int(y) + int(h / 2) - bar // 2, 3, bar)
            else:
                # Keep visual clips clean at every zoom level. Real thumbnails
                # can be added later without painting distracting placeholder
                # squares over the media surface.
                painter.setBrush(QColor(255, 255, 255, 18))
                painter.drawRect(int(x) + 2, int(y) + 2, max(1, int(w) - 4), 2)

            if selected or (
                clip.id == self._hover_clip_id
                and self._hover_edge in ("start", "end")
            ):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, 24))
                painter.drawRoundedRect(int(x) + 1, int(y) + 4, 8, int(h) - 8, 2, 2)
                painter.drawRoundedRect(int(x + w) - 9, int(y) + 4, 8, int(h) - 8, 2, 2)

            if selected:
                painter.setPen(QPen(_SELECT_COLOR, 2.0))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(
                    int(x) + 1, int(y) + 1, int(w) - 2, int(h) - 2, 4, 4
                )

                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(_HANDLE)
                painter.drawRoundedRect(int(x) + 2, int(y) + 7, 3, int(h) - 14, 1, 1)
                painter.drawRoundedRect(int(x + w) - 5, int(y) + 7, 3, int(h) - 14, 1, 1)

            label = _clip_name(clip.path)
            if clip.kind == ClipKind.IMAGE:
                label = f"[IMG] {label}"
            elif clip.kind == ClipKind.AUDIO and clip.muted:
                label = f"[M] {label}"
            painter.setPen(_TEXT)
            painter.drawText(
                int(x) + 8,
                int(y) + int(h) // 2 + 4,
                label[:30],
            )

    def _paint_playhead(self, painter: QPainter) -> None:
        x = _LEFT_GUTTER + self._current_frame * self._pixels_per_frame
        height = self._content_height()
        # Soft glow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_PLAYHEAD_GLOW)
        painter.drawRect(int(x) - 4, 0, 8, height)
        # Line
        painter.setPen(QPen(_PLAYHEAD, 2.0))
        painter.drawLine(int(x), 0, int(x), height)
        # Triangle cap in the ruler
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_PLAYHEAD)
        painter.drawPolygon(
            QPolygon([
                QPoint(int(x) - 6, 0),
                QPoint(int(x) + 6, 0),
                QPoint(int(x), _RULER_HEIGHT - 8),
            ])
        )

    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._timeline is None:
            return
        pos = event.position()
        if event.button() == Qt.MouseButton.LeftButton and pos.y() <= _RULER_HEIGHT:
            self.seek_requested.emit(self._frame_at_x(pos.x(), event.modifiers()))
            return
        if event.button() == Qt.MouseButton.RightButton:
            clip = self._clip_at(pos)
            self._selected_ids = {clip.id} if clip is not None else set()
            self._drag = None
            self.update()
            self.context_menu_requested.emit(event.globalPosition().toPoint())
            return
        clip = self._clip_at(pos)
        if clip is not None:
            multi = bool(event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))
            if multi:
                if clip.id in self._selected_ids:
                    self._selected_ids.remove(clip.id)
                else:
                    self._selected_ids.add(clip.id)
            else:
                self._selected_ids = {clip.id}
            x, _y, _w, _h = self._clip_rect(clip)
            edge = _TRIM_HIT_WIDTH / self._pixels_per_frame
            mode = "start" if pos.x() <= x + edge else "end" if pos.x() >= x + _w - edge else "move"
            self.seek_requested.emit(self._frame_at_x(pos.x(), event.modifiers()))
            self._drag = (
                clip.id,
                int((pos.x() - x) / self._pixels_per_frame),
                clip.kind,
                mode,
                clip.start_frame,
                clip.duration_frames,
                clip.source_in_frame,
                clip.source_start_sec,
            )
        else:
            self._selected_ids = set()
            self._drag = None
            if event.button() == Qt.MouseButton.LeftButton:
                self.seek_requested.emit(self._frame_at_x(pos.x(), event.modifiers()))
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is None or self._timeline is None:
            self._update_hover(event.position())
            return
        clip_id, grab, kind, mode, original_start, original_duration, original_source_in, original_source_sec = self._drag
        clip = self._timeline.clip_by_id(clip_id)
        if clip is None:
            return
        pos = event.position()
        frame = max(0, int((pos.x() - _LEFT_GUTTER) / self._pixels_per_frame))
        if mode == "start":
            new_frame = self._snap_frame(frame, clip)
            minimum_start = max(0, original_start - max(0, clip.source_in_frame))
            if clip.source_duration_frames <= 0:
                minimum_start = original_start
            new_frame = max(minimum_start, min(new_frame, original_start + original_duration - 1))
            clip.start_frame = new_frame
            clip.duration_frames = original_start + original_duration - new_frame
            clip.source_in_frame = original_source_in + (new_frame - original_start)
            clip.source_start_sec = original_source_sec + (new_frame - original_start) / max(1.0, self._timeline.fps_hint)
            self.timeline_changed.emit()
            self.update()
            return
        if mode == "end":
            new_frame = self._snap_frame(frame, clip)
            maximum_end = original_start + original_duration
            if clip.source_duration_frames > 0:
                maximum_end = original_start + max(
                    1,
                    clip.source_duration_frames - original_source_in,
                )
            new_frame = max(original_start + 1, min(new_frame, maximum_end))
            clip.start_frame = original_start
            clip.duration_frames = new_frame - original_start
            clip.source_in_frame = original_source_in
            clip.source_start_sec = original_source_sec
            self.timeline_changed.emit()
            self.update()
            return
        new_frame = self._snap_frame(max(0, frame - grab), clip)
        if _is_visual_kind(kind):
            audio_y = self._audio_start_y()
            y = audio_y - _TRACK_HEIGHT if pos.y() >= audio_y else max(_RULER_HEIGHT, pos.y())
            new_track = min(
                self._video_track_count() - 1,
                max(0, int((y - _RULER_HEIGHT) / _TRACK_HEIGHT)),
            )
        else:
            audio_y = self._audio_start_y()
            y = max(audio_y, pos.y())
            new_track = min(
                self._audio_track_count() - 1,
                max(0, int((y - audio_y) / _TRACK_HEIGHT)),
            )
        self._timeline.move_clip(clip.id, new_frame, new_track)
        self.update()
        self.timeline_changed.emit()

    def _frame_at_x(self, x: float, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> int:
        frame = max(0, round((x - _LEFT_GUTTER) / self._pixels_per_frame))
        return self._snap_frame(frame, None, modifiers)

    def _snap_frame(self, frame: int, moving: TimelineClip | None,
                    modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> int:
        if not self._snap_enabled or modifiers & Qt.KeyboardModifier.AltModifier:
            return max(0, int(frame))
        candidates = [round(frame / 5) * 5, self._current_frame]
        if self._timeline:
            for clip in self._timeline.clips:
                if moving is not None and clip.id == moving.id:
                    continue
                candidates.extend((clip.start_frame, clip.end_frame))
        nearest = min(candidates, key=lambda value: abs(value - frame))
        return int(nearest) if abs(nearest - frame) <= 4 else max(0, int(frame))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag = None
        self._update_hover(event.position())
        self.update()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        ) or event.position().y() <= _RULER_HEIGHT:
            direction = 1.25 if event.angleDelta().y() > 0 else 0.8
            self.zoom_requested.emit(
                self._pixels_per_frame * direction,
                float(event.position().x()),
            )
            event.accept()
            return
        super().wheelEvent(event)

    def _update_hover(self, pos) -> None:
        clip = self._clip_at(pos)
        edge = None
        if clip is not None:
            x, _y, w, _h = self._clip_rect(clip)
            if abs(pos.x() - x) <= _TRIM_HIT_WIDTH:
                edge = "start"
            elif abs(pos.x() - (x + w)) <= _TRIM_HIT_WIDTH:
                edge = "end"
        self._hover_edge = edge
        self._hover_clip_id = clip.id if edge and clip is not None else None
        self.setCursor(
            Qt.CursorShape.SizeHorCursor if edge else Qt.CursorShape.ArrowCursor
        )


class TimelineEditorWidget(QWidget):
    """Toolbar + track view; edits the selected Timeline Input node."""

    timeline_changed = pyqtSignal()

    _VISUAL_FILTER: str = (
        "Videos & Images (*.mp4 *.mov *.mkv *.avi *.webm *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;"
        "Video (*.mp4 *.mov *.mkv *.avi *.webm);;"
        "Image (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;"
        "All files (*)"
    )
    _VIDEO_FILTER: str = "Video (*.mp4 *.mov *.mkv *.avi *.webm);;All files (*)"

    def __init__(self, project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._node = None
        self._clipboard: list[dict] | None = None
        self._node_picker = QComboBox()
        self._node_picker.setMinimumWidth(150)
        self._node_picker.setToolTip("Choose which Timeline Input node to edit")
        self._node_picker.currentIndexChanged.connect(self._on_node_picked)

        self._view = TimelineTrackView()
        self._view.timeline_changed.connect(self.timeline_changed)
        self._view.command_requested.connect(self._on_command)
        self._view.context_menu_requested.connect(self._show_context_menu)
        self._view.seek_requested.connect(self._seek)
        self._view.zoom_requested.connect(self._zoom_at_cursor)

        self._import_video_btn = self._make_button(
            "Video", AppIcon.MEDIA, self.import_video, "Import a video clip (full length)"
        )
        self._import_overlay_btn = self._make_button(
            "Overlay", AppIcon.MEDIA, self.import_overlay,
            "Import a video or image as an overlay layer"
        )
        self._import_audio_btn = self._make_button(
            "Audio", AppIcon.MEDIA, self.import_audio, "Import an audio clip"
        )
        self._split_btn = self._make_button(
            "Split", AppIcon.SPLIT, self.split_selected, "Split at playhead (S)"
        )
        self._duplicate_btn = self._make_button(
            "Duplicate", AppIcon.DUPLICATE, self.duplicate_selected,
            "Duplicate clip (Ctrl+D)"
        )
        self._delete_btn = self._make_button(
            "Delete", AppIcon.DELETE, self.delete_selected, "Delete clip (Del)"
        )
        self._snap_btn = self._make_button(
            "Snap", None, self._toggle_snap, "Snap to frame grid, clip edges, and playhead (Alt temporarily disables)"
        )
        self._snap_btn.setCheckable(True)
        self._snap_btn.setChecked(True)
        self._zoom_out_btn = self._make_button("-", None, self.zoom_out, "Zoom out timeline")
        self._zoom_reset_btn = self._make_button("100%", None, self.zoom_reset, "Reset timeline zoom")
        self._zoom_in_btn = self._make_button("+", None, self.zoom_in, "Zoom in timeline")
        self._zoom_out_btn.setFixedWidth(28)
        self._zoom_reset_btn.setFixedWidth(52)
        self._zoom_in_btn.setFixedWidth(28)
        self._layer_up_btn = self._make_button(
            "", AppIcon.ALIGN_TOP, lambda: self.nudge_layer(1), "Move clip up one track"
        )
        self._layer_down_btn = self._make_button(
            "", AppIcon.ALIGN_BOTTOM, lambda: self.nudge_layer(-1), "Move clip down one track"
        )
        self._layer_up_btn.setFixedWidth(30)
        self._layer_down_btn.setFixedWidth(30)

        self._buttons = (
            self._import_video_btn,
            self._import_overlay_btn,
            self._import_audio_btn,
            self._split_btn,
            self._duplicate_btn,
            self._delete_btn,
            self._snap_btn,
            self._zoom_out_btn,
            self._zoom_reset_btn,
            self._zoom_in_btn,
            self._layer_up_btn,
            self._layer_down_btn,
        )

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)
        toolbar.addWidget(QLabel("Source"))
        toolbar.addWidget(self._node_picker)
        toolbar.addSpacing(8)
        toolbar.addWidget(self._import_video_btn)
        toolbar.addWidget(self._import_overlay_btn)
        toolbar.addWidget(self._import_audio_btn)
        toolbar.addSpacing(14)
        toolbar.addWidget(self._split_btn)
        toolbar.addWidget(self._duplicate_btn)
        toolbar.addWidget(self._delete_btn)
        toolbar.addWidget(self._snap_btn)
        toolbar.addSpacing(14)
        toolbar.addWidget(QLabel("Zoom"))
        toolbar.addWidget(self._zoom_out_btn)
        toolbar.addWidget(self._zoom_reset_btn)
        toolbar.addWidget(self._zoom_in_btn)
        toolbar.addSpacing(14)
        toolbar.addWidget(self._layer_up_btn)
        toolbar.addWidget(self._layer_down_btn)
        toolbar.addStretch(1)

        self._hint = QLabel("Select a “Timeline Input” node in the Node Graph.")
        self._hint.setStyleSheet("color: #8a8a8a; padding: 2px 0;")

        self._scroll = QScrollArea()
        self._scroll.setWidget(self._view)
        self._scroll.setWidgetResizable(False)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: #1e1e1e; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        layout.addWidget(self._hint)
        layout.addLayout(toolbar)
        layout.addWidget(self._scroll, 1)

        if project is not None:
            project.subscribe(self._on_project_event)
        self._refresh_node_picker()

    def _make_button(
        self,
        text: str,
        icon: AppIcon | None,
        handler,
        tooltip: str | None = None,
    ) -> QPushButton:
        btn = QPushButton(text)
        btn.setStyleSheet(_BTN_STYLE)
        if icon is not None:
            btn.setIcon(make_icon(icon))
        if tooltip:
            btn.setToolTip(tooltip)
        btn.clicked.connect(handler)
        btn.setEnabled(False)
        return btn

    # ------------------------------------------------------------------
    def set_project(self, project) -> None:
        """Retarget the editor at a new document and follow its frame clock."""
        if project is self._project:
            return
        if self._project is not None:
            try:
                self._project.unsubscribe(self._on_project_event)
            except Exception:  # noqa: BLE001
                pass
        self._project = project
        if project is not None:
            project.subscribe(self._on_project_event)
            self._view.set_current_frame(int(getattr(project, "current_frame", 0)))
        self._refresh_node_picker()
        self.set_node(None)

    def shutdown(self) -> None:
        if self._project is not None:
            try:
                self._project.unsubscribe(self._on_project_event)
            except Exception:  # noqa: BLE001
                pass

    def _on_project_event(self, event: ObserverEvent, data: Any) -> None:
        if event == ObserverEvent.FrameChanged:
            self._view.set_current_frame(int(data or 0))

    def _seek(self, frame: int) -> None:
        if self._project is not None:
            self._project.set_frame(int(frame))

    def _toggle_snap(self, checked: bool) -> None:
        self._view.set_snap_enabled(checked)

    def zoom_in(self) -> None:
        self._set_zoom(self._view.zoom() * 1.25)

    def zoom_out(self) -> None:
        self._set_zoom(self._view.zoom() / 1.25)

    def zoom_reset(self) -> None:
        self._set_zoom(_PIXELS_PER_FRAME)

    def _set_zoom(self, pixels_per_frame: float) -> None:
        self._view.set_zoom(pixels_per_frame)
        percent = round(self._view.zoom() / _PIXELS_PER_FRAME * 100)
        self._zoom_reset_btn.setText(f"{percent}%")

    def _zoom_at_cursor(self, pixels_per_frame: float, cursor_x: float) -> None:
        old_zoom = self._view.zoom()
        frame_under_cursor = max(0.0, (cursor_x - _LEFT_GUTTER) / old_zoom)
        viewport_x = cursor_x - self._scroll.horizontalScrollBar().value()
        self._set_zoom(pixels_per_frame)
        target_x = _LEFT_GUTTER + frame_under_cursor * self._view.zoom()
        self._scroll.horizontalScrollBar().setValue(round(target_x - viewport_x))

    def _refresh_node_picker(self) -> None:
        current_id = self._current_node_id()
        self._node_picker.blockSignals(True)
        self._node_picker.clear()
        for node_id, node in (self._project.nodes.items() if self._project is not None else ()):
            if getattr(node, "node_type", "") == "Timeline Input":
                self._node_picker.addItem(node.name, node_id)
        selected = self._node_picker.findData(current_id)
        self._node_picker.setCurrentIndex(selected if selected >= 0 else 0)
        self._node_picker.blockSignals(False)
        self._node_picker.setEnabled(self._node_picker.count() > 0)

    def _current_node_id(self) -> str | None:
        if self._project is None or self._node is None:
            return None
        for node_id, node in self._project.nodes.items():
            if node is self._node:
                return node_id
        return None

    def _on_node_picked(self, index: int) -> None:
        node_id = self._node_picker.itemData(index)
        node = self._project.nodes.get(node_id) if self._project is not None else None
        if node is not None:
            self.set_node(node)

    # ------------------------------------------------------------------
    def set_node(self, node) -> None:
        """Point the editor at a Timeline Input node, or None to disable."""
        from core.nodes.timeline_input import TimelineInputNode

        if node is not None and isinstance(node, TimelineInputNode):
            self._refresh_node_picker()
            self._node = node
            self._view.set_timeline(node.timeline)
            self._view.set_current_frame(
                int(getattr(self._project, "current_frame", 0))
            )
            self._hint.setText(
                "S split · Ctrl+A select all · Ctrl+D duplicate · Ctrl+C/V copy/paste · Del delete · Snap: frame/edge/playhead"
            )
            for btn in self._buttons:
                btn.setEnabled(True)
            selected = self._node_picker.findData(self._current_node_id())
            self._node_picker.blockSignals(True)
            self._node_picker.setCurrentIndex(selected)
            self._node_picker.blockSignals(False)
        else:
            self._node = None
            self._view.set_timeline(None)
            self._hint.setText("Select a “Timeline Input” node in the Node Graph.")
            for btn in self._buttons:
                btn.setEnabled(False)
            self._node_picker.setCurrentIndex(-1)

    # ------------------------------------------------------------------
    def _timeline(self) -> Timeline | None:
        return self._node.timeline if self._node is not None else None

    def _selected_clip(self) -> TimelineClip | None:
        return self._view.selected_clip()

    def _fps(self) -> float:
        return float(getattr(self._project, "fps", 30.0)) or 30.0

    def _playhead(self) -> int:
        return int(getattr(self._project, "current_frame", 0))

    def _emit(self) -> None:
        self._view._resize_to_content()
        self._view.update()
        self.timeline_changed.emit()

    def _on_command(self, cmd: str) -> None:
        if cmd == "split":
            self.split_selected()
        elif cmd == "duplicate":
            self.duplicate_selected()
        elif cmd == "copy":
            self.copy_selected()
        elif cmd == "cut":
            self.cut_selected()
        elif cmd == "paste":
            self.paste_clip()
        elif cmd == "delete":
            self.delete_selected()
        elif cmd == "select_all":
            self._view.select_all()
        elif cmd == "zoom_in":
            self.zoom_in()
        elif cmd == "zoom_out":
            self.zoom_out()

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------
    def import_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import video", "", self._VIDEO_FILTER)
        if path:
            self._add_visual(path, overlay=False)

    def import_overlay(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import overlay", "", self._VISUAL_FILTER)
        if path:
            self._add_visual(path, overlay=True)

    def import_audio(self) -> None:
        timeline = self._timeline()
        if timeline is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import audio", "", "Audio (*.mp3 *.wav *.m4a *.aac *.flac);;All files (*)")
        if not path:
            return
        decoder = AudioDecoder()
        info = decoder.open(path)
        duration_sec = info.duration_sec if info else 0.0
        duration = max(1, int(round(duration_sec * self._fps())))
        decoder.close()
        existing = [c.track for c in timeline.clips if c.kind == ClipKind.AUDIO]
        clip = timeline.add_clip(TimelineClip(
            kind=ClipKind.AUDIO,
            path=path,
            track=(max(existing) + 1) if existing else 0,
            start_frame=timeline.duration_frames(),
            duration_frames=duration,
            source_duration_frames=duration,
        ))
        self._view.select_clip(clip.id)
        self._emit()

    def _add_visual(self, path: str, *, overlay: bool) -> None:
        timeline = self._timeline()
        if timeline is None:
            return
        is_image = _is_image_path(path)
        kind = ClipKind.IMAGE if is_image else ClipKind.VIDEO
        duration = self._probe_frames(path, is_image)
        if overlay:
            track = self._next_visual_track(timeline)
            start = self._playhead()
        else:
            track = 0
            start = timeline.duration_frames()
        clip = timeline.add_clip(TimelineClip(
            kind=kind,
            path=path,
            track=track,
            start_frame=start,
            duration_frames=duration,
            source_duration_frames=duration,
        ))
        self._view.select_clip(clip.id)
        self._emit()

    def _next_visual_track(self, timeline: Timeline) -> int:
        return max(
            (c.track for c in timeline.clips if _is_visual_kind(c.kind)),
            default=-1,
        ) + 1

    def _probe_frames(self, path: str, is_image: bool) -> int:
        """Return the clip's duration in timeline frames, preferring the full source length."""
        if is_image:
            return max(1, int(round(_DEFAULT_IMAGE_SECONDS * self._fps())))
        try:
            info = probe_media_cached(path, require_audio=False)
            if info is not None:
                if getattr(info, "frame_count", 0) > 0:
                    return int(info.frame_count)
                if getattr(info, "duration_sec", 0.0) > 0:
                    return max(1, int(round(info.duration_sec * self._fps())))
        except Exception:  # noqa: BLE001 - probing must never block the import
            pass
        info = probe_video(path)
        if info is not None and getattr(info, "frame_count", 0) > 0:
            return int(info.frame_count)
        return max(1, int(round(_DEFAULT_IMAGE_SECONDS * self._fps())))

    # ------------------------------------------------------------------
    # Clip operations
    # ------------------------------------------------------------------
    def split_selected(self) -> None:
        timeline = self._timeline()
        clip_ids = self._view.selected_clip_ids()
        if timeline is None or not clip_ids:
            return
        split_ids = []
        for clip_id in clip_ids:
            if timeline.split_clip(clip_id, self._playhead()) is not None:
                split_ids.append(clip_id)
        if split_ids:
            self._view.select_clip(split_ids[0])
            self._emit()

    def duplicate_selected(self) -> None:
        timeline = self._timeline()
        clip_ids = self._view.selected_clip_ids()
        if timeline is None or not clip_ids:
            return
        duplicates = []
        for clip_id in clip_ids:
            clip = timeline.clip_by_id(clip_id)
            duplicate = timeline.duplicate_clip(clip_id, offset_frames=0) if clip else None
            if duplicate is not None and clip is not None:
                duplicate.track = clip.track + 1
                duplicates.append(duplicate.id)
        if duplicates:
            self._view.select_clip(duplicates[0])
            self._emit()

    def copy_selected(self) -> None:
        timeline = self._timeline()
        if timeline is None:
            return
        self._clipboard = [clip.to_dict() for clip in timeline.clips if clip.id in self._view.selected_clip_ids()]

    def cut_selected(self) -> None:
        self.copy_selected()
        self.delete_selected()

    def paste_clip(self) -> None:
        timeline = self._timeline()
        if timeline is None or self._clipboard is None:
            return
        pasted = []
        source_start = min((int(data.get("start_frame", 0)) for data in self._clipboard), default=0)
        for raw in self._clipboard:
            data = dict(raw)
            data.pop("id", None)
            clip = TimelineClip.from_dict(data)
            clip.start_frame = self._playhead() + int(data.get("start_frame", 0)) - source_start
            timeline.add_clip(clip)
            pasted.append(clip.id)
        if pasted:
            self._view.select_clip(pasted[0])
            self._emit()

    def delete_selected(self) -> None:
        timeline = self._timeline()
        clip_ids = self._view.selected_clip_ids()
        if timeline is None or not clip_ids:
            return
        removed = any(timeline.remove_clip(clip_id) for clip_id in clip_ids)
        if removed:
            self._view.select_clip(None)
            self._view._resize_to_content()
            self._emit()

    def nudge_layer(self, delta: int) -> None:
        timeline = self._timeline()
        clip_id = self._view.selected_clip_id()
        if timeline is None or clip_id is None:
            return
        clip = timeline.clip_by_id(clip_id)
        if clip is None:
            return
        clip.track = max(0, clip.track + delta)
        self._emit()

    def trim_start_selected(self) -> None:
        """Strip the clip's beginning up to the playhead."""
        timeline = self._timeline()
        clip_id = self._view.selected_clip_id()
        if timeline is None or clip_id is None:
            return
        if timeline.trim_start(clip_id, self._playhead()):
            self._emit()

    def trim_end_selected(self) -> None:
        timeline = self._timeline()
        clip_id = self._view.selected_clip_id()
        if timeline is None or clip_id is None:
            return
        if timeline.trim_end(clip_id, self._playhead()):
            self._emit()

    def extract_audio_selected(self) -> None:
        """Create a standalone audio clip from a video clip's embedded audio."""
        timeline = self._timeline()
        clip = self._selected_clip()
        if timeline is None or clip is None or clip.kind != ClipKind.VIDEO:
            return
        source_fps = self._fps()
        try:
            info = probe_media_cached(clip.path, require_audio=False)
            if info is not None and getattr(info, "fps", 0.0) > 0:
                source_fps = info.fps
        except Exception:  # noqa: BLE001
            pass
        source_start_sec = clip.source_in_frame / max(source_fps, 0.001)
        existing = [c.track for c in timeline.clips if c.kind == ClipKind.AUDIO]
        audio = timeline.add_clip(TimelineClip(
            kind=ClipKind.AUDIO,
            path=clip.path,
            track=(max(existing) + 1) if existing else 0,
            start_frame=clip.start_frame,
            duration_frames=clip.duration_frames,
            source_duration_frames=clip.source_duration_frames or clip.duration_frames,
            source_start_sec=source_start_sec,
        ))
        self._view.select_clip(audio.id)
        self._emit()

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------
    def _show_context_menu(self, global_pos) -> None:
        menu = QMenu(self)
        clip = self._selected_clip()
        if clip is None:
            paste = menu.addAction(make_icon(AppIcon.PASTE), "Paste (Ctrl+V)")
            paste.triggered.connect(self.paste_clip)
            paste.setEnabled(self._clipboard is not None)
            menu.exec(global_pos)
            return

        split = menu.addAction(make_icon(AppIcon.SPLIT), "Split at Playhead (S)")
        split.triggered.connect(self.split_selected)
        trim_start = menu.addAction("Strip Beginning (Trim to Playhead)")
        trim_start.triggered.connect(self.trim_start_selected)
        trim_end = menu.addAction("Trim End to Playhead")
        trim_end.triggered.connect(self.trim_end_selected)
        menu.addSeparator()

        duplicate = menu.addAction(make_icon(AppIcon.DUPLICATE), "Duplicate (Ctrl+D)")
        duplicate.triggered.connect(self.duplicate_selected)
        copy = menu.addAction(make_icon(AppIcon.COPY), "Copy (Ctrl+C)")
        copy.triggered.connect(self.copy_selected)
        paste = menu.addAction(make_icon(AppIcon.PASTE), "Paste (Ctrl+V)")
        paste.triggered.connect(self.paste_clip)
        paste.setEnabled(self._clipboard is not None)
        delete = menu.addAction(make_icon(AppIcon.DELETE), "Delete (Del)")
        delete.triggered.connect(self.delete_selected)
        menu.addSeparator()

        if clip.kind == ClipKind.VIDEO:
            extract = menu.addAction("Extract Audio")
            extract.triggered.connect(self.extract_audio_selected)

        menu.addSeparator()
        layer_up = menu.addAction(make_icon(AppIcon.ALIGN_TOP), "Move Layer Up")
        layer_up.triggered.connect(lambda: self.nudge_layer(1))
        layer_down = menu.addAction(make_icon(AppIcon.ALIGN_BOTTOM), "Move Layer Down")
        layer_down.triggered.connect(lambda: self.nudge_layer(-1))

        menu.exec(global_pos)
