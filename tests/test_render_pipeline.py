"""Storage ownership, backpressure, byte I/O and codec regressions."""
import io
import queue
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from core.native import kernels, FrameKernels
from render.ffmpeg_pipe import FfmpegPipe
from render.frame_pipeline import ordered_frames
from render.video_writer import Mp4VideoWriter, VideoEncoder, _END


def test_resource_budget_reserves_desktop_memory(monkeypatch):
    from core.perf import capabilities
    from render.resource_limits import queue_capacity, available_export_bytes, MIB
    monkeypatch.setattr(capabilities,'_physical_memory_mb',lambda:(16384,4096))
    assert available_export_bytes(2048*MIB) == 1024*MIB
    assert queue_capacity(3840*2160*3,32,64*MIB) == 2
    monkeypatch.setattr(capabilities,'_physical_memory_mb',lambda:(16384,2000))
    with pytest.raises(MemoryError):
        queue_capacity(3840*2160*3,32,64*MIB)


def test_contained_export_uses_os_limit_instead_of_speculative_scratch(monkeypatch):
    from render import resource_limits
    from core.perf import capabilities
    monkeypatch.setattr(resource_limits, '_OS_MEMORY_LIMIT_ACTIVE', True)
    monkeypatch.setattr(capabilities, '_physical_memory_mb', lambda: (16384, 2500))
    resource_limits.require_working_memory(8 * 3840 * 2160 * 3 * 4)
    monkeypatch.setattr(capabilities, '_physical_memory_mb', lambda: (16384, 200))
    with pytest.raises(MemoryError, match='critically low'):
        resource_limits.require_working_memory(1)


def test_export_thread_budget_restores_after_nested_failure():
    import cv2
    from render.resource_limits import export_thread_budget, codec_threads
    original = cv2.getNumThreads()
    with pytest.raises(RuntimeError):
        with export_thread_budget():
            with export_thread_budget():
                assert cv2.getNumThreads() <= codec_threads()
            assert cv2.getNumThreads() <= codec_threads()
            raise RuntimeError('test')
    assert cv2.getNumThreads() == original


def test_export_reclaims_preview_cache_without_invalidating_display():
    from core.project import Project
    project = Project()
    displayed = np.ones((2, 2, 3), np.float32)
    project._frame_cache.set_fast(('node', 0, 'frame'), displayed)
    assert project.release_cached_frames() == displayed.nbytes
    assert project._frame_cache.entry_count == 0
    np.testing.assert_array_equal(displayed, 1)
    project.close()


def test_preview_evicts_cold_frames_when_system_memory_is_low(monkeypatch):
    from core.project import Project
    from core.perf import capabilities
    project = Project()
    project._frame_cache.set_fast(('source', 0, 'frame'), np.ones((2, 2, 3), np.float32))
    monkeypatch.setattr(capabilities, '_physical_memory_mb', lambda: (16384, 256))
    assert project.relieve_memory_pressure() == 48
    assert project._frame_cache.entry_count == 0
    project.close()


def test_encoder_queue_owns_snapshot_of_reusable_node_buffer():
    writer = object.__new__(Mp4VideoWriter)
    writer._width, writer._height = 4, 2
    writer._pad_right = writer._pad_bottom = 0
    source = np.ones((2, 4, 3), np.uint8)
    queued = writer._prepare_frame(source)
    source[:] = 200
    np.testing.assert_array_equal(queued, 1)


