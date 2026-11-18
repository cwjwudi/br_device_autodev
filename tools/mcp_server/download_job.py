"""Contain a download and its Windows descendants under one verifiable identity."""

import ctypes
import os
from ctypes import wintypes


class BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
        ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
        ("max_working_set", ctypes.c_size_t), ("active_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
        ("scheduling", wintypes.DWORD),
    ]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", BasicLimits), ("io_counters", ctypes.c_ulonglong * 6),
        ("memory_limits_and_peaks", ctypes.c_size_t * 4),
    ]


class Accounting(ctypes.Structure):
    _fields_ = [
        ("times", ctypes.c_longlong * 4), ("faults", wintypes.DWORD),
        ("total", wintypes.DWORD), ("active", wintypes.DWORD), ("terminated", wintypes.DWORD),
    ]


if os.name == "nt":
    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    def _api(name, result, *arguments):
        function = getattr(_kernel, name)
        function.restype = result
        function.argtypes = arguments
        return function

    _create = _api("CreateJobObjectW", wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCWSTR)
    _open = _api("OpenJobObjectW", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    _set = _api("SetInformationJobObject", wintypes.BOOL, wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    _assign = _api("AssignProcessToJobObject", wintypes.BOOL, wintypes.HANDLE, wintypes.HANDLE)
    _query = _api("QueryInformationJobObject", wintypes.BOOL, wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID)
    _terminate = _api("TerminateJobObject", wintypes.BOOL, wintypes.HANDLE, wintypes.UINT)
    _close = _api("CloseHandle", wintypes.BOOL, wintypes.HANDLE)
    _counter = _api("QueryPerformanceCounter", wintypes.BOOL, ctypes.POINTER(ctypes.c_longlong))
    _frequency = _api("QueryPerformanceFrequency", wintypes.BOOL, ctypes.POINTER(ctypes.c_longlong))


def _checked(value):
    if not value:
        raise ctypes.WinError(ctypes.get_last_error())
    return value


def _name(operation_id: str) -> str:
    return f"Global\\br-plc-download-{operation_id}"


def _active(handle) -> int:
    accounting = Accounting()
    _checked(_query(handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None))
    return accounting.active


def remaining_processes(operation_id: str) -> int | None:
    if os.name != "nt":
        return None
    handle = _open(0x0004, False, _name(operation_id))  # JOB_OBJECT_QUERY
    if not handle:
        return 0 if ctypes.get_last_error() == 2 else None
    try:
        return _active(handle)
    except OSError:
        return None
    finally:
        _close(handle)


def deadline_ticks(remaining_seconds: float) -> int:
    counter, frequency = ctypes.c_longlong(), ctypes.c_longlong()
    _checked(_counter(ctypes.byref(counter)))
    _checked(_frequency(ctypes.byref(frequency)))
    return counter.value + int(remaining_seconds * frequency.value)


class DownloadJob:
    def __init__(self, operation_id: str):
        if os.name != "nt":
            raise OSError("Managed RUC downloads require Windows Job Objects.")
        self.handle = _checked(_create(None, _name(operation_id)))
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            self.close()
            raise OSError("Download job identity is already in use.")
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            _checked(_set(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        except OSError:
            self.close()
            raise

    def attach(self, process):
        _checked(_assign(self.handle, int(process._handle)))

    def active(self) -> int:
        return _active(self.handle)

    def terminate(self) -> None:
        _checked(_terminate(self.handle, 1))

    def close(self) -> None:
        _close(self.handle)
