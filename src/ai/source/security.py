"""The security boundary for the source-intelligence subsystem.

Everything the assistant can learn about Aphelion's own source passes through
this module, and nothing here can write, execute, or reach the network. Four
guarantees are enforced *host-side*, never by asking the model to behave:

1. **Sandbox.** A path is canonicalised (symlinks included) and must stay
   inside the configured root. Absolute paths, ``..`` escapes, UNC paths, and
   symlinks that point outside the root are refused.
2. **Allowlist.** Only source and documentation extensions are readable, and
   known secret locations (``.env``, keys, credential stores) are denied even
   if their extension would otherwise be allowed.
3. **Redaction.** Retrieved text is scanned for credentials before it can
   reach a remote provider, and the values are replaced with ``[REDACTED]``.
4. **Untrusted marking.** Retrieved content is wrapped as data and flagged
   when it contains instruction-like text, so the agent runtime can keep it
   out of the privileged part of the prompt.
"""

from __future__ import annotations

import os
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ai.errors import SourceAccessError

# ======================================================================
# Allowlist / denylist
# ======================================================================

#: Extensions the source tools may read. Deliberately small: source and docs.
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py", ".pyi",
        ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hxx", ".inl",
        ".cs", ".java", ".rs", ".go", ".rb", ".lua",
        ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
        ".glsl", ".frag", ".vert", ".comp", ".hlsl", ".shader",
        ".md", ".rst", ".txt",
        ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg",
        ".cmake", ".pro", ".pri", ".qrc",
        ".qss", ".css", ".html", ".sql", ".sh", ".bat", ".ps1",
    }
)

#: Exact file names that are never indexed or returned, whatever their suffix.
DENIED_FILENAMES: frozenset[str] = frozenset(
    {
        ".env", ".env.local", ".env.production", ".netrc", ".npmrc",
        ".pypirc", ".htpasswd", ".pgpass", "id_rsa", "id_ed25519",
        "id_ecdsa", "id_dsa", "known_hosts", "authorized_keys",
        "credentials", "credentials.json", "secrets.json", "secrets.yaml",
        "secrets.yml", "keystore.json", "ai_credentials.json",
        "ai_settings.json", "preferences.json", "wallet.dat",
    }
)

#: Suffix patterns that mark a file as secret-bearing.
DENIED_SUFFIXES: frozenset[str] = frozenset(
    {
        ".pem", ".key", ".p12", ".pfx", ".crt", ".cer", ".der",
        ".jks", ".keystore", ".kdbx", ".ovpn", ".ppk", ".asc", ".gpg",
        ".env", ".secrets", ".secret", ".token", ".credentials", ".sqlite3",
    }
)

#: Directory names that are never walked, at any depth.
DENIED_DIRECTORIES: frozenset[str] = frozenset(
    {
        ".git", ".hg", ".svn", ".venv", "venv", "env", ".env.d",
        "__pycache__", "node_modules", "bower_components",
        "build", "dist", "out", "releases", "release", "bin", "obj",
        "installer", "installers", "third_party", "vendor",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".eggs",
        ".idea", ".vs", ".vscode", ".gradle", ".cargo", ".conda",
        "site-packages", "userdata", "logs", "cache", "temp", "tmp",
    }
)

#: Directory *prefixes* that are excluded when walking (build-<hash> etc.).
DENIED_DIRECTORY_PREFIXES: tuple[str, ...] = ("build-", "cmake-build-", "dist-")

#: Files larger than this are never read into context.
MAX_FILE_BYTES: int = 512 * 1024

#: Bytes inspected when deciding whether a file is binary.
_BINARY_SNIFF_BYTES: int = 8192


def is_allowed_file(path: Path) -> bool:
    """Whether ``path`` may be indexed or returned to the model."""
    name = path.name
    lowered = name.lower()
    if lowered in DENIED_FILENAMES:
        return False
    # ``.env`` and friends are denied even with an extra suffix appended.
    if lowered.startswith(".env") or lowered.startswith("secrets."):
        return False
    if any(lowered.endswith(suffix) for suffix in DENIED_SUFFIXES):
        return False
    if lowered.startswith("id_rsa") or lowered.startswith("id_ed25519"):
        return False
    return path.suffix.lower() in ALLOWED_EXTENSIONS


def is_denied_directory(name: str) -> bool:
    """Whether a directory should be pruned while walking the tree."""
    lowered = name.lower()
    if lowered in DENIED_DIRECTORIES:
        return True
    if lowered.endswith(".egg-info") or lowered.endswith("_env"):
        return True
    return lowered.startswith(DENIED_DIRECTORY_PREFIXES)


def looks_binary(data: bytes) -> bool:
    """Heuristic binary sniff: NUL bytes or too many non-text bytes."""
    if not data:
        return False
    sample = data[:_BINARY_SNIFF_BYTES]
    if b"\x00" in sample:
        return True
    text_bytes = bytes(range(0x20, 0x7F)) + b"\n\r\t\f\b\x1b"
    allowed = set(text_bytes)
    # UTF-8 continuation bytes are legitimate in text.
    non_text = sum(
        1 for byte in sample if byte not in allowed and byte < 0x80
    )
    return non_text / len(sample) > 0.30


