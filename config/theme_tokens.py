"""Theme token definitions and built-in color presets."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ThemeTokens:
    """Customizable color tokens shared by QSS and the node graph."""

    theme_id: str
    display_name: str
    window_bg: str = "#1e1e1e"
    panel_bg: str = "#1a1a1a"
    surface_bg: str = "#252525"
    surface_elevated: str = "#2a2a2a"
    text_primary: str = "#ffffff"
    text_secondary: str = "#c8c8c8"
    text_muted: str = "#8a8a94"
    border: str = "#333333"
    border_subtle: str = "#121212"
    accent: str = "#2b6ea8"
    accent_hover: str = "#347ebc"
    accent_pressed: str = "#245f91"
    accent_text: str = "#9ecfff"
    menu_bg: str = "#2a2a2a"
    menu_selected: str = "#2b6ea8"
    scrollbar_track: str = "#2a2a2a"
    scrollbar_handle: str = "#555555"
    graph_bg_rgb: tuple[int, int, int] = (24, 24, 26)
    selection_rgb: tuple[int, int, int] = (0, 150, 255)
    socket_input_rgb: tuple[int, int, int] = (80, 160, 255)
    socket_output_rgb: tuple[int, int, int] = (255, 160, 80)
    wire_active_rgb: tuple[int, int, int] = (0, 120, 220)
    node_body_rgb: tuple[int, int, int] = (38, 38, 42)
    node_body_hover_rgb: tuple[int, int, int] = (46, 46, 52)
    node_border_rgb: tuple[int, int, int] = (70, 70, 78)
    node_colors: dict[str, list[int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize tokens for ``.aph.theme`` and preferences JSON."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThemeTokens:
        """Restore tokens from persisted or imported data."""
        rgb_fields = (
            "graph_bg_rgb",
            "selection_rgb",
            "socket_input_rgb",
            "socket_output_rgb",
            "wire_active_rgb",
            "node_body_rgb",
            "node_body_hover_rgb",
            "node_border_rgb",
        )
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key not in cls.__dataclass_fields__:
                continue
            if key in rgb_fields and isinstance(value, list):
                kwargs[key] = tuple(int(v) for v in value[:3])
            elif key == "node_colors" and isinstance(value, dict):
                kwargs[key] = {
                    str(k): [int(c) for c in v[:3]]
                    for k, v in value.items()
                    if isinstance(v, list)
                }
            else:
                kwargs[key] = value
        theme_id = str(kwargs.pop("theme_id", "custom"))
        display_name = str(kwargs.pop("display_name", "Custom"))
        return cls(theme_id=theme_id, display_name=display_name, **kwargs)


def aphelion_dark() -> ThemeTokens:
    """Default Aphelion dark theme."""
    return ThemeTokens(theme_id="aphelion_dark", display_name="Aphelion Dark")


def midnight_blue() -> ThemeTokens:
    """Cool blue variant with deeper backgrounds."""
    return ThemeTokens(
        theme_id="midnight_blue",
        display_name="Midnight Blue",
        window_bg="#141820",
        panel_bg="#161922",
        surface_bg="#1c2230",
        surface_elevated="#222a3a",
        text_primary="#eef2ff",
        text_secondary="#b8c0d8",
        text_muted="#7a849c",
        border="#2a3348",
        border_subtle="#0e121a",
        accent="#3a7bd5",
        accent_hover="#4a8be5",
        accent_pressed="#2f6bbf",
        accent_text="#a8c8ff",
        menu_bg="#1a2030",
        menu_selected="#3a7bd5",
        scrollbar_track="#1a2030",
        scrollbar_handle="#4a5568",
        graph_bg_rgb=(18, 22, 32),
        selection_rgb=(58, 123, 213),
        socket_input_rgb=(96, 168, 255),
        socket_output_rgb=(255, 176, 96),
        wire_active_rgb=(58, 123, 213),
        node_body_rgb=(34, 40, 54),
        node_body_hover_rgb=(42, 50, 66),
        node_border_rgb=(64, 76, 98),
    )


def graphite() -> ThemeTokens:
    """Neutral gray theme with a muted steel accent."""
    return ThemeTokens(
        theme_id="graphite",
        display_name="Graphite",
        window_bg="#181818",
        panel_bg="#1c1c1c",
        surface_bg="#262626",
        surface_elevated="#2c2c2c",
        text_primary="#f2f2f2",
        text_secondary="#c4c4c4",
        text_muted="#888888",
        border="#3a3a3a",
        border_subtle="#101010",
        accent="#6b8cae",
        accent_hover="#7a9abe",
        accent_pressed="#5a7c9e",
        accent_text="#b8cce0",
        menu_bg="#242424",
        menu_selected="#6b8cae",
        scrollbar_track="#242424",
        scrollbar_handle="#5a5a5a",
        graph_bg_rgb=(22, 22, 24),
        selection_rgb=(107, 140, 174),
        socket_input_rgb=(120, 160, 200),
        socket_output_rgb=(210, 170, 120),
        wire_active_rgb=(107, 140, 174),
        node_body_rgb=(40, 40, 44),
        node_body_hover_rgb=(48, 48, 54),
        node_border_rgb=(78, 78, 86),
    )


def warm_studio() -> ThemeTokens:
    """Warm editorial palette inspired by grading suites."""
    return ThemeTokens(
        theme_id="warm_studio",
        display_name="Warm Studio",
        window_bg="#1c1816",
        panel_bg="#201c18",
        surface_bg="#2a2420",
        surface_elevated="#322c28",
        text_primary="#f6f0ea",
        text_secondary="#d8cdc0",
        text_muted="#9a8e82",
        border="#3a342e",
        border_subtle="#120f0d",
        accent="#c4844a",
        accent_hover="#d4945a",
        accent_pressed="#a8743a",
        accent_text="#f0c898",
        menu_bg="#2a2420",
        menu_selected="#c4844a",
        scrollbar_track="#2a2420",
        scrollbar_handle="#6a5a4a",
        graph_bg_rgb=(28, 24, 20),
        selection_rgb=(196, 132, 74),
        socket_input_rgb=(120, 170, 220),
        socket_output_rgb=(240, 170, 90),
        wire_active_rgb=(196, 132, 74),
        node_body_rgb=(44, 38, 34),
        node_body_hover_rgb=(52, 46, 40),
        node_border_rgb=(88, 76, 66),
    )


BUILTIN_THEMES: dict[str, ThemeTokens] = {
    "aphelion_dark": aphelion_dark(),
    "midnight_blue": midnight_blue(),
    "graphite": graphite(),
    "warm_studio": warm_studio(),
}


def builtin_theme(theme_id: str) -> ThemeTokens | None:
    """Return a copy of a built-in preset when ``theme_id`` is known."""
    preset = BUILTIN_THEMES.get(theme_id)
    if preset is None:
        return None
    return ThemeTokens.from_dict(preset.to_dict())