def test_isolated_export_publishes_only_complete_video(tmp_path):
    import av
    from core.project import Project
    from core.nodes.generator_nodes import SolidColorNode
    from core.nodes.viewer import ViewerNode
    from render.export_worker import ExportWorker, ExportRequest, ExportFormat
    from PyQt6.QtCore import Qt
    project = Project()
    project.width, project.height = 64, 48
    source = project.add_node(SolidColorNode())
    viewer = project.add_node(ViewerNode())
    project.connect_nodes(source, 'frame', viewer, 'frame')
    output = tmp_path / 'isolated.mp4'
    request = ExportRequest(viewer, 0, 3, output, ExportFormat.MP4, 30,
                            export_audio_enabled=False, encoder=VideoEncoder.CPU)
    worker = ExportWorker(project, request)
    outcomes = []
    worker.finished_ok.connect(lambda path: outcomes.append(('ok', path)), Qt.ConnectionType.DirectConnection)
    worker.failed.connect(lambda message: outcomes.append(('failed', message)), Qt.ConnectionType.DirectConnection)
    worker.run()
    assert outcomes == [('ok', str(output))]
    with av.open(str(output)) as encoded:
        frames = list(encoded.decode(video=0))
    assert len(frames) == 4
    assert (frames[0].width, frames[0].height) == (64, 48)
    assert not list(tmp_path.glob('.aphelion-export-*'))
    previous = output.read_bytes()
    cancelled = ExportWorker(project, request)
    cancelled.cancel()
    cancelled.run()
    assert output.read_bytes() == previous
    assert not list(tmp_path.glob('.aphelion-export-*'))
    from dataclasses import replace
    active_cancel = ExportWorker(project, replace(request, end_frame=100000))
    cancelled_errors = []
    active_cancel.progress.connect(lambda *_: active_cancel.cancel(), Qt.ConnectionType.DirectConnection)
    active_cancel.failed.connect(cancelled_errors.append, Qt.ConnectionType.DirectConnection)
    started = time.monotonic()
    active_cancel.run()
    assert time.monotonic() - started < 15
    assert cancelled_errors and 'cancelled' in cancelled_errors[0].lower()
    assert output.read_bytes() == previous
    assert not list(tmp_path.glob('.aphelion-export-*'))
    project.close()


def test_status_publish_retries_windows_sharing_violation(monkeypatch, tmp_path):
    from render import export_process
    real_replace = export_process.os.replace
    attempts = []
    def replace(source, destination):
        attempts.append(True)
        if len(attempts) == 1:
            raise PermissionError('file is briefly held by reader')
        return real_replace(source, destination)
    monkeypatch.setattr(export_process.os, 'replace', replace)
    export_process._write_status(tmp_path / 'status.json', {'result': 'ok'})
    assert len(attempts) == 2


def test_static_export_cache_keeps_outputs_separate_and_respects_animation(monkeypatch):
    from core.project import Project
    from core.animation import AnimationCurve
    from core.nodes.generator_nodes import SolidColorNode
    from core.nodes.base import NodeSocketType
    project = Project()
    project.width, project.height = 2, 2
    node = SolidColorNode()
    node.add_output('number', NodeSocketType.Number)
    node_id = project.add_node(node)
    calls = []
    def render(frame, slot):
        calls.append(frame)
        return {'frame': np.full((2, 2, 3), frame, np.float32), 'number': 42 + frame}
    monkeypatch.setattr(node, 'evaluate_output', render)
    project.set_export_mode(True)
    project.evaluate_node(node_id, 0)
    assert project.evaluate_node(node_id, 1, 'number') == 42
    assert calls == [0]
    project.set_export_mode(False)
    node.animated_properties['color'] = AnimationCurve()
    project.set_export_mode(True)
    assert node_id not in project._export_static_nodes
    assert project.evaluate_node(node_id, 1, 'number') == 43
    assert project.evaluate_node(node_id, 2, 'number') == 44
    project.close()


@pytest.mark.parametrize('effect', ['exposure_contrast', 'posterize', 'threshold', 'levels',
                                  'shadows_highlights', 'color_balance', 'color_grade',
                                  'chroma_key', 'spill'])
def test_native_effect_matches_reference_and_preserves_source(effect):
    import core.nodes
    from tools.effects_benchmark import cases
    from effects.native_fx import use_backend
    source = np.random.default_rng(42).random((17, 23, 3), dtype=np.float32)
    saved = source.copy()
    call = cases(source)[effect]
    with use_backend('python'):
        expected = call()
    with use_backend('native'):
        actual = call()
    np.testing.assert_allclose(actual, expected, atol=2e-6, rtol=2e-5)
    np.testing.assert_array_equal(source, saved)


def test_native_vignette_matches_python_reference():
    import core.nodes
    from effects.filters import vignette
    from effects.native_fx import use_backend

    source = np.random.default_rng(42).random((17, 23, 3), dtype=np.float32)
    parameters = {
        'amount': 0.75,
        'softness': 0.6,
        'color': (12, 24, 36),
        'roundness': 0.2,
        'center_x': 0.4,
        'center_y': 0.65,
    }
    with use_backend('python'):
        expected = vignette(source, **parameters)
    with use_backend('native'):
        actual = vignette(source, **parameters)
    np.testing.assert_allclose(actual, expected, atol=2e-6, rtol=2e-5)


