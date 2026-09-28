"""Source indexing: files, symbols, and the incremental cache.

The index answers three questions cheaply and offline:

* Which files exist in the configured source root? (walk, allowlist, prune)
* What is defined where? (classes, functions, methods, enums, constants, and
  the node registrations that make Aphelion's graph vocabulary)
* What changed since last time? (mtime + size, confirmed by content digest)

Nothing here imports a model, touches the network, or writes anywhere except
its own cache file. Extraction is best-effort by design: a file that fails to
parse still gets indexed for lexical search, because a syntax error in one
place must not blind the assistant to the rest of the tree.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ai.errors import SourceUnavailableError
from ai.source.security import (MAX_FILE_BYTES, PathSandbox, is_allowed_file,
                                is_denied_directory, looks_binary)

#: Bumped whenever the extraction format changes, invalidating old caches.
INDEX_VERSION: int = 1

#: Upper bound on indexed files, so a misconfigured root cannot run away.
MAX_INDEXED_FILES: int = 20_000

#: Upper bound on stored symbols per file.
MAX_SYMBOLS_PER_FILE: int = 600

#: Suffix → language identifier, used for citation metadata.
LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "python", ".pyi": "python",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp",
    ".hpp": "cpp", ".hxx": "cpp", ".inl": "cpp",
    ".cs": "csharp", ".java": "java", ".rs": "rust", ".go": "go",
    ".rb": "ruby", ".lua": "lua",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".glsl": "glsl", ".frag": "glsl", ".vert": "glsl", ".comp": "glsl",
    ".hlsl": "hlsl", ".shader": "shader",
    ".md": "markdown", ".rst": "rst", ".txt": "text",
    ".json": "json", ".jsonc": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".ini": "ini", ".cfg": "ini",
    ".cmake": "cmake", ".pro": "qmake", ".pri": "qmake", ".qrc": "xml",
    ".qss": "qss", ".css": "css", ".html": "html", ".sql": "sql",
    ".sh": "shell", ".bat": "shell", ".ps1": "powershell",
}

#: Suffixes whose content we parse for symbols.
_CODE_SUFFIXES: frozenset[str] = frozenset(
    {".py", ".pyi", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hxx",
     ".inl", ".cs", ".java", ".rs", ".go", ".js", ".jsx", ".ts", ".tsx"}
)


@dataclass
class Symbol:
    """One definition found in a file.

    ``line`` and ``end_line`` are 1-based and inclusive, so a citation can
    point at an exact range. ``kind`` is one of ``class``, ``function``,
    ``method``, ``enum``, ``constant``, ``node_type``, ``port``, ``property``,
    or ``macro``.
    """

    name: str
    kind: str
    path: str
    line: int
    end_line: int = 0
    container: str = ""
    signature: str = ""
    doc: str = ""

    @property
    def qualified(self) -> str:
        return f"{self.container}.{self.name}" if self.container else self.name

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Symbol:
        return cls(
            name=str(data.get("name", "")),
            kind=str(data.get("kind", "")),
            path=str(data.get("path", "")),
            line=int(data.get("line", 0) or 0),
            end_line=int(data.get("end_line", 0) or 0),
            container=str(data.get("container", "")),
            signature=str(data.get("signature", "")),
            doc=str(data.get("doc", "")),
        )


@dataclass
class SourceFile:
    """Indexed metadata for one file (the body is read on demand)."""

    path: str
    language: str
    size: int
    mtime: float
    digest: str
    lines: int = 0
    origin: str = "core"
    symbols: list[Symbol] = field(default_factory=list)
    #: Lowercased ``path + symbol names + docs`` used for lexical scoring.
    search_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["symbols"] = [symbol.to_dict() for symbol in self.symbols]
        payload.pop("search_text", None)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceFile:
        symbols = [
            Symbol.from_dict(entry)
            for entry in data.get("symbols", ())
            if isinstance(entry, dict)
        ]
        return cls(
            path=str(data.get("path", "")),
            language=str(data.get("language", "")),
            size=int(data.get("size", 0) or 0),
            mtime=float(data.get("mtime", 0.0) or 0.0),
            digest=str(data.get("digest", "")),
            lines=int(data.get("lines", 0) or 0),
            origin=str(data.get("origin", "core")),
            symbols=symbols,
            search_text=_search_text(str(data.get("path", "")), symbols),
        )


def _search_text(path: str, symbols: Iterable[Symbol]) -> str:
    parts = [path.lower(), path.replace("/", " ").lower()]
    for symbol in symbols:
        parts.append(symbol.name.lower())
        if symbol.container:
            parts.append(f"{symbol.container}.{symbol.name}".lower())
        if symbol.doc:
            parts.append(symbol.doc.lower()[:400])
        if symbol.kind:
            parts.append(symbol.kind)
    return "\n".join(parts)


# ======================================================================
# Reading
# ======================================================================


def read_source_text(path: Path, *, max_bytes: int = MAX_FILE_BYTES) -> str:
    """Read a source file for the model, refusing binary content.

    Raises:
        SourceUnavailableError: missing, oversized, or binary content.
    """
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise SourceUnavailableError(f"Cannot read {path.name}: {exc}") from exc
    if size > max_bytes:
        raise SourceUnavailableError(
            f"{path.name} is {size} bytes, above the {max_bytes}-byte source "
            "read limit."
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SourceUnavailableError(f"Cannot read {path.name}: {exc}") from exc
    if looks_binary(data):
        raise SourceUnavailableError(
            f"{path.name} looks like a binary file and is not readable as source."
        )
    return data.decode("utf-8", errors="replace")


def digest_of(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


# ======================================================================
# Extraction
# ======================================================================

_NODE_PORT_CALL_NAMES: frozenset[str] = frozenset(
    {"add_input", "add_output", "set_property", "add_property"}
)

_CSHARP_LIKE_PATTERN = re.compile(
    r"^\s*(?:template\s*<[^>]*>\s*)?"
    r"(?P<kind>class|struct|union|enum(?:\s+class)?|namespace|interface)\s+"
    r"(?P<name>[A-Za-z_]\w*)",
    re.MULTILINE,
)
_FUNCTION_LIKE_PATTERN = re.compile(
    r"^(?:\s*(?:static|inline|virtual|constexpr|extern|public|private|"
    r"protected|explicit|friend|unsigned|signed|const)\s+)*"
    r"(?P<ret>[A-Za-z_][\w:<>,\*&\s]*?)\s+"
    r"(?:(?P<scope>[A-Za-z_]\w*)::)?(?P<name>[A-Za-z_]\w*)\s*"
    r"\((?P<args>[^;{)]*)\)\s*(?:const\s*)?[{;]",
    re.MULTILINE,
)
_MACRO_PATTERN = re.compile(r"^\s*#\s*define\s+(?P<name>[A-Za-z_]\w*)", re.MULTILINE)


def extract_symbols(path: str, text: str, language: str) -> list[Symbol]:
    """Best-effort symbol extraction; never raises."""
    try:
        if language == "python":
            symbols = _extract_python(path, text)
        elif path.endswith((".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hxx", ".inl")):
            symbols = _extract_c_like(path, text)
        elif language in {"csharp", "java"}:
            symbols = _extract_c_like(path, text)
        elif language in {"javascript", "typescript"}:
            symbols = _extract_js_like(path, text)
        elif language == "rust":
            symbols = _extract_rust(path, text)
        else:
            symbols = _extract_headings(path, text)
    except Exception:  # noqa: BLE001 - one bad file must not stop indexing
        symbols = []
    return symbols[:MAX_SYMBOLS_PER_FILE]


def _extract_python(path: str, text: str) -> list[Symbol]:
    """Extract Python definitions, including node ports and properties.

    Node classes declare their contract in :meth:`_setup_sockets` as
    ``add_input("frame", ...)`` / ``add_output(...)`` / ``set_property(...)``
    calls, so those literal names are recorded as ``port``/``property``
    symbols. That is what lets the agent connect node documentation to the
    exact line that defines it.
    """
    tree = ast.parse(text)
    symbols: list[Symbol] = []

    def add(
        node: ast.AST,
        name: str,
        kind: str,
        container: str = "",
        signature: str = "",
    ) -> None:
        end = getattr(node, "end_lineno", None) or getattr(node, "lineno", 0)
        doc = ""
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = (ast.get_docstring(node) or "")[:600]
        symbols.append(
            Symbol(
                name=name,
                kind=kind,
                path=path,
                line=int(getattr(node, "lineno", 0) or 0),
                end_line=int(end or 0),
                container=container,
                signature=signature,
                doc=doc,
            )
        )

    def visit_class(node: ast.ClassDef, container: str = "") -> None:
        bases = [_name_of(base) for base in node.bases]
        kind = "enum" if any("Enum" in base for base in bases) else "class"
        qualified = f"{container}.{node.name}" if container else node.name
        add(
            node,
            node.name,
            kind,
            container=container,
            signature=f"class {node.name}({', '.join(b for b in bases if b)})",
        )
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                add(
                    child,
                    child.name,
                    "method",
                    container=qualified,
                    signature=_py_signature(child),
                )
                _visit_ports(child, qualified)
            elif isinstance(child, ast.ClassDef):
                visit_class(child, qualified)
            elif isinstance(child, (ast.Assign, ast.AnnAssign)):
                target = _py_assign_target(child)
                if target is None:
                    continue
                if target in {"node_type", "plugin_name", "node_category"}:
                    add(
                        child,
                        f"{target}={_py_assign_literal(child) or '?'}",
                        "node_type",
                        container=qualified,
                    )
                else:
                    add(child, target, "constant", container=qualified)

    def _visit_ports(node: ast.AST, container: str) -> None:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            call = _call_name(child)
            if call not in _NODE_PORT_CALL_NAMES:
                continue
            label = _first_string_arg(child)
            if not label:
                continue
            kind = "property" if "property" in call else "port"
            add(child, label, kind, container=container)

    for statement in tree.body:
        if isinstance(statement, ast.ClassDef):
            visit_class(statement)
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add(statement, statement.name, "function", signature=_py_signature(statement))
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            target = _py_assign_target(statement)
            if target and target.isupper():
                add(statement, target, "constant")
        elif isinstance(statement, (ast.If, ast.Try)):
            # ``if TYPE_CHECKING:`` blocks and similar still declare symbols.
            for inner in statement.body:
                if isinstance(inner, ast.ClassDef):
                    visit_class(inner)
                elif isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add(inner, inner.name, "function")
    return symbols


def _py_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [arg.arg for arg in node.args.args]
    if node.args.vararg is not None:
        args.append("*" + node.args.vararg.arg)
    if node.args.kwarg is not None:
        args.append("**" + node.args.kwarg.arg)
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(args)})"


def _name_of(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _name_of(node.value)
    return ""


def _py_assign_target(node: ast.AST) -> str | None:
    target = getattr(node, "target", None) or getattr(node, "targets", None)
    if isinstance(target, list) and target:
        target = target[0]
    if isinstance(target, ast.Name):
        return target.id
    return None


def _py_assign_literal(node: ast.AST) -> str | None:
    value = getattr(node, "value", None)
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _first_string_arg(call: ast.Call) -> str | None:
    for argument in call.args:
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            return argument.value
    return None


def _extract_c_like(path: str, text: str) -> list[Symbol]:
    symbols: list[Symbol] = []
    for match in _CSHARP_LIKE_PATTERN.finditer(text):
        kind = match.group("kind")
        if kind.startswith("enum"):
            kind = "enum"
        elif kind in {"class", "struct", "union", "interface"}:
            kind = "class"
        symbols.append(
            Symbol(
                name=match.group("name"),
                kind=kind,
                path=path,
                line=text.count("\n", 0, match.start()) + 1,
            )
        )
    for match in _FUNCTION_LIKE_PATTERN.finditer(text):
        name = match.group("name")
        if name in {"if", "for", "while", "switch", "return", "sizeof"}:
            continue
        symbols.append(
            Symbol(
                name=name,
                kind="method" if match.group("scope") else "function",
                path=path,
                line=text.count("\n", 0, match.start()) + 1,
                container=match.group("scope") or "",
                signature=f"{name}({match.group('args').strip()})",
            )
        )
    for match in _MACRO_PATTERN.finditer(text):
        symbols.append(
            Symbol(
                name=match.group("name"),
                kind="macro",
                path=path,
                line=text.count("\n", 0, match.start()) + 1,
            )
        )
    return symbols


def _extract_js_like(path: str, text: str) -> list[Symbol]:
    symbols: list[Symbol] = []
    pattern = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?"
        r"(?P<kind>class|function|const|let|var|interface|enum|type)\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)",
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        kind = match.group("kind")
        if kind in {"const", "let", "var", "type"}:
            kind = "constant"
        elif kind == "function":
            kind = "function"
        symbols.append(
            Symbol(
                name=match.group("name"),
                kind=kind,
                path=path,
                line=text.count("\n", 0, match.start()) + 1,
            )
        )
    return symbols


def _extract_rust(path: str, text: str) -> list[Symbol]:
    symbols: list[Symbol] = []
    pattern = re.compile(
        r"^\s*(?:pub(?:\([^)]*\))?\s+)?"
        r"(?P<kind>fn|struct|enum|trait|impl|mod|const|static|type)\s+"
        r"(?P<name>[A-Za-z_]\w*)",
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        kind = match.group("kind")
        mapped = {
            "fn": "function", "struct": "class", "enum": "enum", "trait": "class",
            "impl": "class", "mod": "namespace", "const": "constant",
            "static": "constant", "type": "constant",
        }.get(kind, kind)
        symbols.append(
            Symbol(
                name=match.group("name"),
                kind=mapped,
                path=path,
                line=text.count("\n", 0, match.start()) + 1,
            )
        )
    return symbols


def _extract_headings(path: str, text: str) -> list[Symbol]:
    """Markdown/other docs: index their headings so docs are searchable."""
    symbols: list[Symbol] = []
    for index, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                symbols.append(
                    Symbol(name=title[:80], kind="section", path=path, line=index)
                )
    return symbols[:120]


# ======================================================================
# The index
# ======================================================================


class SourceIndex:
    """A searchable, cached view of one source root."""

    def __init__(
        self,
        root: Path | str,
        *,
        core_prefixes: Iterable[str] = (),
        max_files: int = MAX_INDEXED_FILES,
    ) -> None:
        self.sandbox = PathSandbox(Path(root))
        self._core_prefixes = tuple(
            prefix.replace("\\", "/").strip("/") for prefix in core_prefixes if prefix
        )
        self._max_files = max_files
        self._files: dict[str, SourceFile] = {}
        self._lock = threading.RLock()
        self._built = False
        self.skipped: list[str] = []

    # -- lifecycle ------------------------------------------------------

    @property
    def root(self) -> Path:
        return self.sandbox.root

    @property
    def available(self) -> bool:
        return self.sandbox.available

    @property
    def built(self) -> bool:
        return self._built

    def build(self, *, force: bool = False) -> int:
        """Index every allowed file. Returns the number of files indexed.

        Raises:
            SourceUnavailableError: the root does not exist.
        """
        if not self.available:
            raise SourceUnavailableError(
                f"Source root does not exist: {self.root}"
            )
        with self._lock:
            if self._built and not force:
                return len(self._files)
            if force:
                self._files.clear()
            self.skipped = []
            count = 0
            for absolute, relative in self.sandbox.readable_files():
                if count >= self._max_files:
                    self.skipped.append(
                        f"stopped after {self._max_files} files"
                    )
                    break
                entry = self._index_one(absolute, relative)
                if entry is not None:
                    self._files[relative] = entry
                    count += 1
            self._built = True
            return len(self._files)

    def refresh(self) -> int:
        """Re-index only files whose size, mtime, or content changed."""
        if not self._built:
            return self.build()
        with self._lock:
            seen: set[str] = set()
            changed = 0
            for absolute, relative in self.sandbox.readable_files():
                seen.add(relative)
                if self._needs_reindex(absolute, relative):
                    entry = self._index_one(absolute, relative)
                    if entry is not None:
                        self._files[relative] = entry
                        changed += 1
            for stale in set(self._files) - seen:
                del self._files[stale]
                changed += 1
            return changed

    def _needs_reindex(self, absolute: Path, relative: str) -> bool:
        existing = self._files.get(relative)
        if existing is None:
            return True
        try:
            stat = absolute.stat()
        except OSError:
            return True
        if int(stat.st_size) != existing.size:
            return True
        if abs(float(stat.st_mtime) - existing.mtime) > 1e-6:
            return True
        return False

    def _index_one(self, absolute: Path, relative: str) -> SourceFile | None:
        try:
            stat = absolute.stat()
        except OSError:
            return None
        language = LANGUAGE_BY_SUFFIX.get(absolute.suffix.lower(), "text")
        # A cheap digest of the tail plus size/mtime is enough to detect edits
        # without reading every byte of a large tree twice.
        digest = hashlib.sha1(
            f"{relative}:{stat.st_size}:{int(stat.st_mtime)}".encode()
        ).hexdigest()[:16]
        symbols: list[Symbol] = []
        lines = 0
        if absolute.suffix.lower() in _CODE_SUFFIXES and stat.st_size <= MAX_FILE_BYTES:
            try:
                text = read_source_text(absolute)
            except SourceUnavailableError:
                text = ""
            if text:
                lines = text.count("\n") + 1
                symbols = extract_symbols(relative, text, language)
        return SourceFile(
            path=relative,
            language=language,
            size=int(stat.st_size),
            mtime=float(stat.st_mtime),
            digest=digest,
            lines=lines,
            origin=self._origin_of(relative),
            symbols=symbols,
            search_text=_search_text(relative, symbols),
        )

    def origin_of(self, relative: str) -> str:
        """Public provenance lookup for a root-relative path."""
        return self._origin_of(relative)

    def _origin_of(self, relative: str) -> str:
        """Classify provenance so third-party content can be marked untrusted.

        First-party source is still untrusted *content*; this only records
        where it came from, which the audit view and the model both need.
        """
        lowered = relative.lower()
        if "/plugins/" in f"/{lowered}" or lowered.startswith("plugins/"):
            return "third_party_plugin"
        if self._core_prefixes:
            for prefix in self._core_prefixes:
                if lowered.startswith(prefix.lower() + "/") or lowered == prefix.lower():
                    return "core"
            return "other"
        return "core"

    # -- queries --------------------------------------------------------

    def files(self) -> list[SourceFile]:
        with self._lock:
            return sorted(self._files.values(), key=lambda entry: entry.path)

    def file(self, relative: str) -> SourceFile | None:
        with self._lock:
            return self._files.get(relative)

    def get_by_path(self, relative: str) -> SourceFile | None:
        return self.file(relative.replace("\\", "/").strip("/"))

    def symbols(self) -> list[Symbol]:
        with self._lock:
            return [symbol for entry in self._files.values() for symbol in entry.symbols]

    def symbols_named(self, name: str, *, limit: int = 25) -> list[Symbol]:
        """Exact (case-insensitive) symbol lookup, best matches first."""
        wanted = name.strip().lower()
        if not wanted:
            return []
        short = wanted.split("::")[-1].split(".")[-1]
        exact: list[Symbol] = []
        qualified: list[Symbol] = []
        with self._lock:
            for entry in self._files.values():
                for symbol in entry.symbols:
                    lowered = symbol.name.lower()
                    if lowered == short and symbol.qualified.lower() == wanted:
                        exact.append(symbol)
                    elif lowered == short:
                        exact.append(symbol)
                    elif wanted in f"{symbol.container}.{symbol.name}".lower():
                        qualified.append(symbol)
        ordered = _dedupe_symbols(exact) + _dedupe_symbols(qualified)
        return ordered[:limit]

    def references(self, name: str, *, limit: int = 40) -> list[dict[str, Any]]:
        """Grep-style reference lookup across indexed source files."""
        needle = name.strip()
        if not needle:
            return []
        pattern = re.compile(rf"(?<![\w.])({re.escape(needle)})(?![\w])")
        hits: list[dict[str, Any]] = []
        for entry in self.files():
            absolute = self.root / entry.path
            try:
                text = read_source_text(absolute)
            except SourceUnavailableError:
                continue
            for index, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    hits.append(
                        {
                            "path": entry.path,
                            "line": index,
                            "text": line.strip()[:200],
                        }
                    )
                    if len(hits) >= limit:
                        return hits
        return hits

    def stats(self) -> dict[str, Any]:
        files = self.files()
        return {
            "root": str(self.root),
            "available": self.available,
            "built": self._built,
            "file_count": len(files),
            "symbol_count": sum(len(entry.symbols) for entry in files),
            "languages": sorted({entry.language for entry in files}),
            "skipped": list(self.skipped),
        }

    # -- persistence ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": INDEX_VERSION,
            "root": str(self.root),
            "files": [entry.to_dict() for entry in self.files()],
        }

    def save(self, path: Path) -> None:
        """Write the cache atomically; failure is never fatal."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self.to_dict(), ensure_ascii=False)
            handle, temporary = tempfile.mkstemp(
                prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
            )
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
            os.replace(temporary, path)
        except OSError:
            return

    @classmethod
    def load(cls, path: Path, *, root: Path | str | None = None) -> SourceIndex | None:
        """Load a cache, or return ``None`` when it is unusable."""
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict) or raw.get("version") != INDEX_VERSION:
            return None
        cached_root = str(raw.get("root") or "")
        if root is not None and os.path.normcase(str(Path(root))) != os.path.normcase(
            cached_root
        ):
            # The user pointed the assistant at a different checkout.
            return None
        if not cached_root:
            return None
        index = cls(cached_root)
        files: dict[str, SourceFile] = {}
        for entry in raw.get("files", ()):
            if not isinstance(entry, dict):
                continue
            parsed = SourceFile.from_dict(entry)
            if parsed.path:
                files[parsed.path] = parsed
        index._files = files
        index._built = True
        return index


def _dedupe_symbols(symbols: list[Symbol]) -> list[Symbol]:
    seen: set[tuple[str, str, int]] = set()
    unique: list[Symbol] = []
    for symbol in symbols:
        key = (symbol.name, symbol.path, symbol.line)
        if key in seen:
            continue
        seen.add(key)
        unique.append(symbol)
    return unique


__all__ = [
    "INDEX_VERSION",
    "LANGUAGE_BY_SUFFIX",
    "MAX_INDEXED_FILES",
    "SourceFile",
    "SourceIndex",
    "Symbol",
    "digest_of",
    "extract_symbols",
    "read_source_text",
]
