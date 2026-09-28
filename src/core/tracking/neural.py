"""Optional inference/model management for tracking backends.

The editor does not import PyTorch, ONNX Runtime, or model weights at startup.
Backends query this layer and degrade to classical tracking when an optional
provider/model is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelSpec:
    name: str
    version: str
    path: Path
    sha256: str | None = None
    task: str = "tracking"


class ModelManager:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path.home() / ".aphelion" / "models"

    def path_for(self, name: str, version: str) -> Path:
        return self.root / name / version

    def is_valid(self, spec: ModelSpec) -> bool:
        if not spec.path.is_file():
            return False
        if not spec.sha256:
            return True
        digest = hashlib.sha256()
        with spec.path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest().lower() == spec.sha256.lower()


class MLInferenceEngine:
    """Lazy ONNX/PyTorch provider wrapper with CPU-safe capability reporting."""

    def __init__(self, provider: str = "auto", model_manager: ModelManager | None = None) -> None:
        self.requested_provider = provider
        self.model_manager = model_manager or ModelManager()
        self.provider = "cpu"
        self._session_cache: dict[Path, Any] = {}
        self._select_provider()

    @property
    def available(self) -> bool:
        return bool(self._session_cache) or self._onnx_available()

    def _onnx_available(self) -> bool:
        try:
            import onnxruntime  # type: ignore
            return bool(onnxruntime.get_available_providers())
        except ImportError:
            return False

    def _select_provider(self) -> None:
        try:
            import onnxruntime  # type: ignore
            providers = onnxruntime.get_available_providers()
            if self.requested_provider == "cpu":
                self.provider = "CPUExecutionProvider"
            elif self.requested_provider in providers:
                self.provider = self.requested_provider
            elif self.requested_provider == "auto":
                preferred = ("CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider")
                self.provider = next((item for item in preferred if item in providers), "cpu")
        except ImportError:
            self.provider = "cpu"

    def load_onnx(self, spec: ModelSpec) -> Any:
        if not self.model_manager.is_valid(spec):
            raise FileNotFoundError(f"Model is missing or failed checksum validation: {spec.name}")
        if spec.path in self._session_cache:
            return self._session_cache[spec.path]
        try:
            import onnxruntime  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Install the optional ONNX tracking extra to use this backend") from exc
        providers = [self.provider] if self.provider != "cpu" else ["CPUExecutionProvider"]
        session = onnxruntime.InferenceSession(str(spec.path), providers=providers)
        self._session_cache[spec.path] = session
        return session

    def run(self, spec: ModelSpec, inputs: dict[str, Any]) -> list[Any]:
        session = self.load_onnx(spec)
        names = [item.name for item in session.get_inputs()]
        return session.run(None, {name: inputs[name] for name in names})
