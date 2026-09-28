"""PyQt6 surfaces for the optional AI assistant.

Nothing in this package is imported by the editor until the assistant is
enabled, which is what keeps a user who never turns AI on from paying any
startup cost for it.
"""

from __future__ import annotations

__all__ = ["AIPanel", "AISettingsDialog", "EditorAgentHost", "build_ai_dock"]


def __getattr__(name: str):  # pragma: no cover - lazy import shim
    if name == "EditorAgentHost":
        from ai.ui.editor_host import EditorAgentHost

        return EditorAgentHost
    if name == "AIPanel":
        from ai.ui.ai_panel import AIPanel

        return AIPanel
    if name == "AISettingsDialog":
        from ai.ui.ai_settings_dialog import AISettingsDialog

        return AISettingsDialog
    if name == "build_ai_dock":
        from ai.ui.integration import build_ai_dock

        return build_ai_dock
    raise AttributeError(name)
