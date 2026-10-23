"""Windows Job Objects: contain a task's whole process tree, including detached descendants.

A job created with KILL_ON_JOB_CLOSE terminates every member when it is terminated or its
last handle closes, so even grandchildren whose parent already exited are cleaned up.
On other platforms every function is a no-op returning None/False.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JobObjectExtendedLimitInformation = 9
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001


class _IO(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rt", "wt", "ot")]


class _Basic(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class _Extended(ctypes.Structure):
    _fields_ = [("Basic", _Basic), ("Io", _IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


if os.name == "nt":
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    _k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    _k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _k32.CloseHandle.argtypes = (wintypes.HANDLE,)


def contain(pid: int):
    """Create a kill-on-close job and put pid in it. Returns the job handle, or None if unavailable."""
    if os.name != "nt":
        return None
    job = _k32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _Extended()
    info.Basic.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not _k32.SetInformationJobObject(job, JobObjectExtendedLimitInformation, ctypes.byref(info),
                                        ctypes.sizeof(info)):
        _k32.CloseHandle(job)
        return None
    ph = _k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
    ok = bool(ph) and bool(_k32.AssignProcessToJobObject(job, ph))
    if ph:
        _k32.CloseHandle(ph)
    if not ok:
        _k32.CloseHandle(job)
        return None
    return job


def terminate(job) -> bool:
    return bool(job) and os.name == "nt" and bool(_k32.TerminateJobObject(job, 1))


def close(job) -> None:
    if job and os.name == "nt":
        _k32.CloseHandle(job)
