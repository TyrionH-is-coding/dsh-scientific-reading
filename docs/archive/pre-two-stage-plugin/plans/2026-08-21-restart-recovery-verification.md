# DSH 重启恢复自动演练 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用无网络、临时数据的真实 OS 进程演练证明 detached worker 在启动父进程退出后继续执行，并由新进程读回 job 与 SQLite 状态。

**Architecture:** 插件仓库提供一个 Python 验证脚本，在 `%TEMP%` 创建 overlay，只替换 worker 入口为固定两秒 handler；launcher、run_job、store、library 和 CLI 均加载实际引擎代码。引擎仅修复已有 `_sync_library_status()` 未被成功路径调用的问题，gate 与失败状态不覆盖文献最后完成状态。

**Tech Stack:** Python 3 标准库、SQLite、现有 scientific-reading CLI、pytest、Node 脚本门禁。

---

## 文件结构

Python 引擎仓库 `Scientific-Reading-for-Newbies`：

- Modify `src/scientific_reading/worker.py`：completed transition 后同步 library 状态。
- Modify `tests/test_worker.py`：成功同步与非成功状态不覆盖测试。

DSH 插件仓库 `dsh-scientific-reading`：

- Create `scripts/verify_restart_recovery.py`：跨进程自动演练。
- Modify `package.json`：增加 `verify:restart-recovery`。
- Modify `docs/roadmap.md`：记录 T1.5 自动演练结果及边界。
- Modify `docs/handoff-dsh-native.md`：加入验证命令和下一步调整。

### Task 1: 先复现 worker 完成状态未同步

**Files:**
- Modify: `Scientific-Reading-for-Newbies/tests/test_worker.py`
- Create: `dsh-scientific-reading/scripts/verify_restart_recovery.py`

- [ ] **Step 1: 写 engine RED 测试**

在 `tests/test_worker.py` 增加 imports：

```python
from scientific_reading.library_service import LibraryService
from scientific_reading.models import PaperMetadata
```

增加帮助函数：

```python
def library_job(tmp_path, *, target_stage="paper_parse"):
    metadata = PaperMetadata(
        title="Restart Recovery Probe",
        authors=["Scientific Reading Test"],
        doi="10.5555/restart-recovery-probe",
        year=2026,
        journal="Test Engineering",
    )
    library = LibraryService(tmp_path)
    try:
        item = library.ensure_item(metadata)
    finally:
        library.close()
    store = BackgroundJobStore(tmp_path)
    handle = store.create_or_get(
        BackgroundRequest(
            paper_id=item["paper_id"],
            target_stage=target_stage,
            input_hash="b" * 64,
            payload={"data_root": str(tmp_path)},
        )
    )
    return store, handle, item["paper_id"]


def read_library_status(tmp_path, paper_id):
    library = LibraryService(tmp_path)
    try:
        return next(
            item["status"]
            for item in library.list_items()
            if item["paper_id"] == paper_id
        )
    finally:
        library.close()
```

增加成功同步测试：

```python
def test_completed_worker_syncs_stage_status_to_library(tmp_path) -> None:
    store, handle, paper_id = library_job(tmp_path)

    code = run_job(
        store,
        handle.job_id,
        {"paper_parse": lambda request, heartbeat: {"status": "parsed_fast"}},
    )

    assert code == 0
    assert store.load_status(handle.job_id).state == "completed"
    assert read_library_status(tmp_path, paper_id) == "parsed_fast"
```

增加边界测试，分别让 handler 抛 `AgentRequired` 与普通异常，断言 library 仍为 `library_ready`；每个测试只验证一个状态分支。

- [ ] **Step 2: 运行 engine RED**

Run:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest tests\test_worker.py -q
```

Expected: 成功同步测试 FAIL，实际为 `library_ready`；既有 worker 测试与两个非成功边界测试 PASS。

- [ ] **Step 3: 创建跨进程验收脚本**

创建 `scripts/verify_restart_recovery.py`，只使用标准库。脚本结构必须为：

```python
from __future__ import annotations

import argparse
import json
import os
import shutil
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