def test_native_effect_rejects_invalid_buffers():
    import aphelion_native
    source = np.ones((4, 4, 3), np.float32)
    output = np.empty_like(source)
    output.flags.writeable = False
    with pytest.raises((ValueError, BufferError)):
        aphelion_native.fx_apply(source, output, 4, 4, 2, ())
    output.flags.writeable = True
    with pytest.raises(ValueError):
        aphelion_native.fx_apply(source, output, 40, 40, 2, ())
    with pytest.raises(ValueError):
        aphelion_native.fx_apply(source, output, 4, 4, 1, (float('nan'), 0))
    storage = np.ones(49, np.float32)
    with pytest.raises((ValueError, RuntimeError)):
        aphelion_native.fx_apply(storage[:-1], storage[1:], 4, 4, 2, ())


@pytest.mark.parametrize('mode_name', ['Normal', 'Add', 'Subtract', 'Multiply', 'Screen',
                                      'Overlay', 'Difference', 'Darken', 'Lighten'])
@pytest.mark.parametrize('masked', [False, True])
def test_native_compositor_matches_reference(mode_name, masked):
    import core.nodes
    from core.nodes.enums import BlendMode
    from effects.compositing import blend_frames
    from effects.native_fx import use_backend
    rng = np.random.default_rng(35)
    bg = rng.random((13, 17, 3), dtype=np.float32) * 1.2 - .1
    fg = rng.random((13, 17, 3), dtype=np.float32)
    mask = rng.random((13, 17, 3), dtype=np.float32) if masked else None
    args = dict(mode=BlendMode[mode_name], opacity=.6, mask=mask)
    original = bg.copy()
    with use_backend('python'):
        expected = blend_frames(bg, fg, **args)
    with use_backend('native'):
        actual = blend_frames(bg, fg, **args)
    np.testing.assert_allclose(actual, expected, atol=3e-7, rtol=2e-6)
    np.testing.assert_array_equal(bg, original)


@pytest.mark.skipif(__import__('sys').platform != 'win32', reason='Windows job object')
def test_windows_job_refuses_excess_allocation():
    import subprocess
    import sys
    from render.process_limits import ExportProcessLimits
    # The failed allocation is larger than the job ceiling, so this exercises
    # OS admission without ever committing a large block of RAM.
    code = "input();\ntry:\n bytearray(256*1024*1024)\nexcept MemoryError:\n print('bounded')"
    child = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    limits = None
    try:
        limits = ExportProcessLimits(child.pid, 128 * 1024 * 1024, 25)
        output, errors = child.communicate(b'RUN\n', timeout=15)
        assert child.returncode == 0, errors.decode(errors='replace')
        assert output.strip() == b'bounded'
    finally:
        if limits:
            limits.close()
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)


def test_export_releases_socket_frames_and_propagates_memory_failure(monkeypatch):
    from core.project import Project
    from core.nodes.viewer import ViewerNode
    from render import resource_limits
    project = Project()
    node = ViewerNode()
    node_id = project.add_node(node)
    project.set_export_mode(True)
    calls = []
    def render(*args):
        calls.append(True)
        frame = np.ones((2, 2, 3), np.uint8)
        node.set_input_value('frame', frame)
        return frame
    monkeypatch.setattr(node, 'evaluate_output', render)
    monkeypatch.setattr(resource_limits, 'require_working_memory', lambda _: None)
    result = project.evaluate_node(node_id, 0)
    assert result.shape == (2, 2, 3)
    assert not node._input_values
    assert not project._export_frame_cache
    def reject(*args):
        raise MemoryError('test memory limit')
    monkeypatch.setattr(resource_limits, 'require_working_memory', reject)
    with pytest.raises(MemoryError):
        project.evaluate_node(node_id, 1)
    assert len(calls) == 1
    monkeypatch.setattr(resource_limits, 'require_working_memory', lambda _: None)
    monkeypatch.setattr(node, 'evaluate_output', reject)
    with pytest.raises(MemoryError):
        project.evaluate_node(node_id, 2)
    assert not node._input_values
    project.close()


def test_auto_keeps_hardware_and_bounds_qsv_surfaces(monkeypatch,tmp_path):
    from render import video_writer as module
    executable = module.imageio_ffmpeg.get_ffmpeg_exe()
    monkeypatch.setattr(module.imageio_ffmpeg,'get_ffmpeg_exe',lambda:executable)
    monkeypatch.setattr(module,'_detect_encoders',lambda _: {
        'h264_qsv':True,'h264_nvenc':False,'h264_amf':False})
    assert module._select_encoder('unused',VideoEncoder.AUTO) == 'h264_qsv'
    commands=[]
    def capture(command, **kwargs):
        commands.append(command)
        raise OSError('test: no encoder process launched')
    monkeypatch.setattr(module.subprocess,'Popen',capture)
    with pytest.raises(OSError):
        Mp4VideoWriter(tmp_path/'probe.mp4',fps=30,width=3840,height=2160,include_audio=False)
    command=commands[0]
    assert command[command.index('-async_depth')+1] == '1'
    assert command[command.index('-pix_fmt')+1] == 'nv12'
    assert int(command[command.index('-filter_threads')+1]) <= 4


