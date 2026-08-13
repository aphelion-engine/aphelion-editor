"""Runtime graph color palette driven by theme preferences."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QColor

from config.theme_tokens import ThemeTokens, aphelion_dark


@dataclass
class GraphThemePalette:
    """Live graph colors consumed by the node graph canvas."""

    graph_bg: QColor
    grid_major: QColor
    grid_minor: QColor
    vignette: QColor
    node_body: QColor
    node_body_hover: QColor
    node_border: QColor
    node_border_hover: QColor
    selection: QColor
    selection_soft: QColor
    text_primary: QColor
    text_secondary: QColor
    socket_input: QColor
    socket_output: QColor
    socket_ring: QColor
    marquee: QColor
    marquee_border: QColor
    wire: QColor
    wire_active: QColor
    wire_preview: QColor

    @classmethod
    def from_tokens(cls, tokens: ThemeTokens) -> GraphThemePalette:
        """Build a palette from theme tokens."""
        sel = tokens.selection_rgb
        body = tokens.node_body_rgb
        hover = tokens.node_body_hover_rgb
        border = tokens.node_border_rgb
        return cls(
            graph_bg=QColor(*tokens.graph_bg_rgb),
            grid_major=QColor(255, 255, 255, 18),
            grid_minor=QColor(255, 255, 255, 8),
            vignette=QColor(0, 0, 0, 140),
            node_body=QColor(*body),
            node_body_hover=QColor(*hover),
            node_border=QColor(*border),
            node_border_hover=QColor(
                min(border[0] + 40, 255),
                min(border[1] + 40, 255),
                min(border[2] + 42, 255),
            ),
            selection=QColor(*sel),
            selection_soft=QColor(sel[0], sel[1], sel[2], 55),
            text_primary=QColor(240, 240, 244),
            text_secondary=QColor(160, 160, 168),
            socket_input=QColor(*tokens.socket_input_rgb),
            socket_output=QColor(*tokens.socket_output_rgb),
            socket_ring=QColor(12, 12, 14),
            marquee=QColor(sel[0], sel[1], sel[2], 40),
            marquee_border=QColor(sel[0], sel[1], sel[2], 200),
            wire=QColor(0, 0, 0),
            wire_active=QColor(*tokens.wire_active_rgb),
            wire_preview=QColor(0, 0, 0, 220),
        )


_default_palette: GraphThemePalette = GraphThemePalette.from_tokens(aphelion_dark())


def current_graph_palette() -> GraphThemePalette:
    """Return the active graph palette."""
    return _default_palette


def apply_graph_palette(tokens: ThemeTokens) -> None:
    """Replace the active graph palette from theme tokens."""
    global _default_palette
    _default_palette = GraphThemePalette.from_tokens(tokens)
