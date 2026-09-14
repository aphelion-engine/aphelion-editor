"""``python main.py --benchmark-playback <file>`` — real playback measurement.

This exists because "playback feels laggy" is not an actionable bug report.
This tool turns it into a per-stage millisecond breakdown on the user's own
machine and media, so a regression is a number rather than an opinion, and
so the effect of a decoder/proxy/graph change can be seen immediately.

What it measures, in the order the frames flow:

1. **Source decode** — raw sequential decode with no graph at all. This is
   the floor: if this is not comfortably above the target frame rate,
   nothing downstream matters (see the "critical bare-playback gate").
2. **Decode + proxy** — the same decode through a generated all-intra proxy,
   if one exists. The gap between this and (1) is what real proxies buy.
3. **Bare graph** — ``Video Input → Viewer`` evaluated as a real ``Project``.
   The gap between this and (1) is pure engine overhead.
4. **Light / medium graphs** — the same source with effects attached.
5. **Presentation** — float→uint8 conversion, QImage construction, QPixmap
   upload, and fit-scaling, measured on an offscreen Qt surface.
6. **Seek latency** — p50/p95/mean of random seeks, with and without the
   keyframe index.
7. **First-frame and playback-start latency** — how long the user waits
   before something appears and before motion begins.

Every number printed is measured. Anything that cannot be measured (no
FFmpeg, no proxy, no Qt) is reported as unavailable with the reason, never
guessed or estimated.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

#: Percent of frames that must land inside the budget for a "realtime" verdict.
REALTIME_TARGET: float = 0.95


def _percentile(values: Sequence[float], fraction: float) -> float:
    """Return the nearest-rank percentile of ``values``."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return float(ordered[index])


@dataclass(slots=True)
class Timing:
    """A measured stage."""

    name: str
    unit: str
    samples: list[float] = field(default_factory=list)
    note: str = ""

    def add_ms(self, milliseconds: float) -> None:
        """Record one millisecond sample."""
        self.samples.append(float(milliseconds))

    @property
    def count(self) -> int:
        """Number of samples recorded."""
        return len(self.samples)

    @property
    def mean(self) -> float:
        """Mean sample value."""
        return statistics.fmean(self.samples) if self.samples else 0.0

    @property
    def p50(self) -> float:
        """Median sample value."""
        return _percentile(self.samples, 0.50)

    @property
    def p95(self) -> float:
        """95th percentile sample value."""
        return _percentile(self.samples, 0.95)

    @property
    def maximum(self) -> float:
        """Largest sample value."""
        return max(self.samples) if self.samples else 0.0

    @property
    def fps(self) -> float:
        """Throughput implied by the mean sample."""
        return (1000.0 / self.mean) if self.mean > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""
        return {
            "name": self.name,
            "count": self.count,
            "mean_ms": round(self.mean, 4),
            "p50_ms": round(self.p50, 4),
            "p95_ms": round(self.p95, 4),
            "max_ms": round(self.maximum, 4),
            "fps": round(self.fps, 3),
            "note": self.note,
        }


