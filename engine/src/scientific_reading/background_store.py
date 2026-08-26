from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .background_models import BackgroundRequest, JobStatus
from .workspace import atomic_write_json


ALLOWED_TRANSITIONS = {
    "queued": {"running", "failed"},
    "running": {
        "completed",
        "waiting_agent",
        "waiting_user",
        "failed",
        "interrupted",
    },
    "waiting_agent": {"queued", "failed"},
    "waiting_user": {"queued", "failed"},
    "interrupted": {"queued", "failed"},
    "completed": set(),
    "failed": {"queued"},
}


class InvalidJobTransition(RuntimeError):
    pass


class JobClaimUnavailable(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_job_id(request: BackgroundRequest) -> str:
    try:
        canonical = json.dumps(
            request.identity_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("payload 必须只包含 JSON 类型") from error
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"job_{digest}"


def windows_pid_is_alive(pid: int) -> bool:
    """只读查询 Windows 进程；拒绝访问或查询失败时保守视为存活。"""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    )
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ctypes.get_last_error() == 5
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == 259
    finally:
        kernel32.CloseHandle(handle)


@dataclass(frozen=True, slots=True)
class JobHandle:
    root: Path
    created: bool

    @property
    def job_id(self) -> str:
        return self.root.name

    @property
    def request_path(self) -> Path:
        return self.root / "request.json"

    @property
    def status_path(self) -> Path:
        return self.root / "status.json"

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def log_path(self) -> Path:
        return self.root / "worker.log"

    @property
    def resume_path(self) -> Path:
        return self.root / "resume.json"

    @property
    def reading_pipeline_path(self) -> Path:
        return self.root / "reading_pipeline.json"


class BackgroundJobStore:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root).resolve()
        self.jobs_root = self.data_root / "jobs"
        self.jobs_root.mkdir(parents=True, exist_ok=True)

    def handle(self, job_id: str, *, created: bool = False) -> JobHandle:
        if not re_full_job_id(job_id):
            raise ValueError("job_id 无效")
        root = self.jobs_root / job_id
        if not root.is_dir():
            raise FileNotFoundError(job_id)
        return JobHandle(root=root, created=created)

    def create_or_get(self, request: BackgroundRequest) -> JobHandle:
        job_id = stable_job_id(request)
        final = self.jobs_root / job_id
        temporary = self.jobs_root / f".{job_id}.{uuid.uuid4().hex}.tmp"
        temporary.mkdir()
        now = _now()
        atomic_write_json(temporary / "request.json", request.to_dict())
        atomic_write_json(
            temporary / "status.json",
            JobStatus(
                job_id=job_id,
                state="queued",
                created_at=now,
                updated_at=now,
            ).to_dict(),
        )
        try:
            temporary.rename(final)
            return JobHandle(root=final, created=True)
        except OSError:
            if not final.is_dir():
                raise
            shutil.rmtree(temporary)
            existing = self.load_request(job_id)
            if existing != request:
                raise ValueError("稳定 job_id 对应的请求不一致")
            return JobHandle(root=final, created=False)

    def load_request(self, job_id: str) -> BackgroundRequest:
        handle = self.handle(job_id)
        payload = json.loads(handle.request_path.read_text(encoding="utf-8"))
        return BackgroundRequest.from_dict(payload)

    def load_status(self, job_id: str) -> JobStatus:
        handle = self.handle(job_id)
        payload = json.loads(handle.status_path.read_text(encoding="utf-8"))
        return JobStatus.from_dict(payload)

    def transition(
        self,
        job_id: str,
        new_state: str,
        *,
        pid: int | None = None,
        reason_code: str | None = None,
        required_input: dict | None = None,
        result: dict | None = None,
        error: str | None = None,
    ) -> JobStatus:
        status = self.load_status(job_id)
        allowed = ALLOWED_TRANSITIONS.get(status.state)
        if allowed is None or new_state not in allowed:
            raise InvalidJobTransition(f"{status.state} -> {new_state}")
        if new_state in {"waiting_agent", "waiting_user"} and not reason_code:
            raise ValueError("gate 状态必须提供 reason_code")

        now = _now()
        status.state = new_state
        status.updated_at = now
        status.pid = pid if new_state == "running" else None
        status.heartbeat_at = now if new_state == "running" else None
        status.reason_code = reason_code
        status.required_input = required_input or {}
        status.result = result or {}
        status.error = error

        handle = self.handle(job_id)
        atomic_write_json(handle.status_path, status.to_dict())
        event = {
            "job_id": job_id,
            "state": new_state,
            "timestamp": now,
            "reason_code": reason_code,
        }
        try:
            with handle.events_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError:
            pass
        return status

    def read_events(self, job_id: str) -> list[dict]:
        path = self.handle(job_id).events_path
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def heartbeat(self, job_id: str, *, pid: int | None = None) -> JobStatus:
        status = self.load_status(job_id)
        if status.state != "running":
            return status
        now = _now()
        status.updated_at = now
        status.heartbeat_at = now
        if pid is not None:
            status.pid = pid
        atomic_write_json(self.handle(job_id).status_path, status.to_dict())
        return status

    def save_resume_input(self, job_id: str, values: dict) -> None:
        atomic_write_json(self.handle(job_id).resume_path, values)

    def load_resume_input(self, job_id: str) -> dict:
        path = self.handle(job_id).resume_path
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    @contextmanager
    def claim(self, job_id: str, name: str):
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
            raise ValueError("claim 名称无效")
        lock = self.handle(job_id).root / f".claim_{name}"
        stale_lock: Path | None = None
        try:
            lock.mkdir()
        except FileExistsError:
            if not self._stale_pid_lock(lock):
                raise JobClaimUnavailable(f"任务已被其他 {name} 操作领取") from None
            stale_lock = lock.with_name(f"{lock.name}.{uuid.uuid4().hex}.stale")
            try:
                lock.replace(stale_lock)
                lock.mkdir()
            except OSError:
                shutil.rmtree(stale_lock, ignore_errors=True)
                raise JobClaimUnavailable(f"任务已被其他 {name} 操作领取") from None
        atomic_write_json(
            lock / "owner.json", {"pid": os.getpid(), "started_at": _now()}
        )
        try:
            yield
        finally:
            shutil.rmtree(lock, ignore_errors=True)
            if stale_lock is not None:
                shutil.rmtree(stale_lock, ignore_errors=True)

    @contextmanager
    def launch_claim(self, job_id: str):
        """为一次 worker spawn 提供跨进程原子 claim。"""
        handle = self.handle(job_id)
        lock = handle.root / ".launch_claim"
        acquired = False
        stale_lock: Path | None = None
        try:
            try:
                lock.mkdir()
            except FileExistsError:
                if not self._stale_launch_claim(lock):
                    raise JobClaimUnavailable("任务已被其他 launch 操作领取") from None
                stale_lock = lock.with_name(f"{lock.name}.{uuid.uuid4().hex}.stale")
                try:
                    lock.replace(stale_lock)
                except OSError:
                    raise JobClaimUnavailable("任务已被其他 launch 操作领取") from None
                try:
                    lock.mkdir()
                except FileExistsError:
                    raise JobClaimUnavailable("任务已被其他 launch 操作领取") from None
            acquired = True
            atomic_write_json(
                lock / "owner.json",
                {"pid": os.getpid(), "started_at": _now()},
            )
            yield
        finally:
            if acquired:
                shutil.rmtree(lock, ignore_errors=True)
            if stale_lock is not None:
                shutil.rmtree(stale_lock, ignore_errors=True)

    @staticmethod
    def _stale_launch_claim(lock: Path) -> bool:
        try:
            age = time.time() - lock.stat().st_mtime
            owner = json.loads((lock / "owner.json").read_text(encoding="utf-8"))
            pid = owner.get("pid")
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            return age > 60 if "age" in locals() else False
        if age <= 60:
            return False
        if not isinstance(pid, int) or pid <= 0:
            return True
        return not BackgroundJobStore._pid_is_alive(pid)

    @staticmethod
    def _stale_pid_lock(
        lock: Path, *, invalid_after_seconds: float = 60
    ) -> bool:
        """死亡 owner 立即回收；缺失或损坏 owner 仅在足够老时回收。"""
        try:
            age = time.time() - lock.stat().st_mtime
            owner = json.loads((lock / "owner.json").read_text(encoding="utf-8"))
            pid = owner.get("pid")
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return age > invalid_after_seconds if "age" in locals() else False
        if not isinstance(pid, int) or pid <= 0:
            return age > invalid_after_seconds
        return not BackgroundJobStore._pid_is_alive(pid)

    @staticmethod
    def _pid_is_alive(pid: int) -> bool:
        """跨平台只读探测 PID；Windows 上禁止使用会终止进程的 os.kill(pid, 0)。"""
        if os.name != "nt":
            try:
                os.kill(pid, 0)
            except (OSError, OverflowError):
                return False
            return True

        return windows_pid_is_alive(pid)


def re_full_job_id(value: str) -> bool:
    return bool(re.fullmatch(r"job_[0-9a-f]{16}", value))
