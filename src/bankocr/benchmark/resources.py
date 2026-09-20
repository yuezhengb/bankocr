"""Cross-platform process resource measurements used by release benchmarks."""

from __future__ import annotations

import os
import sys


def peak_rss_mb() -> float:
    if os.name == "nt":
        return _windows_peak_rss_mb()
    try:
        import resource

        value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
        return value / divisor
    except Exception:
        return 0.0


def _windows_peak_rss_mb() -> float:
    try:
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("page_fault_count", wintypes.DWORD),
                ("peak_working_set", ctypes.c_size_t),
                ("working_set", ctypes.c_size_t),
                ("peak_paged_pool", ctypes.c_size_t),
                ("paged_pool", ctypes.c_size_t),
                ("peak_non_paged_pool", ctypes.c_size_t),
                ("non_paged_pool", ctypes.c_size_t),
                ("pagefile_usage", ctypes.c_size_t),
                ("peak_pagefile_usage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        get_memory = psapi.GetProcessMemoryInfo
        get_memory.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        get_memory.restype = wintypes.BOOL
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not get_memory(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return 0.0
        return float(counters.peak_working_set) / (1024 * 1024)
    except Exception:
        return 0.0
