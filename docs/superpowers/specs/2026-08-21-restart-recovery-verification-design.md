# DSH 重启恢复自动演练设计

## 1. 目标

建立一项可重复、无用户数据、不会重启当前 DSH 的进程级演练，证明：

1. DSH 一类的启动父进程退出后，引擎 detached worker 仍继续运行；
2. 新启动的进程只依靠 `dataRoot/jobs/<job_id>/` 就能读回任务状态；
3. worker 完成后，任务结果和 SQLite 文献状态都可由新进程读回；
4. 演练失败时不会遗留测试 worker 或临时数据。

本阶段不杀掉当前监听 3080 端口的真实 DSH，也不操作真实论文、飞书或网络。

## 2. 方案比较

### 方案 A：直接重启真实 DSH 并运行真实解析

最接近用户场景，但会打断当前宿主，任务耗时受 PDF 和解析环境影响，难以进入稳定回归测试。

### 方案 B：真实进程边界 + 隔离短时 worker

用真实 `BackgroundLauncher` 启动 detached worker，让模拟宿主父进程先退出；worker 复用真实 `run_job()`、`BackgroundJobStore` 和 `LibraryService`，只把耗时处理器替换为固定两秒的本地探针。新 Python 进程通过正式 CLI 读取 job 与 library。该方案不依赖网络，能稳定覆盖真正的 OS 进程边界。

### 方案 C：只检查 `Popen` 参数和状态机单元测试

速度最快，但现有测试已经覆盖参数，不能证明真实子进程在父进程退出后存活。

采用方案 B。真实 DSH 热重载仍由现有 `harness.mjs`、`plugin-check.mjs` 与 `verify-live.mjs` 共同覆盖；本阶段新增的是此前缺失的进程存活与磁盘恢复证据。

## 3. 组件与职责

### Python 引擎

- `worker.run_job()`：仅在任务成功完成并写入 `completed` 后调用现有 `_sync_library_status()`。
- `tests/test_worker.py`：证明 handler 返回的阶段状态会写入 SQLite；gate、失败和中断不得覆盖文献的最后完成状态。

当前 `_sync_library_status()` 已存在但没有调用点。本阶段只补调用与测试，不重构 worker。

### DSH 插件仓库

- `scripts/verify_restart_recovery.py`：自包含、无网络的验收脚本。
- `package.json`：增加 `verify:restart-recovery` 入口，允许显式指定 Python，默认使用 `SCIENTIFIC_READING_PYTHON` 或数据目录 venv。
- `docs/handoff-dsh-native.md` 与 `docs/roadmap.md`：记录自动演练范围、命令和证据边界。

## 4. 演练数据流

```text
顶层验证进程
  ├─ 创建 %TEMP% 隔离 dataRoot 与 Python overlay
  ├─ 启动“模拟 DSH 父进程”
  │    └─ 真实 BackgroundLauncher.enqueue()
  │         └─ detached python -m scientific_reading.worker
  └─ 等待模拟父进程退出
       ├─ 新进程：job-status → 必须观察到 running
       ├─ worker：真实 run_job + 两秒本地 handler
       ├─ 新进程：job-status → completed
       └─ 新进程：library-list → restart_probe_ready
```

overlay 只替换 `scientific_reading.worker` 入口；其 `__path__` 继续指向真实已安装引擎，因此 launcher、store、run_job、library 和 CLI 都使用实际代码。

## 5. 安全与失败处理

- dataRoot、overlay 和帮助脚本全部位于系统临时目录。
- 测试论文使用虚构 DOI `10.5555/restart-recovery-probe`，不联网。
- 最长等待 15 秒；超时后只终止 status 中记录的测试 worker PID。
- PID 必须来自本次临时 job，且在发信号前再次读回匹配的 job ID。
- `finally` 清理临时目录；失败时保留最近的 worker log 摘要在控制台，不保留资产。
- 不读取或传递飞书凭证、浏览器会话、Cookie 或用户论文路径。

## 6. 测试与验收

1. 先加入 worker SQLite 同步单元测试，确认现状为 RED。
2. 先运行跨进程演练，确认现状能看到 worker 存活和 job 完成，但 SQLite 状态仍停在 `library_ready`。
3. 最小修复：成功完成 transition 后调用 `_sync_library_status()`；gate、failed、interrupted 不调用。
4. 单元测试与跨进程演练转为 GREEN。
5. 引擎全量 pytest 通过。
6. 插件的 restart recovery、client build、harness、飞书凭证边界、plugin-check 和 verify-live 全部通过。
7. 最终报告必须区分：已完成“真实 OS 进程边界自动演练”；未直接杀掉用户当前的真实 DSH 进程。

