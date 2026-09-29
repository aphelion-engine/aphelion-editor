"""OS-enforced resource envelope for an owned Windows export process tree."""
from __future__ import annotations

import ctypes as c
import sys
from ctypes import wintypes as w


class _Basic(c.Structure):
    _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64),
                ('flags', w.DWORD), ('min_ws', c.c_size_t), ('max_ws', c.c_size_t),
                ('active', w.DWORD), ('affinity', c.c_size_t),
                ('priority', w.DWORD), ('scheduling', w.DWORD)]


class _IO(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in
               ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]


class _Limits(c.Structure):
    _fields_ = [('basic', _Basic), ('io', _IO), ('process_memory', c.c_size_t),
                ('job_memory', c.c_size_t), ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]


class _CPU(c.Structure):
    _fields_ = [('flags', w.DWORD), ('rate', w.DWORD)]


class ExportProcessLimits:
    """Hold the job handle until the child and all its encoders have exited.

    Child waits for a startup token, so assignment precedes media decoding.
    Closing the handle kills descendants too, including a stuck FFmpeg.
    Failure to install requested Windows limits aborts startup.
    """

    def __init__(self, pid: int, memory_bytes: int, cpu_percent: int = 75):
        self.handle = None
        if sys.platform != 'win32':
            return
        k = self.kernel = c.WinDLL('kernel32', use_last_error=True)
        k.CreateJobObjectW.restype = w.HANDLE
        k.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        k.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        k.OpenProcess.restype = w.HANDLE
        k.CloseHandle.argtypes = [w.HANDLE]
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise c.WinError(c.get_last_error())
        process = None
        try:
            limits = _Limits()
            # JOB_MEMORY plus KILL_ON_JOB_CLOSE; limit applies to the whole tree.
            limits.basic.flags = 0x200 | 0x2000
            limits.job_memory = max(1, int(memory_bytes))
            if not k.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)):
                raise c.WinError(c.get_last_error())
            cpu = _CPU(1 | 4, max(1, min(100, cpu_percent)) * 100)
            if not k.SetInformationJobObject(self.handle, 15, c.byref(cpu), c.sizeof(cpu)):
                raise c.WinError(c.get_last_error())
            process = k.OpenProcess(0x100 | 0x1, False, pid)
            if not process or not k.AssignProcessToJobObject(self.handle, process):
                raise c.WinError(c.get_last_error())
        except BaseException:
            self.close()
            raise
        finally:
            if process:
                k.CloseHandle(process)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