def resolve_python(explicit: str | None) -> Path:
    candidates = [
        explicit,
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
    for index, line in enumerate(result.stdout.splitlines()):
        if line.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads("\n".join(result.stdout.splitlines()[index:]))
                break
            except json.JSONDecodeError:
                continue
    return result.returncode, parsed, result.stderr
```

主流程必须完成以下机械步骤：

1. 用未覆盖环境运行 `python -c` 导入 `scientific_reading`，取得真实 package 目录；失败时报 `engine_import_failed`。
2. 在 `TemporaryDirectory(prefix="sr-restart-recovery-")` 下创建 `data/`、`overlay/scientific_reading/`、`launch_parent.py`。
3. overlay `__init__.py` 只把真实 package 目录追加到 `__path__`。
4. overlay `worker.py` 用 `importlib.util.spec_from_file_location("scientific_reading._restart_runtime_worker", real_worker_path)` 加载真实 worker，并用真实 `run_job()` 执行：

```python
def probe_handler(request, heartbeat):
    heartbeat()
    time.sleep(2.0)
    heartbeat()
    return {"status": "restart_probe_ready"}
```

5. `launch_parent.py` 用真实 `LibraryService.ensure_item()` 建虚构论文，再用真实 `BackgroundLauncher.enqueue()` 创建 `target_stage="restart_probe"` 任务；stdout 只输出 `{job_id, paper_id, launcher_pid}` JSON。
6. 顶层用 `subprocess.run()` 等待 launch parent 退出，确认返回后再轮询。每次状态轮询都启动新的正式 CLI 进程：

```python
[
    str(python), "-m", "scientific_reading",
    "--data-root", str(data_root),
    "job-status", "--job-id", job_id,
]
```

7. 15 秒内必须至少观察一次 `detail.state == "running"`，最终观察 `detail.state == "completed"` 且 `detail.result.status == "restart_probe_ready"`。
8. 再用新的 `library-list` CLI 进程确认对应 `paper_id` 的 `status == "restart_probe_ready"`。
9. 成功时输出单个 JSON：

```json
{
  "status": "restart_recovery_verified",
  "parent_exited_before_completion": true,
  "observed_running": true,
  "job_state": "completed",
  "library_status": "restart_probe_ready"
}
```

10. 失败时读取本次 job 的 `status.json`，只对其中记录且仍存活的测试 worker PID 发送终止信号；打印最后 2000 字符 worker log，随后抛出明确错误。临时目录始终由 context manager 清理。

CLI 只接受可选 `--python <absolute path>`；相对路径、目录和不存在路径直接失败。

- [ ] **Step 4: 运行跨进程 RED**

Run:

```powershell
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" scripts\verify_restart_recovery.py
```

Expected: 模拟父进程已退出，演练观察到 `running` 和 `completed`，但最终以 `library_status_mismatch: library_ready` 失败。这证明失败来自 production 同步缺口，而不是 fixture 或 detachment。

### Task 2: 最小修复并转为 GREEN

**Files:**
- Modify: `Scientific-Reading-for-Newbies/src/scientific_reading/worker.py`
- Test: `Scientific-Reading-for-Newbies/tests/test_worker.py`
- Verify: `dsh-scientific-reading/scripts/verify_restart_recovery.py`

- [ ] **Step 1: 只在 completed 路径调用现有同步函数**

把 `worker.run_job()` 的 completed 分支改为：

```python
if state == "completed":
    store.transition(job_id, state, result=values)
    _sync_library_status(request, state, values)
elif state in {"waiting_agent", "waiting_user"}:
```

不得在 `waiting_agent`、`waiting_user`、`failed` 或 `interrupted` 路径调用。

- [ ] **Step 2: 运行 engine GREEN 与全量测试**

Run:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest tests\test_worker.py -q
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest -q
```

Expected: 定向与全量均 PASS；无既有测试退化。

- [ ] **Step 3: 运行跨进程 GREEN**

Run:

```powershell
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" scripts\verify_restart_recovery.py
```

Expected: 退出 0，输出 `restart_recovery_verified`，同时 `parent_exited_before_completion` 与 `observed_running` 都为 true。

- [ ] **Step 4: 分仓提交**

引擎仓库：

```powershell
git add src/scientific_reading/worker.py tests/test_worker.py
git commit -m "修复：同步后台完成状态到文献库"
```

插件仓库：

```powershell
git add scripts/verify_restart_recovery.py
git commit -m "测试：增加重启恢复进程演练"
```

### Task 3: 接入门禁与更新真实状态文档

**Files:**
- Modify: `dsh-scientific-reading/package.json`
- Modify: `dsh-scientific-reading/docs/roadmap.md`
- Modify: `dsh-scientific-reading/docs/handoff-dsh-native.md`

- [ ] **Step 1: 增加 package 入口**

在 `package.json` scripts 增加：

```json
"verify:restart-recovery": "python scripts/verify_restart_recovery.py"
```

该入口适合已把 engine Python 设为 PATH 的环境；Windows 正式验收继续用绝对 venv Python，避免 PATH 歧义。

- [ ] **Step 2: 更新 roadmap**

把 T1.5 标为完成，并紧邻记录：自动演练使用真实 detached process、真实 `run_job`/job CLI/SQLite，在临时数据根验证父进程退出后 running→completed→library status；没有直接重启用户当前 3080 DSH。

- [ ] **Step 3: 更新 handoff**

在插件验证命令中增加绝对 venv Python 执行 `scripts\verify_restart_recovery.py`。把建议下一步的“完成重启恢复演练”改成已完成证据，将“首次真实飞书写入验收”置为下一项，但继续注明每次 sync 必须由用户针对本次写入明确确认。

- [ ] **Step 4: 插件全量门禁**

Run:

```powershell
node tests\client-build.mjs
node tests\harness.mjs
node tests\feishu-env-only.mjs
node scripts\plugin-check.mjs
node scripts\verify-live.mjs
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" scripts\verify_restart_recovery.py
git diff --check
```

Expected: 全部退出 0；真实服务仍为 18 个工具、8 条路由，测试论文仍为 `quick_read_ready`。

- [ ] **Step 5: 提交文档与入口**

```powershell
git add package.json docs/roadmap.md docs/handoff-dsh-native.md
git commit -m "文档：记录重启恢复验收"
```

### Task 4: 审核、合并与清理

**Files:**
- Verify: all files from Tasks 1-3 in both repositories

- [ ] **Step 1: 逐任务规格审查**

每项由 medium reviewer 只读检查：跨进程演练是真实 detached child；父进程先退出；状态由新 CLI 进程读取；SQLite 只在 completed 同步；不碰用户数据或网络。

- [ ] **Step 2: 逐任务代码质量审查**

规格批准后由另一 medium reviewer 检查：Windows process flags、PID 清理安全、overlay 导入边界、超时、UTF-8、临时目录、异常日志、测试非脆弱性。

- [ ] **Step 3: 最终跨仓审核**

由 fresh medium reviewer 审查两个仓库的完整 diff，确认文档没有把自动进程演练夸大为真实 GUI 宿主重启。

- [ ] **Step 4: 本地合并与主分支复验**

按用户默认约定，分别快进合并到两个仓库本地 `main`，在两个 main 上重跑各自完整门禁。成功后删除两个 worktree 和临时分支；不 push GitHub。
