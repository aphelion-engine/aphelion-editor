"""Direct libav software encoding, retaining NumPy storage through AVBufferRef."""
from fractions import Fraction
import threading


class LibavEncoder:
    def __init__(self, path, *, width, height, fps, preset, crf):
        import av
        self.av = av
        self.cancelled = threading.Event()
        self.container = av.open(str(path), 'w', format='mp4')
        try:
            self.stream = self.container.add_stream('libx264', rate=Fraction(str(fps)).limit_denominator(1000000))
        except BaseException:
            self.container.close()
            self.container = None
            raise
        self.stream.width = width
        self.stream.height = height
        self.stream.pix_fmt = 'yuv420p'
        self.stream.options = {'preset':preset, 'crf':str(crf)}
        # Bound codec working memory and avoid competing with graph workers.
        from render.resource_limits import codec_threads
        self.stream.codec_context.thread_count = codec_threads()
        self.time_base = 1 / self.stream.average_rate
        self.index = 0

    def write(self, array):
        if self.cancelled.is_set():
            raise RuntimeError('Export cancelled')
        frame = self.av.VideoFrame.from_numpy_buffer(array, format='rgb24')
        frame.pts = self.index
        frame.time_base = self.time_base
        for packet in self.stream.encode(frame):
            self.container.mux(packet)
        self.index += 1

    def close(self, *, flush=True):
        if self.container is None:
            return
        try:
            if flush and not self.cancelled.is_set():
                for packet in self.stream.encode():
                    self.container.mux(packet)
        finally:
            self.container.close()
            self.container = None
