"""Reproducible real codec/graph benchmarks (no GUI or cached-frame loops).

Run with PYTHONPATH=src: python -m tools.render_benchmark --output report.json
Fixtures are generated once in the requested work directory and reused.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time

import cv2
import imageio_ffmpeg
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--work', type=Path, default=Path('benchmarks/media'))
    parser.add_argument('--frames', type=int, default=48)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    from core.native import kernels, probe
    from render.video_writer import Mp4VideoWriter, VideoEncoder
    from render.video_decoder import VideoDecoder
    from tools.playback_benchmark import _build_graph
    args.work.mkdir(parents=True, exist_ok=True)
    report = {'machine': platform.platform(), 'python': platform.python_version(),
              'cpu_count': os.cpu_count(), 'native': probe().to_dict(),
              'frames': args.frames, 'repeats': args.repeats, 'results': []}
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    for width, height, fps, codec in [(1920,1080,30,'h264'), (1920,1080,60,'h264'),
                                     (3840,2160,30,'h264'), (3840,2160,60,'h264'),
                                     (3840,2160,30,'hevc')]:
        label = f'{width}x{height}-{fps}-{codec}'
        source = args.work / f'{label}-{args.frames}.mp4'
        if not source.exists():
            subprocess.run([ffmpeg, '-v','error','-y','-f','lavfi','-i',
                            f'testsrc2=size={width}x{height}:rate={fps}', '-frames:v',str(args.frames),
                            '-c:v','libx264' if codec == 'h264' else 'libx265', '-preset','ultrafast',
                            '-pix_fmt','yuv420p', str(source)], check=True, capture_output=True)
        measurements = {}
        for repeat in range(args.repeats):
            decoder = VideoDecoder()
            decoder.open(str(source), use_proxy=False)
            started = time.perf_counter()
            for index in range(args.frames):
                frame = decoder.read_rgb(index, 0)
                assert frame is not None and frame.shape == (height,width,3)
            measurements.setdefault('decode_fps', []).append(args.frames/(time.perf_counter()-started))
            decoder.close()
            project, viewer = _build_graph(str(source), 'bare')
            project.set_export_audio_enabled(False)
            project.nodes[viewer].get_property('exposure').value = 120
            started = time.perf_counter()
            for index in range(args.frames):
                assert project.evaluate_node(viewer, index) is not None
            measurements.setdefault('preview_graph_fps', []).append(args.frames/(time.perf_counter()-started))
            project.close()
            # Full-resolution real graph + software encoder, including drain/mux.
            project, viewer = _build_graph(str(source), 'bare')
            project.nodes[viewer].get_property('exposure').value = 120
            from render.export_worker import ExportWorker, ExportRequest, ExportFormat
            output = args.work / 'output.mp4'
            request = ExportRequest(viewer,0,args.frames-1,output,ExportFormat.MP4,fps,export_audio_enabled=False)
            worker = ExportWorker(project, request)
            project.set_full_resolution_override(True)
            project.set_export_audio_enabled(False)
            project.set_export_mode(True)
            started = time.perf_counter()
            with Mp4VideoWriter(output,fps=fps,width=width,height=height,include_audio=False,encoder=VideoEncoder.CPU) as writer:
                for index in range(args.frames):
                    frame, _ = worker._evaluate_frame_rgb(index)
                    assert frame is not None
                    writer.write(frame)
            measurements.setdefault('export_cpu_fps', []).append(args.frames/(time.perf_counter()-started))
            project.close()
            capture = cv2.VideoCapture(str(output))
            count = 0
            while True:
                ok, decoded = capture.read()
                if not ok:
                    break
                assert decoded.shape == (height,width,3)
                count += 1
            assert count == args.frames, (count, args.frames)
            assert abs(capture.get(cv2.CAP_PROP_FPS)-fps) < 0.01
            capture.release()
        row = {'case': label, 'samples': measurements,
               'median': {key: statistics.median(values) for key,values in measurements.items()}}
        report['results'].append(row)
        print(json.dumps(row), flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
