"""Optional AI assistant subsystem for Aphelion.

Importing this package is deliberately cheap. Nothing here opens a socket,
constructs a provider client, or imports a machine-learning runtime. The
assistant is opt-in: :data:`AI_ENABLED_BY_DEFAULT` is ``False``, and the
editor therefore pays no startup, memory, or network cost for a user who
never turns the feature on.

The runtime is split so the expensive parts stay lazy:

* :mod:`ai.types` / :mod:`ai.permissions` / :mod:`ai.validation` — pure,
  Qt-free domain types used by tools and tests.
* :mod:`ai.tools` — the structured tool API the model is allowed to call.
* :mod:`ai.providers` — network providers, imported only when used.
* :mod:`ai.engine` — the bounded agent loop.
* :mod:`ai.ui` — the PyQt panel (imports PyQt6 and is only reached from the
  editor once the assistant is enabled).
"""

from __future__ import annotations

__all__ = ["AGENT_NAME", "AI_ENABLED_BY_DEFAULT", "describe_build"]

#: Product name shown in the assistant panel header.
AGENT_NAME: str = "Aphelion AI"

#: AI is off until the user explicitly enables it and picks a provider.
AI_ENABLED_BY_DEFAULT: bool = False

#: Bumped when the on-disk AI settings document changes shape.
AI_SETTINGS_VERSION: int = 1


def describe_build() -> dict[str, object]:
    """Return lightweight build metadata for diagnostics and the UI."""
    return {
        "name": AGENT_NAME,
        "enabled_by_default": AI_ENABLED_BY_DEFAULT,
        "settings_version": AI_SETTINGS_VERSION,
    }