# ======================================================================
# Path sandbox
# ======================================================================


def _norm(path: Path) -> str:
    """Case-normalised absolute string, for reliable containment checks."""
    return os.path.normcase(str(path))


def _is_within(child: Path, parent: Path) -> bool:
    child_norm = _norm(child)
    parent_norm = _norm(parent)
    if child_norm == parent_norm:
        return True
    return child_norm.startswith(parent_norm.rstrip(os.sep) + os.sep)


@dataclass(frozen=True)
class PathSandbox:
    """A canonicalising, container-only view of one source root."""

    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).expanduser().resolve())

    @property
    def available(self) -> bool:
        return self.root.is_dir()

    def relative(self, path: Path) -> str:
        """Return the root-relative POSIX path used in citations."""
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.name

    def resolve(self, relative: str) -> Path:
        """Resolve a model-supplied path, refusing anything outside the root.

        Raises:
            SourceAccessError: for absolute paths, UNC paths, traversals,
                symlink escapes, non-existent files, or any path that lands
                outside the configured root.
        """
        raw = str(relative or "").strip()
        if not raw:
            raise SourceAccessError(
                "A source path is required.", code="ACCESS_DENIED"
            )
        # Windows separators are accepted so the model can cite either style.
        normalised = raw.replace("\\", "/")
        if normalised.startswith("~"):
            raise SourceAccessError(
                f"Refusing to expand '{raw}': paths must be relative to the "
                "configured source root.",
                code="ACCESS_DENIED",
            )
        if normalised.startswith("//"):
            raise SourceAccessError(
                f"Refusing UNC path '{raw}'.", code="ACCESS_DENIED"
            )
        candidate = Path(normalised)
        if candidate.is_absolute() or (len(normalised) > 1 and normalised[1] == ":"):
            raise SourceAccessError(
                f"Refusing absolute path '{raw}': paths must be relative to "
                "the configured source root.",
                code="ACCESS_DENIED",
            )
        if any(part == ".." for part in candidate.parts):
            raise SourceAccessError(
                f"Refusing path traversal in '{raw}'.", code="ACCESS_DENIED"
            )

        joined = self.root / candidate
        try:
            resolved = joined.resolve()
        except OSError as exc:
            raise SourceAccessError(
                f"Could not resolve '{raw}': {exc}", code="ACCESS_DENIED"
            ) from exc
        if not _is_within(resolved, self.root):
            raise SourceAccessError(
                f"'{raw}' resolves outside the configured source root.",
                code="ACCESS_DENIED",
            )
        return resolved

    def readable_files(
        self, relative: str | None = None
    ) -> Iterable[tuple[Path, str]]:
        """Yield ``(absolute, root-relative-posix)`` for readable files.

        Never follows a directory symlink out of the root, never walks a
        denied directory, and never returns a denied file.
        """
        base = self.root if not relative else self.resolve(relative)
        if base.is_file():
            if is_allowed_file(base):
                yield base, self.relative(base)
            return
        for directory, subdirectories, filenames in os.walk(base, followlinks=False):
            current = Path(directory)
            subdirectories[:] = [
                name
                for name in subdirectories
                if not is_denied_directory(name)
                and not _escapes(current / name, self.root)
            ]
            if is_denied_directory(current.name) and current != base:
                continue
            for filename in filenames:
                candidate = current / filename
                if not is_allowed_file(candidate):
                    continue
                if _escapes(candidate, self.root):
                    continue
                yield candidate, self.relative(candidate)


def _escapes(path: Path, root: Path) -> bool:
    """Whether ``path`` is (or resolves through) a symlink leaving the root."""
    try:
        if path.is_symlink():
            return not _is_within(path.resolve(), root)
    except OSError:
        return True
    return False


# ======================================================================
# Secret redaction
# ======================================================================

REDACTED: str = "[REDACTED]"

#: ``(kind, pattern)`` pairs. Order matters: specific tokens first so their
#: shape is not mangled by the generic assignment rule.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key_block",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{16,}")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}")),
    ("huggingface_token", re.compile(r"\bhf_[A-Za-z0-9]{16,}")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}"),
    ),
    ("bearer_token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{20,}")),
)

#: ``key = "value"`` / ``key: value`` assignments for credential-ish names.
_ASSIGNMENT_PATTERN = re.compile(
    r"""(?ix)
    \b(
        api[_-]?key | apikey | secret[_-]?key | client[_-]?secret
      | access[_-]?token | refresh[_-]?token | auth[_-]?token | bearer[_-]?token
      | private[_-]?key | password | passwd | passphrase | credential
    )\b
    \s*[:=]\s*
    (?P<quote>["']?)
    (?P<value>[^\s"',;#)]{8,})
    (?P=quote)
    """
)