def test_export_decoder_cache_stays_small():
    from render.video_decoder import VideoDecoder
    decoder=VideoDecoder()
    decoder.set_export_limits(True)
    decoder.set_decode_preferences(threads=128)
    assert 1 <= decoder._decode_threads <= 4
    for index in range(10):
        decoder._remember((index,2),np.zeros((2,2,3),np.uint8))
    assert len(decoder._frame_cache) == 2
    decoder.close()


def test_viewer_native_path_does_not_require_source_permission():
    from core.nodes.viewer import ViewerNode
    node = ViewerNode()
    frame = np.full((4,4,3),100,np.uint8)
    node._input_values['frame'] = frame
    node.get_property('exposure').value = 120
    node._emit_u8_allowed = False  # planner grants this only to source nodes
    result = node.evaluate(0)
    assert result.dtype == np.uint8
    np.testing.assert_array_equal(result,120)
    node.get_property('apply_exposure').value = False
    np.testing.assert_array_equal(node.evaluate(0),frame)
    np.testing.assert_array_equal(frame,100)


@pytest.mark.parametrize('gain', [0., .5, 1., 1.2, 2., 1e300])
@pytest.mark.parametrize('horizontal,vertical', [(False,False),(True,False),(False,True),(True,True)])
def test_native_lut_exact(gain, horizontal, vertical):
    source = np.arange(256*3, dtype=np.uint8).reshape(16,16,3)
    saved = source.copy()
    destination = np.empty_like(source)
    expected = np.empty_like(source)
    kernels().render_rgb_u8(source,destination,exposure=gain,
                            flip_horizontal=horizontal,flip_vertical=vertical)
    FrameKernels().render_rgb_u8(source,expected,exposure=gain,
                                 flip_horizontal=horizontal,flip_vertical=vertical)
    np.testing.assert_array_equal(destination,expected)
    np.testing.assert_array_equal(source,saved)


def test_native_rejects_readonly_destination():
    import aphelion_native
    source = np.zeros((2,2,3),np.uint8)
    output = source.copy()
    output.flags.writeable = False
    with pytest.raises((ValueError, BufferError)):
        aphelion_native.render_rgb_u8(source, output, 2,2,1.,0,0)


def test_native_quantize_boundaries():
    source = np.array([np.nan,-np.inf,np.inf,-1,0,.5,1,2,.1],np.float32).reshape(1,3,3)
    output = np.empty(source.shape,np.uint8)
    kernels().quantize_f32_u8(source,output)
    np.testing.assert_array_equal(output.ravel(), [0,0,255,0,0,128,255,255,26])


def test_quantize_matches_scalar_rounding():
    rng = np.random.default_rng(10)
    values = rng.uniform(-.1,1.1,(80,90,3)).astype(np.float32)
    values.ravel()[:255] = ((np.arange(255)+.5)/255).astype(np.float32)
    output = np.empty(values.shape,np.uint8)
    kernels().quantize_f32_u8(values,output)
    expected = np.floor(np.clip(values.astype(np.float64),0,1)*255+.5).astype(np.uint8)
    np.testing.assert_array_equal(output,expected)


@pytest.mark.parametrize('backend', ['pipe','libav'])
def test_actual_av_sync_and_timestamps(tmp_path, backend):
    import av
    from core.audio import AudioData, frame_sample_bounds
    fps = 30000/1001
    path = tmp_path/'sound.mp4'
    with Mp4VideoWriter(path,fps=fps,width=64,height=48,encoder=VideoEncoder.CPU,backend=backend) as writer:
        for index in range(30):
            first,last = frame_sample_bounds(index,fps,48000)
            tone = (.1*np.sin(2*np.pi*440*np.arange(first,last)/48000)).astype(np.float32)
            writer.write(np.full((48,64,3),index*5,np.uint8), AudioData(tone,48000))
    with av.open(str(path)) as container:
        video,audio = container.streams.video[0],container.streams.audio[0]
        assert video.codec_context.name == 'h264'
        assert audio.codec_context.name == 'aac'
        duration = 30/fps
        assert abs(float(video.duration*video.time_base)-duration) < .002
        assert abs(float(audio.duration*audio.time_base)-duration) < .002
        frames = list(container.decode(video=0))
        assert len(frames) == 30
        times = [float(frame.pts*frame.time_base) for frame in frames]
        np.testing.assert_allclose(times,np.arange(30)/fps,atol=.0001)


