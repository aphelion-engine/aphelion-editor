"""Structured tool API exposed to the model.

Every capability the assistant has is one named tool with a strict JSON
schema. Tools are the only path from the model to the project: they validate
their arguments, check permissions, and mutate the project exclusively through
:mod:`core.history` commands.
"""

from __future__ import annotations

from ai.tools.base import (ToolContext, ToolRegistry, ToolSpec,
                           build_default_registry)

__all__ = ["ToolContext", "ToolRegistry", "ToolSpec", "build_default_registry"]