def redact_secrets(text: str) -> tuple[str, list[str]]:
    """Replace likely credentials in ``text``.

    Returns:
        ``(redacted_text, kinds)`` where ``kinds`` names what was found, so the
        audit view can report redactions without ever echoing a value.
    """
    if not text:
        return text, []
    found: list[str] = []
    result = text
    for kind, pattern in _SECRET_PATTERNS:
        result, count = pattern.subn(REDACTED, result)
        if count:
            found.append(kind)

    def _replace_assignment(match: re.Match[str]) -> str:
        value = match.group("value")
        if value in {REDACTED, "true", "false", "null", "none"}:
            return match.group(0)
        found.append("assigned_credential")
        quote = match.group("quote") or ""
        return f"{match.group(1)}={quote}{REDACTED}{quote}"

    result = _ASSIGNMENT_PATTERN.sub(_replace_assignment, result)
    return result, sorted(set(found))


# ======================================================================
# Prompt-injection heuristics
# ======================================================================

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_instructions",
        re.compile(r"(?i)\b(ignore|disregard|forget)\b[^.\n]{0,40}\binstructions?\b"),
    ),
    (
        "override_policy",
        re.compile(
            r"(?i)\b(override|bypass|disable|turn off)\b[^.\n]{0,30}\b"
            r"(safety|security|guardrail|permission|policy|restriction)s?\b"
        ),
    ),
    ("system_prompt", re.compile(r"(?i)\bsystem\s+(prompt|message|instructions?)\b")),
    (
        "role_switch",
        re.compile(r"(?i)\b(you are now|from now on,? you|act as if you)\b"),
    ),
    (
        "exfiltrate",
        re.compile(
            r"(?i)\b(send|email|post|upload|exfiltrate|reveal|print|leak)\b"
            r"[^.\n]{0,40}\b(api[_-]?key|credentials?|secrets?|password|token|"
            r"env(ironment)?\s+variables?)\b"
        ),
    ),
    (
        "destructive_request",
        re.compile(
            r"(?i)\b(delete|erase|wipe|format|destroy)\b[^.\n]{0,30}\b"
            r"(every|all|entire|the whole)\b[^.\n]{0,20}\b(file|node|project|disk|repo)"
        ),
    ),
    (
        "shell_execution",
        re.compile(
            r"(?i)(\brm\s+-rf\b|\bcurl\b[^\n]{0,60}\|\s*(sh|bash)\b|"
            r"\bsubprocess\b[^\n]{0,20}\bshell\s*=\s*True)"
        ),
    ),
    ("new_instructions", re.compile(r"(?i)\bnew\s+instructions?\b|[<\[]/?\s*system\s*[>\]]")),
    (
        "upload_data",
        re.compile(
            r"(?i)\b(upload|send|post|share|exfiltrate)\b[^.\n]{0,40}\b"
            r"(project|files?|data|source|code|repo(sitory)?|keys?)\b"
        ),
    ),
)


def detect_injection(text: str) -> list[str]:
    """Return markers for instruction-like text found in untrusted content.

    Findings are advisory: legitimate source comments discuss prompt injection
    and shell commands all the time. The runtime uses this only to annotate the
    content as suspected injection *and to keep treating it as data*.
    """
    if not text:
        return []
    markers: list[str] = []
    for marker, pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            markers.append(marker)
    return markers


# ======================================================================
# Security log
# ======================================================================


@dataclass
class SecurityEvent:
    """One recorded security-relevant event (never contains a secret)."""

    kind: str
    detail: str = ""
    fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {"kind": self.kind, "detail": self.detail}
        if self.fields:
            payload.update(self.fields)
        return payload


class SourceSecurityLog:
    """A bounded, thread-safe record of security-relevant decisions.

    Deliberately holds no secret values: redaction records the *kind* of secret
    and the file it was found in, never the value itself.
    """

    MAX_EVENTS: int = 200

    def __init__(self) -> None:
        self._events: deque[SecurityEvent] = deque(maxlen=self.MAX_EVENTS)
        self._lock = threading.Lock()

    def record(self, kind: str, detail: str = "", **fields: Any) -> SecurityEvent:
        event = SecurityEvent(kind=kind, detail=detail, fields=dict(fields))
        with self._lock:
            self._events.append(event)
        return event

    def events(self) -> list[SecurityEvent]:
        with self._lock:
            return list(self._events)

    def to_dicts(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.events()]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


#: Process-wide log shared by the retriever and the UI audit view.
SECURITY_LOG = SourceSecurityLog()


__all__ = [
    "ALLOWED_EXTENSIONS",
    "DENIED_DIRECTORIES",
    "DENIED_FILENAMES",
    "DENIED_SUFFIXES",
    "MAX_FILE_BYTES",
    "PathSandbox",
    "REDACTED",
    "SECURITY_LOG",
    "SecurityEvent",
    "SourceSecurityLog",
    "detect_injection",
    "is_allowed_file",
    "is_denied_directory",
    "looks_binary",
    "redact_secrets",
]
