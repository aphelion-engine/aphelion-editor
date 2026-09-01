"""Preview/playback settings resolved from the active Viewer node."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, auto
from typing import TYPE_CHECKING

from config.constants import DEFAULT_PREVIEW_MAX_WIDTH

if TYPE_CHECKING:
    from core.nodes import Node


class ViewportFitMode(IntEnum):
    """How the viewport maps a frame into its widget rectangle."""

    Fit = auto()  # letterbox, preserve aspect, entire frame visible
    Fill = auto()  # cover widget, preserve aspect (may crop)
    Stretch = auto()  # ignore aspect ratio


class ViewerBackground(IntEnum):
    """Letterbox / empty viewport background."""

    Black = auto()
    DarkGray = auto()
    Gray = auto()


_BACKGROUND_HEX: dict[ViewerBackground, str] = {
    ViewerBackground.Black: "#0a0a0a",
    ViewerBackground.DarkGray: "#1a1a1a",
    ViewerBackground.Gray: "#2a2a2a",
}


@dataclass(frozen=True, slots=True)
class PreviewSettings:
    """Resolved playback/preview knobs used by decode + display."""

    max_width: int
    fit_mode: ViewportFitMode
    prefetch_frames: int
    background: ViewerBackground
    exposure_percent: int

    @classmethod
    def defaults(cls) -> PreviewSettings:
        return cls(
            max_width=DEFAULT_PREVIEW_MAX_WIDTH,
            fit_mode=ViewportFitMode.Fit,
            prefetch_frames=6,
            background=ViewerBackground.Black,
            exposure_percent=100,
        )

    @property
    def background_hex(self) -> str:
        return _BACKGROUND_HEX.get(self.background, "#0a0a0a")

    @classmethod
    def from_viewer(cls, node: Node | None) -> PreviewSettings:
        """Read Viewer properties; fall back to defaults when missing."""
        defaults = cls.defaults()
        if node is None or node.node_type != "Viewer":
            return defaults

        max_width = defaults.max_width
        width_prop = node.get_property("preview_max_width")
        if width_prop is not None and width_prop.value is not None:
            max_width = max(160, int(width_prop.value))

        fit_mode = defaults.fit_mode
        fit_prop = node.get_property("fit_mode")
        if fit_prop is not None and isinstance(fit_prop.value, ViewportFitMode):
            fit_mode = fit_prop.value
        elif fit_prop is not None and fit_prop.value is not None:
            try:
                fit_mode = ViewportFitMode[str(fit_prop.value)]
            except KeyError:
                fit_mode = defaults.fit_mode

        prefetch = defaults.prefetch_frames
        prefetch_prop = node.get_property("prefetch_frames")
        if prefetch_prop is not None and prefetch_prop.value is not None:
            prefetch = max(0, min(12, int(prefetch_prop.value)))

        background = defaults.background
        bg_prop = node.get_property("background")
        if bg_prop is not None and isinstance(bg_prop.value, ViewerBackground):
            background = bg_prop.value

        exposure = defaults.exposure_percent
        exposure_prop = node.get_property("exposure")
        if exposure_prop is not None and exposure_prop.value is not None:
            exposure = max(1, int(exposure_prop.value))

        return cls(
            max_width=max_width,
            fit_mode=fit_mode,
            prefetch_frames=prefetch,
            background=background,
            exposure_percent=exposure,
        )