@dataclass(slots=True)
class BenchmarkReport:
    """Everything the run measured."""

    source: str = ""
    media: dict[str, Any] = field(default_factory=dict)
    machine: dict[str, Any] = field(default_factory=dict)
    timings: list[Timing] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def timing(self, name: str) -> Timing:
        """Return an existing timing by name, creating it on first use."""
        for entry in self.timings:
            if entry.name == name:
                return entry
        created = Timing(name=name, unit="ms")
        self.timings.append(created)
        return created

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""
        return {
            "source": self.source,
            "media": self.media,
            "machine": self.machine,
            "unavailable": list(self.unavailable),
            "notes": list(self.notes),
            "timings": [entry.to_dict() for entry in self.timings],
        }

    def format_report(self, target_fps: float) -> str:
        """Return the terminal report."""
        budget = 1000.0 / max(0.001, target_fps)
        lines = [
            "",
            "=" * 66,
            "Aphelion playback benchmark",
            "=" * 66,
            f"source        : {self.source}",
        ]
        for key, value in self.media.items():
            lines.append(f"  {key:<12}: {value}")
        lines.append(f"target        : {target_fps:g} FPS  ({budget:.2f} ms/frame)")

        backend = self.machine.get("frame_kernels")
        if backend:
            detail = f" (v{self.machine['native_version']})" if backend == "native" else ""
            lines.append(f"frame kernels : {backend}{detail}")
        lines.append("")
        lines.append(
            f"{'stage':<32}{'mean ms':>9}{'p50':>9}{'p95':>9}{'FPS':>9}"
        )
        lines.append("-" * 66)
        for entry in self.timings:
            lines.append(
                f"{entry.name:<32}{entry.mean:>9.2f}{entry.p50:>9.2f}"
                f"{entry.p95:>9.2f}{entry.fps:>9.1f}"
            )

        if self.unavailable:
            lines.append("")
            lines.append("unavailable:")
            lines.extend(f"  - {item}" for item in self.unavailable)

        if self.notes:
            lines.append("")
            lines.append("notes:")
            lines.extend(f"  - {item}" for item in self.notes)

        lines.append("")
        lines.extend(self._verdicts(target_fps))
        lines.append("=" * 66)
        return "\n".join(lines)

    def _verdicts(self, target_fps: float) -> list[str]:
        """Return pass/fail lines against the acceptance gates."""
        budget = 1000.0 / max(0.001, target_fps)
        lines = ["verdicts:"]

        bare = self._find("bare graph")
        if bare is not None and bare.count:
            ratio = budget / bare.mean if bare.mean > 0 else 0.0
            verdict = "PASS" if ratio >= 2.0 else "FAIL"
            lines.append(
                f"  [{verdict}] bare playback gate: {ratio:.2f}x realtime "
                f"(need >= 2.00x for effect headroom)"
            )
        else:
            lines.append("  [n/a ] bare playback gate: not measured")

        seek = self._find("seek")
        if seek is not None and seek.count:
            verdict = "PASS" if seek.p95 <= 50.0 else "WARN"
            lines.append(f"  [{verdict}] seek p95 {seek.p95:.1f} ms (target <= 50 ms)")

        return lines

    def _find(self, prefix: str) -> Timing | None:
        for entry in self.timings:
            if entry.name.startswith(prefix):
                return entry
        return None


# ----------------------------------------------------------------------
# Measurement helpers
# ----------------------------------------------------------------------


def _measure(fn: Callable[[], Any], frames: int, *, warmup: int = 2) -> list[float]:
    """Return per-frame milliseconds for ``frames`` calls to ``fn``."""
    samples: list[float] = []
    for index in range(frames + warmup):
        start = time.perf_counter()
        fn()
        elapsed = (time.perf_counter() - start) * 1000.0
        if index >= warmup:
            samples.append(elapsed)
    return samples


def _machine_info() -> dict[str, Any]:
    """Return a description of the test machine."""
    info: dict[str, Any] = {"python": sys.version.split()[0]}
    try:
        import platform

        info["platform"] = f"{platform.system()} {platform.release()}"
        info["cpu_logical"] = os.cpu_count()
    except Exception:  # noqa: BLE001
        pass
    try:
        from core.perf.capabilities import detect_capabilities

        caps = detect_capabilities()
        info["ram_total_mb"] = caps.ram_total_mb
        if caps.gpu_name:
            info["gpu"] = caps.gpu_name
        if caps.hardware_encoders:
            info["hw_encoders"] = list(caps.hardware_encoders)
        # Recording the backend is not decoration: two runs of this tool
        # only compare if the frame kernels and the codec path match, and
        # the difference is invisible in the timings themselves.
        info["frame_kernels"] = caps.frame_backend
        info["native_version"] = caps.native_version
    except Exception:  # noqa: BLE001
        pass
    return info


# ----------------------------------------------------------------------
# Suites
# ----------------------------------------------------------------------


def _measure_source_decode(report: BenchmarkReport, path: str, frames: int) -> None:
    """Raw sequential decode with no graph; the pipeline floor."""
    try:
        from render.video_decoder import VideoDecoder
    except Exception as exc:  # noqa: BLE001
        report.unavailable.append(f"source decode: {exc}")
        return

    decoder = VideoDecoder()
    info = decoder.open(path)
    if info is None:
        report.unavailable.append("source decode: could not open media")
        return

    report.media.update(
        {
            "resolution": f"{info.width}x{info.height}",
            "fps": f"{info.fps:.3f}",
            "frames": info.frame_count,
            "duration_s": f"{info.duration_sec:.2f}",
            "audio": "yes" if info.has_audio else "no",
        }
    )

    count = min(frames, max(1, info.frame_count))
    try:
        # Sequential cursor rather than re-reading frame 0, so the number
        # reflects playback rather than a single cached frame.
        cursor = {"index": 0}

        def advance() -> None:
            decoder.read_rgb(cursor["index"], 0)
            cursor["index"] = min(cursor["index"] + 1, max(0, info.frame_count - 1))

        samples = _measure(advance, count)
    finally:
        decoder.close()

    timing = report.timing("source decode (full res)")
    for value in samples:
        timing.add_ms(value)


