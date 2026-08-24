from __future__ import annotations

import argparse
import ctypes
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path


PROBE_DOI = "10.5555/restart-recovery-probe"
EXPECTED_LIBRARY_STATUS = "restart_probe_ready"
TIMEOUT_SECONDS = 15.0


def process_is_alive(pid: int) -> bool:
    """只读探测进程；Windows 上不能使用会终止目标的 os.kill(pid, 0)。"""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except (OSError, OverflowError):
            return False
        return True

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    open_process.restype = ctypes.c_void_p
    get_exit_code = kernel32.GetExitCodeProcess
    get_exit_code.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    get_exit_code.restype = ctypes.c_int
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int

    handle = open_process(0x1000, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        return bool(get_exit_code(handle, ctypes.byref(exit_code))) and exit_code.value == 259
    finally:
        close_handle(handle)


def terminate_process(pid: int) -> None:
    if os.name != "nt":
        os.kill(pid, signal.SIGTERM)
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    open_process.restype = ctypes.c_void_p
    terminate = kernel32.TerminateProcess
    terminate.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    terminate.restype = ctypes.c_int
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int

    handle = open_process(0x0001, False, pid)
    if not handle:
        return
    try:
        terminate(handle, 1)
    finally:
        close_handle(handle)


def resolve_python(explicit: str | None) -> Path:
    if explicit is not None:
        candidate = Path(explicit)
        if not candidate.is_absolute() or not candidate.is_file():
            raise RuntimeError("scientific_reading_python_required")
        return candidate.resolve()
    candidates = [
        os.environ.get("SCIENTIFIC_READING_PYTHON"),
        str(Path.home() / "scientific-reading-data" / ".venv" / "Scripts" / "python.exe"),
        sys.executable,
    ]
    for value in candidates:
        if value and Path(value).is_file():
            return Path(value).resolve()
    raise RuntimeError("scientific_reading_python_required")


def run_json(python: Path, args: list[str], *, env: dict[str, str]) -> tuple[int, object, str]:
    result = subprocess.run(
        [str(python), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=10,
        check=False,
    )
    parsed = None
    lines = result.stdout.splitlines()
    for index, line in enumerate(lines):
        if line.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads("\n".join(lines[index:]))
                break
            except json.JSONDecodeError:
                continue
    return result.returncode, parsed, result.stderr


def real_package_directory(python: Path) -> Path:
    code = "import scientific_reading; print(scientific_reading.__path__[0])"
    result = subprocess.run(
        [str(python), "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )
    package_dir = Path(result.stdout.strip())
    if result.returncode or not package_dir.is_dir():
        raise RuntimeError(f"engine_import_failed: {result.stderr.strip()}")
    return package_dir.resolve()


def write_overlay(overlay: Path, real_package: Path) -> None:
    package = overlay / "scientific_reading"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        f"__path__.append({str(real_package)!r})\n__version__ = '0.1.0'\n",
        encoding="utf-8",
    )
    worker = textwrap.dedent(
        f"""
        from __future__ import annotations

        import importlib.util
        import time
        from pathlib import Path

        from .background_store import BackgroundJobStore

        _real_worker_path = Path({str(real_package / "worker.py")!r})
        _spec = importlib.util.spec_from_file_location(
            "scientific_reading._restart_runtime_worker", _real_worker_path
        )
        if _spec is None or _spec.loader is None:
            raise RuntimeError("real_worker_load_failed")
        _runtime = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_runtime)
        run_job = _runtime.run_job


        def probe_handler(request, heartbeat):
            heartbeat()
            time.sleep(2.0)
            heartbeat()
            return {{"status": "restart_probe_ready"}}


        def main():
            args = _runtime._build_parser().parse_args()
            raise SystemExit(
                run_job(
                    BackgroundJobStore(args.data_root),
                    args.job_id,
                    {{"restart_probe": probe_handler}},
                )
            )


        if __name__ == "__main__":
            main()
        """
    ).lstrip()
    (package / "worker.py").write_text(worker, encoding="utf-8")


def write_launch_parent(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            f"""
            import json
            import os
            import sys
            from pathlib import Path

            from scientific_reading.background_launcher import BackgroundLauncher
            from scientific_reading.background_models import BackgroundRequest
            from scientific_reading.library_service import LibraryService
            from scientific_reading.models import PaperMetadata

            data_root = Path(sys.argv[1])
            library = LibraryService(data_root)
            try:
                item = library.ensure_item(PaperMetadata(
                    title="Restart Recovery Probe",
                    authors=["Scientific Reading Test"],
                    doi={PROBE_DOI!r},
                    year=2026,
                    journal="Test Engineering",
                ))
            finally:
                library.close()
            launched = BackgroundLauncher(data_root).enqueue(BackgroundRequest(
                paper_id=item["paper_id"],
                target_stage="restart_probe",
                input_hash="c" * 64,
                payload={{"data_root": str(data_root)}},
            ))
            print(json.dumps({{
                "job_id": launched.job_id,
                "paper_id": item["paper_id"],
                "launcher_pid": os.getpid(),
            }}))
            """
        ).lstrip(),
        encoding="utf-8",
    )


def worker_command_matches(pid: int, job_id: str, data_root: Path) -> bool:
    try:
        if os.name == "nt":
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process "
                    f"-Filter 'ProcessId = {pid}' | "
                    "Select-Object -ExpandProperty CommandLine",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=2,
                check=False,
            )
            if result.returncode:
                return False
            command_line = result.stdout
        else:
            command_line = (Path("/proc") / str(pid) / "cmdline").read_bytes().decode(
                "utf-8", errors="replace"
            )
    except (OSError, subprocess.SubprocessError):
        return False
    return (
        "scientific_reading.worker" in command_line
        and command_line.count(job_id) == 1
        and str(data_root) in command_line
    )


def terminate_test_worker(data_root: Path, job_id: str) -> str:
    status_path = data_root / "jobs" / job_id / "status.json"
    if not status_path.is_file():
        return ""
    status = json.loads(status_path.read_text(encoding="utf-8"))
    pid = status.get("pid")
    if (
        status.get("job_id") == job_id
        and status.get("state") == "running"
        and isinstance(pid, int)
        and not isinstance(pid, bool)
        and pid > 0
        and worker_command_matches(pid, job_id, data_root)
    ):
        if process_is_alive(pid):
            terminate_process(pid)
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and process_is_alive(pid):
                time.sleep(0.05)
    log_path = data_root / "jobs" / job_id / "worker.log"
    if log_path.is_file():
        return log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
    return ""


def verify(python: Path) -> dict[str, object]:
    real_package = real_package_directory(python)
    with tempfile.TemporaryDirectory(prefix="sr-restart-recovery-") as temporary:
        root = Path(temporary)
        data_root = root / "data"
        overlay = root / "overlay"
        data_root.mkdir()
        write_overlay(overlay, real_package)
        launch_parent = root / "launch_parent.py"
        write_launch_parent(launch_parent)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(overlay)
        cli_env = os.environ.copy()
        cli_env["PYTHONPATH"] = str(real_package.parent)
        parent = subprocess.run(
            [str(python), str(launch_parent), str(data_root)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=10,
            check=False,
        )
        if parent.returncode:
            raise RuntimeError(f"launch_parent_failed: {parent.stderr.strip()}")
        try:
            launch = json.loads(parent.stdout)
            job_id = launch["job_id"]
            paper_id = launch["paper_id"]
        except (json.JSONDecodeError, KeyError) as error:
            raise RuntimeError("launch_parent_output_invalid") from error
        observed_running = False
        last_status = None
        try:
            deadline = time.monotonic() + TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                code, payload, stderr = run_json(
                    python,
                    ["-m", "scientific_reading", "--data-root", str(data_root), "job-status", "--job-id", job_id],
                    env=cli_env,
                )
                if code or not isinstance(payload, dict):
                    raise RuntimeError(f"job_status_failed: {stderr.strip()}")
                detail = payload.get("detail")
                if not isinstance(detail, dict):
                    raise RuntimeError("job_status_detail_missing")
                last_status = detail
                if detail.get("state") == "running":
                    observed_running = True
                if detail.get("state") == "completed":
                    if detail.get("result", {}).get("status") != EXPECTED_LIBRARY_STATUS:
                        raise RuntimeError("job_result_mismatch")
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError(f"job_completion_timeout: {last_status}")
            if not observed_running:
                raise RuntimeError("running_state_not_observed")
            code, items, stderr = run_json(
                python,
                ["-m", "scientific_reading", "--data-root", str(data_root), "library-list"],
                env=cli_env,
            )
            if code or not isinstance(items, list):
                raise RuntimeError(f"library_list_failed: {stderr.strip()}")
            item = next((entry for entry in items if entry.get("paper_id") == paper_id), None)
            library_status = item.get("status") if isinstance(item, dict) else None
            if library_status != EXPECTED_LIBRARY_STATUS:
                raise RuntimeError(f"library_status_mismatch: {library_status}")
            return {
                "status": "restart_recovery_verified",
                "parent_exited_before_completion": True,
                "observed_running": True,
                "job_state": "completed",
                "library_status": library_status,
            }
        except Exception:
            worker_log = terminate_test_worker(data_root, job_id)
            if worker_log:
                print(worker_log, file=sys.stderr)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "验证所选 Python 运行时实际导入的 scientific_reading 是否支持父进程退出后的任务恢复；"
            "这是行为验收，不校验源码 commit。"
        )
    )
    parser.add_argument(
        "--python",
        help="引擎 Python 的绝对路径；默认依次读取环境变量、用户 venv 和当前 Python",
    )
    args = parser.parse_args()
    print(json.dumps(verify(resolve_python(args.python)), ensure_ascii=False))


if __name__ == "__main__":
    main()