def test_pipe_short_reads_have_one_owned_buffer():
    class ShortReader(io.BytesIO):
        def readinto(self, buffer):
            return super().readinto(buffer[:5])
    pipe = FfmpegPipe()
    pipe._width, pipe._height, pipe._frame_bytes = 4,2,24
    pipe._proc = SimpleNamespace(stdout=ShortReader(bytes(range(48))))
    first, second = pipe.read(), pipe.read()
    assert first.flags.owndata and first.flags.writeable
    np.testing.assert_array_equal(first.ravel(),np.arange(24))
    np.testing.assert_array_equal(second.ravel(),np.arange(24,48))
    assert pipe.read() is None


def test_encoder_partial_writes_are_bytes():
    class PartialWriter:
        def __init__(self):
            self.output = bytearray()
        def write(self, view):
            assert view.ndim == 1
            count = min(5,len(view))
            self.output.extend(view[:count])
            return count
    writer = object.__new__(Mp4VideoWriter)
    stream = PartialWriter()
    writer._process = SimpleNamespace(stdin=stream)
    writer._frame_queue = queue.Queue()
    writer._write_error = None
    writer._native_encoder = None
    writer._frame_queue.put(np.arange(24,dtype=np.uint8).reshape(2,4,3))
    writer._frame_queue.put(_END)
    writer._encoder_worker()
    assert writer._write_error is None
    assert stream.output == bytes(range(24))


def test_ordered_window_is_bounded():
    started = []
    lock = threading.Lock()
    def render(index):
        with lock:
            started.append(index)
        time.sleep(.02 if index == 0 else .001)
        return index
    results = ordered_frames(render,range(100),workers=4,capacity=3,cancelled=lambda:False)
    assert next(results) == 0
    assert len(started) <= 3
    assert list(results) == list(range(1,100))


def test_cancel_stops_submission():
    stop = threading.Event()
    results = ordered_frames(lambda x:x, range(100),workers=2,capacity=2,cancelled=stop.is_set)
    assert next(results) == 0
    stop.set()
    assert list(results) == []


def test_decode_cache_byte_budget(monkeypatch):
    from render import video_decoder as module
    monkeypatch.setattr(module,'_DECODE_CACHE_BYTES',24)
    decoder = module.VideoDecoder()
    for i in range(20):
        decoder._remember((i,2),np.zeros((2,2,3),np.uint8))
    assert list(decoder._frame_cache) == [(18,2),(19,2)]
    assert decoder.cache_stats()['bytes'] == 24
    decoder.close()


@pytest.mark.parametrize('backend', ['pipe','libav'])
def test_encode_real_file_and_atomic_abort(tmp_path, backend):
    import cv2
    output = tmp_path/'output.mp4'
    with Mp4VideoWriter(output, fps=30,width=64,height=48,include_audio=False,
                        encoder=VideoEncoder.CPU,memory_budget_bytes=64*48*3,backend=backend) as writer:
        assert writer._frame_queue.maxsize == 1
        for i in range(8):
            writer.write(np.full((48,64,3),i*25,np.uint8))
    previous = output.read_bytes()
    capture = cv2.VideoCapture(str(output))
    means = []
    while True:
        ok,frame = capture.read()
        if not ok:
            break
        means.append(frame.mean())
    capture.release()
    assert len(means) == 8
    assert all(abs(value-i*25) < 4 for i,value in enumerate(means))
    writer = Mp4VideoWriter(output,fps=30,width=64,height=48,include_audio=False,encoder=VideoEncoder.CPU,backend=backend)
    writer.write(np.zeros((48,64,3),np.uint8))
    writer.abort()
    assert output.read_bytes() == previous
    assert not writer._encoder_thread.is_alive()


def test_failed_encoder_never_waits_for_queue_join(tmp_path):
    writer = Mp4VideoWriter(tmp_path/'bad.mp4',fps=30,width=64,height=48,
                           include_audio=False,encoder=VideoEncoder.CPU,queue_size=1,backend='pipe')
    writer._process.kill()
    writer._process.wait(timeout=5)
    with pytest.raises(RuntimeError):
        for _ in range(8):
            writer.write(np.zeros((48,64,3),np.uint8))
        writer.close()
    writer.abort()
