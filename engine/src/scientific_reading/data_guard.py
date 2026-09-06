"""跨进程数据根操作锁：备份先关闭入口，再等待在途操作结束。"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path


class DataRootBusy(ValueError):
    pass


_local = threading.local()


def _key(root: Path) -> str:
    return os.path.normcase(str(Path(root).resolve()))


def _windows_lock(stream, exclusive: bool) -> bool:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class Overlapped(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LockFileEx.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped),
    )
    kernel.LockFileEx.restype = wintypes.BOOL
    flags = 1 | (2 if exclusive else 0)  # FAIL_IMMEDIATELY, EXCLUSIVE_LOCK
    if kernel.LockFileEx(msvcrt.get_osfhandle(stream.fileno()), flags, 0, 1, 0, ctypes.byref(Overlapped())):
        return True
    error = ctypes.get_last_error()
    if error == 33:  # ERROR_LOCK_VIOLATION
        return False
    raise ctypes.WinError(error)


@contextmanager
def _file_lock(key: str, kind: str, *, exclusive: bool, deadline: float):
    directory = Path(tempfile.gettempdir()) / "scientific-reading-operation-locks"
    directory.mkdir(mode=0o700, exist_ok=True)
    name = hashlib.sha256(key.encode("utf-8")).hexdigest() + "." + kind
    # Lock files live outside the payload; never unlink a potentially locked inode.
    with (directory / name).open("a+b") as stream:
        while True:
            if os.name == "nt":
                acquired = _windows_lock(stream, exclusive)
            else:
                import fcntl
                try:
                    fcntl.flock(stream, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                    acquired = True
                except BlockingIOError:
                    acquired = False
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise DataRootBusy("data_root_busy")
            time.sleep(min(0.02, max(0, deadline - time.monotonic())))
        yield
        # Closing the handle also releases locks after exceptions and process death.


@contextmanager
def data_root_operation(root: Path, *, timeout: float = 0.0):
    """整个受支持写操作持有共享锁；已有操作内部可在同线程重入。"""
    key = _key(root)
    held = getattr(_local, "held", None)
    if held is None:
        held = _local.held = {}
    if held.get(key) == "freeze":
        raise DataRootBusy("data_root_frozen")
    if key in held:
        yield
        return
    # Admission and activity are separate so waiting backups cannot be starved.
    with _file_lock(key, "admission", exclusive=False, deadline=time.monotonic() + max(0, timeout)):
        activity = _file_lock(key, "active", exclusive=False, deadline=time.monotonic())
        activity.__enter__()
    held[key] = "operation"
    try:
        yield
    finally:
        del held[key]
        activity.__exit__(None, None, None)


@contextmanager
def data_root_freeze(root: Path, *, timeout: float = 30.0):
    key = _key(root)
    held = getattr(_local, "held", None)
    if held is None:
        held = _local.held = {}
    if key in held:
        raise DataRootBusy("backup_inside_active_operation")
    deadline = time.monotonic() + max(0, timeout)
    with _file_lock(key, "admission", exclusive=True, deadline=deadline):
        with _file_lock(key, "active", exclusive=True, deadline=deadline):
            held[key] = "freeze"
            try:
                yield
            finally:
                del held[key]


def root_operation(method):
    """供具有 data_root 的公开服务写方法使用；CLI/worker 同时保护跨服务操作。"""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with data_root_operation(self.data_root):
            return method(self, *args, **kwargs)
    return guarded


def workspace_data_root(workspace) -> Path:
    """解析受支持的论文工作区；独立 fixture 仅锁自身目录。"""
    root = Path(workspace.root).resolve()
    paper_id = r"[A-Za-z0-9][A-Za-z0-9_.-]*"
    if (
        root.parent.name.casefold() == "papers"
        and re.fullmatch(paper_id, root.name)
        and ".." not in root.name
    ):
        return root.parents[1]
    if (
        root.parent.name.casefold() == "generations"
        and re.fullmatch(r"[0-9a-f]{16}", root.name)
        and root.parents[2].name.casefold() == "papers"
        and re.fullmatch(paper_id, root.parents[1].name)
        and ".." not in root.parents[1].name
    ):
        return root.parents[3]
    return root


def workspace_operation(method):
    @wraps(method)
    def guarded(self, workspace, *args, **kwargs):
        with data_root_operation(workspace_data_root(workspace)):
            return method(self, workspace, *args, **kwargs)
    return guarded


def data_root_method_operation(method):
    @wraps(method)
    def guarded(self, data_root, *args, **kwargs):
        with data_root_operation(data_root):
            return method(self, data_root, *args, **kwargs)
    return guarded