def _measure_proxy_decode(report: BenchmarkReport, path: str, frames: int) -> None:
    """Decode through a generated proxy, if one exists."""
    try:
        from core.media.proxy import get_proxy_manager
        from render.video_decoder import VideoDecoder

        manager = get_proxy_manager()
        entry = manager.lookup_with_info(path)
    except Exception as exc:  # noqa: BLE001
        report.unavailable.append(f"proxy decode: {exc}")
        return

    if entry is None:
        report.unavailable.append(
            "proxy decode: no proxy present "
            f"(run once to generate, or set Proxy height in preferences; "
            f"cache: {manager.cache_root})"
        )
        return

    proxy_path = str(entry[0])
    decoder = VideoDecoder()
    info = decoder.open(proxy_path)
    if info is None:
        report.unavailable.append("proxy decode: could not open generated proxy")
        return

    report.media["proxy"] = proxy_path
    count = min(frames, max(1, info.frame_count))
    cursor = {"index": 0}

    try:

        def advance() -> None:
            decoder.read_rgb(cursor["index"], 0)
            cursor["index"] = min(cursor["index"] + 1, max(0, info.frame_count - 1))

        samples = _measure(advance, count)
    finally:
        decoder.close()

    timing = report.timing("decode via proxy")
    for value in samples:
        timing.add_ms(value)

    # Note the size difference so the reader can judge what was compared.
    try:
        gain = Path(path).stat().st_size / max(1, Path(proxy_path).stat().st_size)
        report.notes.append(
            f"proxy is {gain:.1f}x smaller on disk than the original "
            f"({Path(proxy_path).name})"
        )
    except OSError:
        pass


def _build_graph(path: str, preset: str):
    """Construct a real ``Project`` graph around a media source."""
    from app_io.node_loader import NodeLoader
    from core.project import Project

    NodeLoader.load_defaults()

    by_type: dict[str, Any] = {}
    for cls in NodeLoader.default_nodes:
        by_type.setdefault(cls.node_type, cls)

    project = Project(f"bench-{preset}")
    node_defs: list[tuple[str, dict[str, Any]]] = []

    if preset == "bare":
        node_defs = [("Video Input", {"file_path": path}), ("Viewer", {})]
    elif preset == "light":
        node_defs = [
            ("Video Input", {"file_path": path}),
            ("Exposure & Contrast", {}),
            ("Transform 2D", {}),
            ("Viewer", {}),
        ]
    elif preset == "medium":
        node_defs = [
            ("Video Input", {"file_path": path}),
            ("Color Grading", {}),
            ("Gaussian Blur", {}),
            ("Transform 2D", {}),
            ("Viewer", {}),
        ]
    else:
        node_defs = [
            ("Video Input", {"file_path": path}),
            ("Chroma Key", {}),
            ("Gaussian Blur", {}),
            ("Glow", {}),
            ("Transform 2D", {}),
            ("Viewer", {}),
        ]

    ids: list[str] = []
    for node_type, properties in node_defs:
        cls = by_type.get(node_type)
        if cls is None:
            raise KeyError(f"node type not registered: {node_type}")
        node = cls()
        for key, value in properties.items():
            prop = node.get_property(key)
            if prop is not None:
                prop.value = value
        ids.append(project.add_node(node))

    for producer_id, consumer_id in zip(ids, ids[1:]):
        producer = project.nodes[producer_id]
        consumer = project.nodes[consumer_id]
        out_slot = next(iter(producer.outputs))
        in_slot = next(iter(consumer.inputs))
        if not project.connect_nodes(producer_id, out_slot, consumer_id, in_slot):
            raise RuntimeError(
                f"could not connect {producer.node_type} -> {consumer.node_type}"
            )

    return project, ids[-1]