@pytest.mark.parametrize("kind", ["dof", "haze", "relight", "slice", "anaglyph", "unsharp", "bloom", "sort"])
@pytest.mark.parametrize("invert", [False, True])
def test_extended_native_effect_parity(kind, invert):
    import core.nodes
    from effects import depth, filters, stylize, creative
    from effects.native_fx import use_backend
    from core.nodes.enums import AnaglyphMode, PixelSortMode
    rng = np.random.default_rng(83)
    frame = rng.random((19, 31, 3), dtype=np.float32)
    matte = rng.random((19, 31, 3), dtype=np.float32)
    cases = {
        "dof": lambda: depth.depth_of_field(frame, matte, focus=.4, focus_range=.3, max_blur=3, invert=invert),
        "haze": lambda: depth.depth_haze(frame, matte, near=.2, far=.7, color=(12, 90, 230), density=.6, invert=invert),
        "relight": lambda: depth.depth_relight(frame, matte, light_x=.3, light_y=-.4, relief=2, strength=.8, ambient=.2, invert=invert),
        "slice": lambda: depth.depth_slice(matte, near=.2, far=.7, softness=.15, invert=invert),
        "anaglyph": lambda: depth.anaglyph(frame, matte, separation=.23, mode=AnaglyphMode.AmberBlue, invert=invert),
        "unsharp": lambda: filters.unsharp_mask(frame, amount=.8, radius=3, threshold=12 if invert else 0),
        "bloom": lambda: stylize.bloom(frame, threshold=.4, intensity=.8, radius=3, softness=.2 if invert else 0, tint=(60, 180, 255)),
        "sort": lambda: creative.pixel_sort(frame, mode=PixelSortMode.Hue, threshold=.2, max_length=9, reverse=invert),
    }
    with use_backend("python"):
        expected = cases[kind]()
    with use_backend("native"):
        actual = cases[kind]()
    np.testing.assert_allclose(actual, expected, atol=2e-6, rtol=2e-6)


@pytest.mark.parametrize('space', ['sRGB', 'linear', 'log_c'])
@pytest.mark.parametrize('strength', [0.0, .37, 1.0])
def test_native_lut_and_input_color_parity(space, strength):
    import core.nodes
    from effects.input_color import apply_input_color
    from effects.native_fx import use_backend
    rng = np.random.default_rng(94)
    frame = rng.random((13, 21, 3), dtype=np.float32) * 1.2 - .1
    lut = (rng.random((7, 7, 7, 3), dtype=np.float32), 7)
    with use_backend('python'):
        expected = apply_input_color(frame, space, lut, strength)
    with use_backend('native'):
        actual = apply_input_color(frame, space, lut, strength)
    np.testing.assert_allclose(actual, expected, atol=3e-6, rtol=3e-6)


@pytest.mark.parametrize('kind', ['twirl', 'bulge', 'wave', 'tile', 'bend', 'mirror', 'kaleidoscope', 'shockwave'])
def test_native_geometry_reference_parity(kind):
    import core.nodes
    from core.nodes.enums import BendAxis, MirrorAxis
    from effects import creative, distort
    from effects.native_fx import use_backend
    frame = np.random.default_rng(67).random((23, 37, 3), dtype=np.float32)
    cases = {
        'twirl': lambda: distort.twirl(frame, angle_degrees=74, radius=.7, strength=.8, center_x=.4, center_y=.6),
        'bulge': lambda: distort.bulge(frame, strength=.7, radius=.7, center_x=.4, center_y=.6),
        'wave': lambda: distort.wave_warp(frame, amplitude=.7, frequency=3, phase=37, direction=24, frame_num=14),
        'tile': lambda: distort.tile(frame, columns=3, rows=2, mirror=True),
        'bend': lambda: distort.bend(frame, amount=.2, axis=BendAxis.Horizontal),
        'mirror': lambda: creative.mirror(frame, axis=MirrorAxis.Horizontal, offset=.3),
        'kaleidoscope': lambda: creative.kaleidoscope(frame, segments=7, rotation_degrees=-43, center_x=.4, center_y=.6),
        'shockwave': lambda: creative.shockwave(frame, progress=.4, amplitude=.2, wavelength=.3, center_x=.4, center_y=.6),
    }
    with use_backend('python'):
        expected = cases[kind]()
    with use_backend('native'):
        actual = cases[kind]()
    np.testing.assert_allclose(actual, expected, atol=2e-5, rtol=2e-5)
