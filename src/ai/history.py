"""Conversation persistence (opt-in, and never inside the project file).

Conversations are large and churn often; putting them in ``.aph`` would bloat
every save. They are stored under ``userdata/ai_conversations/<key>.json`` and
only when the user enables "Save AI conversation with project".

Raw tool payloads are not persisted: each turn keeps the user-facing action
lines and the model's own text, which is what a user wants to re-read. That
also keeps a stored conversation small enough to reload into a context window.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logging_setup import get_logger
from utils.paths import app_data_path, ensure_directory

_LOG = get_logger("ai.history")

CONVERSATION_DIRNAME: str = "ai_conversations"
MAX_CONVERSATIONS_PER_PROJECT: int = 20
MAX_STORED_MESSAGES: int = 400
_SLUG = re.compile(r"[^A-Za-z0-9_.-]+")


def project_key(project: Any) -> str:
    """Return a stable per-project key for conversation scoping.

    Uses the document path when there is one (so two projects with the same
    name never collide) and a name hash otherwise.
    """
    path = getattr(project, "file_path", None)
    if path:
        digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:12]
        stem = _SLUG.sub("_", Path(str(path)).stem)[:40]
        return f"{stem}-{digest}"
    name = str(getattr(project, "name", "untitled") or "untitled")
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
    return f"{_SLUG.sub('_', name)[:40]}-{digest}"


@dataclass
class StoredMessage:
    """One persisted conversation turn."""

    role: str
    content: str = ""
    actions: list[str] = field(default_factory=list)
    tool_name: str = ""
    tool_ok: bool | None = None
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.actions:
            payload["actions"] = self.actions
        if self.tool_name:
            payload["tool_name"] = self.tool_name
        if self.tool_ok is not None:
            payload["tool_ok"] = self.tool_ok
        payload["timestamp"] = self.timestamp or time.time()
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoredMessage:
        return cls(
            role=str(data.get("role", "user")),
            content=str(data.get("content", "")),
            actions=[str(item) for item in (data.get("actions") or [])],
            tool_name=str(data.get("tool_name", "")),
            tool_ok=data.get("tool_ok") if isinstance(data.get("tool_ok"), bool) else None,
            timestamp=float(data.get("timestamp", 0.0) or 0.0),
        )


@dataclass
class Conversation:
    """One stored conversation."""

    conversation_id: str
    title: str = "New conversation"
    created_at: float = 0.0
    updated_at: float = 0.0
    provider_id: str = ""
    model: str = ""
    messages: list[StoredMessage] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.conversation_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "provider_id": self.provider_id,
            "model": self.model,
            "messages": [message.to_dict() for message in self.messages],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Conversation:
        return cls(
            conversation_id=str(data.get("id", "")),
            title=str(data.get("title", "New conversation")),
            created_at=float(data.get("created_at", 0.0) or 0.0),
            updated_at=float(data.get("updated_at", 0.0) or 0.0),
            provider_id=str(data.get("provider_id", "")),
            model=str(data.get("model", "")),
            messages=[
                StoredMessage.from_dict(entry)
                for entry in (data.get("messages") or [])
                if isinstance(entry, dict)
            ],
        )


class ConversationStore:
    """Per-project conversation file with a bounded number of sessions."""

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory or app_data_path("userdata", CONVERSATION_DIRNAME)

    def _path_for(self, key: str) -> Path:
        return self._directory / f"{_SLUG.sub('_', key)}.json"

    def load(self, key: str) -> list[Conversation]:
        path = self._path_for(key)
        if not path.is_file():
            return []
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _LOG.warning("Conversation file unreadable: %s", type(exc).__name__)
            return []
        entries = document.get("conversations", []) if isinstance(document, dict) else []
        conversations = [
            Conversation.from_dict(entry)
            for entry in entries
            if isinstance(entry, dict)
        ]
        conversations = [c for c in conversations if c.conversation_id]
        conversations.sort(key=lambda item: item.updated_at, reverse=True)
        return conversations

    def save(self, key: str, conversations: list[Conversation]) -> None:
        """Persist conversations atomically, keeping only the newest ones."""
        trimmed = sorted(
            conversations, key=lambda item: item.updated_at, reverse=True
        )[:MAX_CONVERSATIONS_PER_PROJECT]
        for conversation in trimmed:
            conversation.messages = conversation.messages[-MAX_STORED_MESSAGES:]
        payload = {
            "version": 1,
            "conversations": [conversation.to_dict() for conversation in trimmed],
        }
        path = self._path_for(key)
        ensure_directory(path.parent)
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        handle, temporary_name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def clear(self, key: str) -> None:
        """Delete every stored conversation for a project."""
        try:
            self._path_for(key).unlink(missing_ok=True)
        except OSError as exc:  # pragma: no cover - filesystem dependent
            _LOG.warning("Could not clear conversations: %s", exc)


def new_conversation(*, provider_id: str = "", model: str = "") -> Conversation:
    """Create a fresh, empty conversation."""
    now = time.time()
    return Conversation(
        conversation_id=hashlib.sha1(f"{now}".encode("utf-8")).hexdigest()[:16],
        created_at=now,
        updated_at=now,
        provider_id=provider_id,
        model=model,
    )
