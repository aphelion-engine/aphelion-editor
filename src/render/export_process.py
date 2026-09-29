"""Supervised export: only status crosses processes, never image buffers."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict
from pathlib import Path

_EXPORT_SLOT = threading.Lock()


def _write_status(path: Path, value: dict) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    # A reader or antivirus can briefly hold the old file open on Windows.
    for attempt in range(50):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(.01)


def supervise(worker) -> None:
    # Coordinate overlapping dialogs before admission: two simultaneous jobs
    # must not each reserve the same currently available RAM.
    while not _EXPORT_SLOT.acquire(timeout=.05):
        if worker._cancelled or worker.isInterruptionRequested():
            raise RuntimeError('Export cancelled')
    try:
        if worker._cancelled or worker.isInterruptionRequested():
            raise RuntimeError('Export cancelled')
        _supervise(worker)
    finally:
        _EXPORT_SLOT.release()


def _supervise(worker) -> None:
    from app_io.plugin_loader import PluginLoader
    from render.process_limits import ExportProcessLimits
    from render.resource_limits import available_export_bytes, MIB

    worker._project.release_cached_frames()
    budget = available_export_bytes(4 * 1024 * MIB)
    if budget < 512 * MIB:
        raise MemoryError('Insufficient free memory for an isolated export; close unused applications first')
    request = worker._request
    destination = request.output_path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Same volume as destination makes the final MP4 replace atomic. All child
    # scratch files live here, so forced cancellation cannot leave large files.
    with tempfile.TemporaryDirectory(prefix='.aphelion-export-', dir=destination.parent) as directory:
        root = Path(directory)
        status_path = root / 'status.json'
        data = asdict(request)
        for name in ('format', 'encoder', 'export_quality'):
            data[name] = getattr(request, name).name
        data['output_path'] = str(root / ('frames' if request.format.name == 'PNG_SEQUENCE' else 'video.mp4'))
        settings = PluginLoader._last_settings
        directories = PluginLoader._last_directories
        payload = {'document': worker._document, 'request': data,
                   'plugins': settings.to_dict() if settings else {},
                   'plugin_directories': [str(path) for path in directories] if directories else None,
                   'sys_path': [str(path) for path in sys.path]}
        config = root / 'request.json'
        config.write_text(json.dumps(payload), encoding='utf-8')
        environment = os.environ.copy()
        environment.update({'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1',
                            'MKL_NUM_THREADS': '1', 'QT_QPA_PLATFORM': 'offscreen',
                            'TMP': str(root), 'TEMP': str(root),
                            'PYTHONPATH': os.pathsep.join(payload['sys_path'])})
        command = ([sys.executable, '--export-child', str(config)] if getattr(sys, 'frozen', False)
                   else [sys.executable, '-m', 'render.export_process', str(config)])
        process = None
        limits = None
        with (root / 'worker.log').open('w+b') as log:
            try:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log, stderr=log,
                                           env=environment,
                                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                limits = ExportProcessLimits(process.pid, budget)
                process.stdin.write(b'RUN\n')
                process.stdin.flush()
                process.stdin.close()
                last_progress = None
                cancel_started = None
                while process.poll() is None:
                    if worker._cancelled or worker.isInterruptionRequested():
                        if cancel_started is None:
                            (root / 'cancel').touch()
                            cancel_started = time.monotonic()
                        elif time.monotonic() - cancel_started > 5:
                            limits.close()
                            process.kill()
                    try:
                        status = json.loads(status_path.read_text(encoding='utf-8'))
                        progress = status.get('progress')
                        if progress and progress != last_progress:
                            worker.progress.emit(*progress)
                            last_progress = progress
                    except (OSError, ValueError):
                        pass
                    time.sleep(.05)
                if worker._cancelled or worker.isInterruptionRequested():
                    raise RuntimeError('Export cancelled')
                try:
                    status = json.loads(status_path.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    status = {}
                if process.returncode or status.get('result') != 'ok':
                    log.seek(0, 2)
                    log.seek(max(0, log.tell() - 4000))
                    detail = log.read().decode('utf-8', errors='replace')
                    raise RuntimeError(status.get('error') or
                                       f'Export process stopped (exit {process.returncode}); '
                                       f'a resource limit or native failure may have occurred.\n{detail}')
                staged = Path(data['output_path'])
                if request.format.name == 'PNG_SEQUENCE':
                    destination.mkdir(parents=True, exist_ok=True)
                    for frame in staged.iterdir():
                        os.replace(frame, destination / frame.name)
                else:
                    os.replace(staged, destination)
            finally:
                if limits is not None:
                    limits.close()
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
                    if process.stdin is not None:
                        process.stdin.close()
    worker.finished_ok.emit(str(destination))


def child_main(config_path: str) -> int:
    # Only stdlib imports before parent attaches the process to its job.
    if sys.stdin.readline().strip() != 'RUN':
        return 2
    config = Path(config_path)
    root = config.parent
    status_path = root / 'status.json'
    stop = threading.Event()
    project = None
    try:
        payload = json.loads(config.read_text(encoding='utf-8'))
        sys.path[:] = payload['sys_path']
        from app_io.node_loader import NodeLoader
        from app_io.plugin_loader import PluginLoader
        from core.preferences.models import PluginSettings
        from core.project import Project
        from render.export_worker import ExportRequest, ExportWorker, ExportFormat
        from render.video_writer import VideoEncoder, ExportQuality
        from render.resource_limits import set_os_memory_limit_active
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication

        # Text/generator and SDK nodes may use Qt font/image services. An
        # offscreen application provides them without opening another window.
        application = QApplication.instance() or QApplication([])
        set_os_memory_limit_active(sys.platform == 'win32')

        NodeLoader.load_defaults()
        paths = payload['plugin_directories']
        PluginLoader.load_installed(PluginSettings.from_dict(payload['plugins']),
                                    directories=tuple(Path(path) for path in paths) if paths else None)
        project = Project.from_dict(payload['document'])
        if set(project.nodes) != set(payload['document']['nodes']):
            raise RuntimeError('Export could not restore every project node')
        data = payload['request']
        data['format'] = ExportFormat[data['format']]
        data['encoder'] = VideoEncoder[data['encoder']]
        data['export_quality'] = ExportQuality[data['export_quality']]
        data['output_path'] = Path(data['output_path'])
        worker = ExportWorker(project, ExportRequest(**data))
        result = {}
        worker.progress.connect(lambda current, total: _write_status(status_path, {'progress': [current, total]}),
                                Qt.ConnectionType.DirectConnection)
        worker.finished_ok.connect(lambda _: result.update(result='ok'), Qt.ConnectionType.DirectConnection)
        worker.failed.connect(lambda error: result.update(result='failed', error=error), Qt.ConnectionType.DirectConnection)
        def cancellation():
            while not stop.wait(.05):
                if (root / 'cancel').exists():
                    worker.cancel()
                    return
        monitor = threading.Thread(target=cancellation, daemon=True)
        monitor.start()
        worker._run_local(project_isolated=True)
        stop.set()
        monitor.join(timeout=1)
        _write_status(status_path, result or {'result': 'failed', 'error': 'Export returned without a result'})
        return 0 if result.get('result') == 'ok' else 1
    except BaseException as exc:
        _write_status(status_path, {'result': 'failed', 'error': f'{type(exc).__name__}: {exc}'})
        return 1
    finally:
        stop.set()
        if project is not None:
            project.close()


if __name__ == '__main__':
    raise SystemExit(child_main(sys.argv[1]))