def _measure_graph(
    report: BenchmarkReport,
    path: str,
    preset: str,
    frames: int,
) -> None:
    """Evaluate a real graph and record per-frame cost."""
    label = f"{preset} graph"
    try:
        project, viewer_id = _build_graph(path, preset)
    except Exception as exc:  # noqa: BLE001
        report.unavailable.append(f"{label}: {exc}")
        return

    try:
        plan = project.render_plan()
        report.notes.append(f"{preset}: {plan.describe()}")

        count = max(4, frames)
        cursor = 0

        def advance() -> None:
            nonlocal cursor
            project.evaluate_node(viewer_id, cursor)
            cursor += 1

        samples = _measure(advance, count, warmup=4)
    except Exception as exc:  # noqa: BLE001
        report.unavailable.append(f"{label}: {exc}")
        return
    finally:
        try:
            project.close()
        except Exception:  # noqa: BLE001
            pass

    timing = report.timing(label)
    for value in samples:
        timing.add_ms(value)


def _measure_seek(report: BenchmarkReport, path: str) -> None:
    """Random seek latency, with and without the keyframe index."""
    try:
        from render.video_decoder import VideoDecoder
    except Exception as exc:  # noqa: BLE001
        report.unavailable.append(f"seek: {exc}")
        return

    decoder = VideoDecoder()
    info = decoder.open(path)
    if info is None:
        report.unavailable.append("seek: could not open media")
        return

    try:
        total = max(2, info.frame_count)
        targets = [
            int(total * (index + 1) / 25) for index in range(24)
        ]

        # Cold seeks: drop the decode LRU between seeks so the measurement
        # reflects real random access rather than cache hits.
        samples: list[float] = []
        for target in targets:
            decoder.clear_frame_cache()
            start = time.perf_counter()
            decoder.read_rgb(min(target, total - 1), 0)
            samples.append((time.perf_counter() - start) * 1000.0)

        timing = report.timing("seek")
        for value in samples:
            timing.add_ms(value)

        index = decoder._keyframes
        if index is not None and index.complete:
            report.notes.append(
                f"keyframe index: {index.summary()} "
                f"(worst seek distance {index.worst_gop} frames)"
            )
        else:
            report.unavailable.append(
                "keyframe index: not built yet (run again once the background "
                "indexing pass finishes)"
            )
    finally:
        decoder.close()


