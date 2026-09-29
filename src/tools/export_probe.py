"""Bounded, software-only export probe of a few frames from an existing project."""
import argparse
import json
import tempfile
import time
from pathlib import Path


def main():
    from app_io.node_loader import NodeLoader
    from app_io.aph_format import load_aph
    from render.export_worker import ExportWorker, ExportRequest, ExportFormat
    from render.video_writer import VideoEncoder
    from PyQt6.QtCore import Qt
    import av

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--frame', type=int, default=0)
    parser.add_argument('--frames', type=int, default=1)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    count = max(1, min(16, args.frames))
    NodeLoader.load_defaults()
    project = load_aph(args.project)
    report = {'frames_requested': count, 'start_frame': args.frame, 'encoder': 'CPU'}
    try:
        with tempfile.TemporaryDirectory(prefix='aphelion-probe-') as directory:
            output = Path(directory) / 'probe.mp4'
            request = ExportRequest(project.active_viewer, args.frame, args.frame + count - 1,
                                    output, ExportFormat.MP4, project.fps,
                                    export_audio_enabled=False, encoder=VideoEncoder.CPU)
            worker = ExportWorker(project, request)
            worker.finished_ok.connect(lambda _: report.update(result='ok'), Qt.ConnectionType.DirectConnection)
            worker.failed.connect(lambda error: report.update(result='failed', error=error), Qt.ConnectionType.DirectConnection)
            started = time.perf_counter()
            worker.run()
            report['seconds'] = time.perf_counter() - started
            if report.get('result') == 'ok':
                with av.open(str(output)) as container:
                    frames = list(container.decode(video=0))
                report['frames_decoded'] = len(frames)
                report['size'] = [frames[0].width, frames[0].height] if frames else None
                if len(frames) != count:
                    raise RuntimeError('Exported frame count did not match request')
    finally:
        project.close()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)
    return 0 if report.get('result') == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
