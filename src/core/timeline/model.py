"""Multi-track timeline data model powering the Timeline Input node."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import IntEnum, auto


class ClipKind(IntEnum):
    """What a clip contributes to the timeline composition."""

    VIDEO = auto()
    AUDIO = auto()
    IMAGE = auto()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class TimelineClip:
    """One item on the timeline.

    Video clips render pixels (and, optionally, their own audio). Audio clips
    render audio only. ``track`` is the layer: higher tracks draw on top of
    lower ones. Positions are expressed in *timeline frames* at the project
    frame rate; ``source_in_frame`` is the source video frame the clip starts
    at, while ``source_start_sec`` is the source audio offset in seconds.
    """

    kind: ClipKind
    path: str = ""
    track: int = 0
    start_frame: int = 0
    duration_frames: int = 0
    source_in_frame: int = 0
    source_start_sec: float = 0.0
    volume: float = 1.0
    muted: bool = False
    opacity: float = 1.0
    play_audio: bool = True
    # Total source length. A zero value means the source length is unknown,
    # so trimming remains limited to the current segment for legacy clips.
    source_duration_frames: int = 0
    id: str = field(default_factory=_new_id)

    @property
    def end_frame(self) -> int:
        return self.start_frame + max(0, int(self.duration_frames))

    def contains_frame(self, frame: int) -> bool:
        return self.start_frame <= int(frame) < self.end_frame

    def source_frame_at(self, frame: int) -> int:
        return self.source_in_frame + (int(frame) - self.start_frame)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": int(self.kind),
            "path": self.path,
            "track": int(self.track),
            "start_frame": int(self.start_frame),
            "duration_frames": int(self.duration_frames),
            "source_in_frame": int(self.source_in_frame),
            "source_duration_frames": int(self.source_duration_frames),
            "source_start_sec": float(self.source_start_sec),
            "volume": float(self.volume),
            "muted": bool(self.muted),
            "opacity": float(self.opacity),
            "play_audio": bool(self.play_audio),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TimelineClip":
        return cls(
            kind=ClipKind(int(data.get("kind", ClipKind.VIDEO))),
            path=str(data.get("path", "")),
            track=int(data.get("track", 0)),
            start_frame=int(data.get("start_frame", 0)),
            duration_frames=int(data.get("duration_frames", 0)),
            source_in_frame=int(data.get("source_in_frame", 0)),
            source_duration_frames=int(data.get("source_duration_frames", 0)),
            source_start_sec=float(data.get("source_start_sec", 0.0)),
            volume=float(data.get("volume", 1.0)),
            muted=bool(data.get("muted", False)),
            opacity=float(data.get("opacity", 1.0)),
            play_audio=bool(data.get("play_audio", True)),
            id=str(data.get("id", "") or _new_id()),
        )


class Timeline:
    """Ordered, serializable collection of clips."""

    #: Frame-rate hint used only to convert a frame split into a seconds
    #: offset for audio clips; the compositor overrides it per evaluation.
    fps_hint: float = 30.0

    def __init__(self) -> None:
        self._clips: list[TimelineClip] = []

    @property
    def clips(self) -> tuple[TimelineClip, ...]:
        return tuple(self._clips)

    def __len__(self) -> int:
        return len(self._clips)

    def clip_by_id(self, clip_id: str) -> TimelineClip | None:
        for clip in self._clips:
            if clip.id == clip_id:
                return clip
        return None

    def add_clip(self, clip: TimelineClip) -> TimelineClip:
        self._clips.append(clip)
        return clip

    def remove_clip(self, clip_id: str) -> bool:
        clip = self.clip_by_id(clip_id)
        if clip is None:
            return False
        self._clips.remove(clip)
        return True

    def duplicate_clip(self, clip_id: str, *, offset_frames: int = 0) -> TimelineClip | None:
        clip = self.clip_by_id(clip_id)
        if clip is None:
            return None
        copy = TimelineClip.from_dict(clip.to_dict())
        copy.id = _new_id()
        copy.start_frame = max(0, clip.start_frame + int(offset_frames))
        self._clips.append(copy)
        return copy

    def split_clip(self, clip_id: str, at_frame: int) -> tuple[TimelineClip, TimelineClip] | None:
        """Split ``clip_id`` at a timeline frame into two adjacent clips.

        Returns the (left, right) clips, or None when the split point is not
        strictly inside the clip. The left clip keeps the original id.
        """
        clip = self.clip_by_id(clip_id)
        if clip is None:
            return None
        point = int(at_frame)
        if point <= clip.start_frame or point >= clip.end_frame:
            return None
        left_duration = point - clip.start_frame
        right = TimelineClip.from_dict(clip.to_dict())
        right.id = _new_id()
        right.start_frame = point
        right.duration_frames = clip.duration_frames - left_duration
        right.source_in_frame = clip.source_in_frame + left_duration
        right.source_start_sec = clip.source_start_sec + left_duration / max(1.0, self.fps_hint)
        clip.duration_frames = left_duration
        self._clips.append(right)
        return clip, right

    def move_clip(self, clip_id: str, new_start_frame: int, new_track: int) -> bool:
        clip = self.clip_by_id(clip_id)
        if clip is None:
            return False
        clip.start_frame = max(0, int(new_start_frame))
        clip.track = max(0, int(new_track))
        return True

    def trim_start(self, clip_id: str, at_frame: int) -> bool:
        """Strip everything before ``at_frame``, keeping the clip's tail.

        The clip keeps its id; ``source_in_frame``/``source_start_sec`` advance
        so the remaining material stays in sync with its source.
        """
        clip = self.clip_by_id(clip_id)
        if clip is None:
            return False
        point = int(at_frame)
        minimum_start = clip.start_frame
        if clip.source_duration_frames > 0:
            minimum_start = max(0, clip.start_frame - clip.source_in_frame)
        if point < minimum_start or point >= clip.end_frame or point == clip.start_frame:
            return False
        removed = point - clip.start_frame
        clip.source_in_frame += removed
        clip.source_start_sec += removed / max(1.0, self.fps_hint)
        clip.start_frame = point
        clip.duration_frames -= removed
        return True

    def trim_end(self, clip_id: str, at_frame: int) -> bool:
        """Strip everything after ``at_frame``, keeping the clip's head."""
        clip = self.clip_by_id(clip_id)
        if clip is None:
            return False
        point = int(at_frame)
        maximum_end = clip.end_frame
        if clip.source_duration_frames > 0:
            maximum_end = clip.start_frame + max(
                1,
                clip.source_duration_frames - clip.source_in_frame,
            )
        if point <= clip.start_frame or point > maximum_end or point == clip.end_frame:
            return False
        clip.duration_frames = point - clip.start_frame
        return True

    def set_clip_property(self, clip_id: str, key: str, value: object) -> bool:
        clip = self.clip_by_id(clip_id)
        if clip is None or not hasattr(clip, key):
            return False
        setattr(clip, key, value)
        return True

    def duration_frames(self) -> int:
        return max((clip.end_frame for clip in self._clips), default=0)

    def video_clips_at(self, frame: int) -> list[TimelineClip]:
        """Active pixel clips at a frame (video + image), lowest track first."""
        clips = [
            c
            for c in self._clips
            if c.kind in (ClipKind.VIDEO, ClipKind.IMAGE) and c.contains_frame(frame)
        ]
        return sorted(clips, key=lambda c: c.track)

    def audio_clips_at(self, frame: int) -> list[TimelineClip]:
        """Clips contributing audio at a frame (video clips with their audio
        enabled, plus standalone audio clips)."""
        active: list[TimelineClip] = []
        for clip in self._clips:
            if not clip.contains_frame(frame) or clip.muted:
                continue
            if clip.kind == ClipKind.AUDIO:
                active.append(clip)
            elif clip.kind == ClipKind.VIDEO and clip.play_audio:
                active.append(clip)
        return active

    def to_dict(self) -> dict:
        return {"clips": [clip.to_dict() for clip in self._clips]}

    @classmethod
    def from_dict(cls, data: dict | None) -> "Timeline":
        timeline = cls()
        if not isinstance(data, dict):
            return timeline
        raw_clips = data.get("clips", [])
        if isinstance(raw_clips, list):
            for raw in raw_clips:
                if isinstance(raw, dict):
                    timeline.add_clip(TimelineClip.from_dict(raw))
        return timeline