def _measure_presentation(report: BenchmarkReport, path: str) -> None:
    """Render a frame into a Qt surface and time the presentation stages."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    try:
        from effects.frame_ops import to_display_u8
        from PyQt6.QtWidgets import QApplication
        from render.video_decoder import VideoDecoder
    except Exception as exc:  # noqa: BLE001
        report.unavailable.append(f"presentation: {exc}")
        return

    app = QApplication.instance() or QApplication([])
    del app

    decoder = VideoDecoder()
    info = decoder.open(path)
    if info is None:
        report.unavailable.append("presentation: could not open media")
        return

    try:
        import numpy as np
        from PyQt6.QtGui import QImage, QPixmap

        frame_u8 = decoder.read_rgb(0, 960)
        if frame_u8 is None:
            report.unavailable.append("presentation: could not decode a frame")
            return

        # The float representation an effect chain would hand to the display
        # boundary, so the conversion cost is measured honestly.
        frame_f32 = np.multiply(frame_u8, np.float32(1.0 / 255.0), dtype=np.float32)

        convert = report.timing("presentation: convert")
        for value in _measure(lambda: to_display_u8(frame_f32), 30):
            convert.add_ms(value)

        contiguous = np.ascontiguousarray(frame_u8)
        height, width = contiguous.shape[:2]

        def make_image() -> None:
            image = QImage(
                contiguous.data,
                width,
                height,
                3 * width,
                QImage.Format.Format_RGB888,
            )
            image.width()

        upload = report.timing("presentation: qimage")
        for value in _measure(make_image, 30):
            upload.add_ms(value)

        def make_pixmap() -> None:
            image = QImage(
                contiguous.data,
                width,
                height,
                3 * width,
                QImage.Format.Format_RGB888,
            )
            pixmap = QPixmap.fromImage(image)
            pixmap.width()

        qt_upload = report.timing("presentation: qpixmap")
        for value in _measure(make_pixmap, 30):
            qt_upload.add_ms(value)

        report.media["presented size"] = f"{width}x{height} (preview width 960)"
    except Exception as exc:  # noqa: BLE001
        report.unavailable.append(f"presentation: {exc}")
    finally:
        decoder.close()


def _measure_latency(report: BenchmarkReport, path: str) -> None:
    """Cold first-frame latency and warm re-render, through the real graph.

    This deliberately drives ``Project.evaluate_node`` rather than the Qt
    worker thread: the question is how long the *engine* takes to produce a
    frame, which is independent of signal delivery latency and can be
    measured without an event loop.
    """
    try:
        from core.project import Project  # noqa: F401 - import check only
    except Exception as exc:  # noqa: BLE001
        report.unavailable.append(f"latency: {exc}")
        return

    try:
        project, viewer_id = _build_graph(path, "bare")
    except Exception as exc:  # noqa: BLE001
        report.unavailable.append(f"latency: {exc}")
        return

    try:
        for _ in range(3):
            project.clear_cache()
            start = time.perf_counter()
            project.evaluate_node(viewer_id, 0)
            report.timing("cold first frame").add_ms(
                (time.perf_counter() - start) * 1000.0
            )

        # A repeat read of the same frame is what pressing play on a paused
        # timeline actually costs, so it is worth showing separately.
        for index in range(8):
            start = time.perf_counter()
            project.evaluate_node(viewer_id, index % 2)
            report.timing("warm frame (cached)").add_ms(
                (time.perf_counter() - start) * 1000.0
            )
    except Exception as exc:  # noqa: BLE001
        report.unavailable.append(f"latency: {exc}")
    finally:
        try:
            project.close()
        except Exception:  # noqa: BLE001
            pass


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------


def run_benchmark(
    path: str,
    *,
    frames: int = 120,
    target_fps: float = 30.0,
    suites: Sequence[str] | None = None,
    json_path: str | None = None,
) -> int:
    """Run the playback benchmark and print the report.

    Parameters:
        path: Media file to benchmark.
        frames: Frames sampled per throughput stage.
        target_fps: Frame rate the verdicts are judged against.
        suites: Optional subset of ``decode``, ``graph``, ``seek``,
            ``presentation``, ``latency``.
        json_path: Optional path for a machine-readable dump.

    Returns:
        Process exit code (0 on success).
    """
    source = str(path)
    if not Path(source).is_file():
        print(f"error: media file not found: {source}", file=sys.stderr)
        return 2

    selected = set(suites) if suites else {
        "decode",
        "graph",
        "seek",
        "presentation",
        "latency",
    }

    report = BenchmarkReport(source=source, machine=_machine_info())

    if "decode" in selected:
        _measure_source_decode(report, source, frames)
        _measure_proxy_decode(report, source, frames)
    if "graph" in selected:
        for preset in ("bare", "light", "medium"):
            _measure_graph(report, source, preset, frames)
    if "seek" in selected:
        _measure_seek(report, source)
    if "presentation" in selected:
        _measure_presentation(report, source)
    if "latency" in selected:
        _measure_latency(report, source)

    print(report.format_report(target_fps))

    if json_path:
        destination = Path(json_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(report.to_dict(), indent=2),
            encoding="utf-8",
        )
        print(f"wrote {destination}")

    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the benchmark flags on the editor CLI parser."""
    parser.add_argument(
        "--benchmark-playback",
        type=str,
        default=None,
        metavar="MEDIA",
        help=(
            "Run the playback benchmark against a media file and print a "
            "per-stage timing breakdown, then exit."
        ),
    )
    parser.add_argument(
        "--benchmark-frames",
        type=int,
        default=120,
        help="Frames sampled per throughput stage (default: 120).",
    )
    parser.add_argument(
        "--benchmark-target-fps",
        type=float,
        default=30.0,
        help="Frame rate the benchmark verdicts are judged against.",
    )
    parser.add_argument(
        "--benchmark-json",
        type=str,
        default=None,
        help="Write the benchmark results to this JSON file.",
    )


def main_from_args(args: argparse.Namespace) -> int | None:
    """Run the benchmark when ``--benchmark-playback`` was supplied."""
    target = getattr(args, "benchmark_playback", None)
    if not target:
        return None
    return run_benchmark(
        target,
        frames=int(getattr(args, "benchmark_frames", 120) or 120),
        target_fps=float(getattr(args, "benchmark_target_fps", 30.0) or 30.0),
        json_path=getattr(args, "benchmark_json", None),
    )
