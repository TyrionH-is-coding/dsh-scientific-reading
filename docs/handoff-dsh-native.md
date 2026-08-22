# DSH 原生开发交接

> 交接日期：2026-08-21
> 用途：从当前可运行版本继续在 DSH 内原生开发。本文记录的是实际代码、运行环境与实测结果；旧文档中的 Phase 标签若与本文冲突，以本文和代码为准。

## 1. 当前基线

| 项目 | 当前状态 |
|---|---|
| DSH 插件仓库 | `dsh-scientific-reading`，分支 `main`（以当前仓库 HEAD 为准） |
| Python 引擎仓库 | `Scientific-Reading-for-Newbies`，基线 `b259754`，分支 `main` |
| 已测试 DSH 宿主 | `@deepseek-ai/dsh@0.1.0-rc.7`；Node 22 |
| 数据目录 | `%USERPROFILE%\scientific-reading-data`，与两个仓库分离 |
| 引擎 Python | `%USERPROFILE%\scientific-reading-data\.venv\Scripts\python.exe` |
| 引擎安装方式 | editable install，当前 import 直接指向相邻 Python 仓库的 `src\scientific_reading` |
| 飞书配置 | `%USERPROFILE%\scientific-reading-data\feishu-config.example.json`，仓库外保存 |
| DSH 本地服务 | `http://127.0.0.1:3080`，上线验证已通过 |
| 当前测试论文 | `Attention Is All You Need`，状态 `quick_read_ready` |

重要现状：插件没有 vendor 或 git submodule；TypeScript 插件通过 CLI 子进程调用独立 Python 引擎。旧路线图中的 submodule 方案尚未实现。

## 2. 实际运行架构

```text
DSH 对话 / 文献页
  ├─ 18 个 sr_* 工具
  ├─ /sr/api/*、/sr/reading/*、/sr/reader/*
  └─ conversation.view 文献标签页
          │
          ▼
dsh-scientific-reading（TypeScript host + 手写 client bundle）
          │  python -m scientific_reading --data-root ...
          ▼
Scientific-Reading-for-Newbies（Python 确定性引擎）
          │
          ├─ library.sqlite
          ├─ papers/<paper_id>/
          ├─ jobs/<job_id>/
          └─ 飞书 worker（仅确认写入时联网）
```

职责边界：

- 插件负责 DSH 工具、路由、设置、页面和 CLI 参数适配。
- Python 引擎负责文献库、PDF 校验、解析、浅读、精读、飞书预览/同步和后台任务。
- 论文、PDF、解析图片、表格、HTML、SQLite、任务状态全部留在 `dataRoot`，不得提交进仓库。
- Agent 只处理必须判断的 gate；确定性步骤继续放到后台脚本，避免单篇文献入库耗时被对话阻塞。

## 3. 已完成能力

当前共注册 18 个工具：

- 下载与机构访问：`sr_setup`、`sr_scansci_status`、`sr_scansci_fetch`、`sr_scansci_login`、`sr_scansci_set_school`。
- 本地库与流水线：`sr_init`、`sr_library_check`、`sr_library_ensure`、`sr_pdf_attach`、`sr_library_list`、`sr_library_search`、`sr_parse`、`sr_quick_read`、`sr_full_read`、`sr_job_status`。
- 外部衔接：`sr_feishu_preview`、`sr_feishu_sync`、`sr_zotero_migrate`。

页面与路由已完成：

- DSH 对话栏已有【文献】标签页，能够显示列表、详情、状态和操作。
- `/sr/api/papers`、`/sr/api/paper/<id>`、`/sr/api/job/<id>` 已实测可用。
- `/sr/reading/<id>` 提供浅读笔记；`/sr/reader/<id>` 提供精读 HTML。
- 路由使用 `ctx.effect` 清理，并通过 `registerSafe` 容忍热重载时的重复注册。

## 4. 飞书当前真实状态

当前表为“科学文献阅读库 / 文献”。最终读回结果：

- 28 个字段，0 条记录；本轮没有写入任何文献。
- “阅读工作台”16 列，“文献档案”11 列，“系统维护”8 列。
- “阅读工作台”最左侧五列依次为：`🔵 标题`、`🟢 阅读状态`、`🟣 个人理解程度`、`🟡 一句话结论`、`🟠 主要结果`。
- `🟢 阅读状态` 是普通文本列，不使用彩色状态标签。
- `🟣 个人理解程度` 保留单选等级：未评估、模糊、基本理解、可复述、可应用。
- “项目”字段已删除。
- “关键图表”已改为“图表资产目录”；同步值只记录 MinerU 图片目录和表格目录，不让 AI 判断所谓关键图。
- 仓库外配置包含 18 个受管字段，`reading_status.type` 为 `text`，不含 `projects`。

飞书凭证规则必须保持：

1. `FEISHU_APP_ID`、`FEISHU_APP_SECRET` 只存在于启动 DSH 的宿主环境变量。
2. 插件设置只保存仓库外 JSON 路径，不保存或回显凭证。
3. 修改环境变量后必须重启 DSH，worker 才能继承。
4. 每篇文献先调用 `sr_feishu_preview`；只有用户针对本次写入明确确认后，才允许 `sr_feishu_sync(confirm=true)`。
5. DOI、PMID、Zotero Key 查重命中多条时，以 `ambiguous_feishu_record` 停止，不自动选记录。
6. 写入成功后必须读回所有受管字段进行比对。

最终零写入预览已通过：`preview_ready`，payload SHA-256 为 `79a60faf4a826f5c3232db9ac6608f002587d4cf33edffefccae8d058f7661ac`。

## 5. DSH 原生开发流程

### 5.1 修改插件

在插件仓库中修改 host `src/*.ts`；client 的唯一源码是 `client/client.js`。首次安装或 lockfile 变化后，从空依赖目录执行：

```powershell
npm.cmd ci --ignore-scripts --legacy-peer-deps
npm.cmd run build:ci
npm.cmd run test:offline
```

`test:offline` 包含 client 构建测试、DSH rc.7 兼容检查、workflow 自检、挂载冒烟、
飞书凭证边界和 plugin-check。`--legacy-peer-deps` 只避免 npm 自动安装完整宿主 peer 图；
所有插件直接加载的依赖仍由 lockfile 精确固定。

GitHub Actions 只运行可独立复现的 build 与 `test:offline`。`verify-live` 需要真实 DSH，
restart recovery 需要相邻 Python 引擎，所以保留为本地集成验收；Python 全量 pytest
由 `Scientific-Reading-for-Newbies/.github/workflows/ci.yml` 独立负责。

Profile Bundle 有两层验收，不能互相替代：

- 离线 CI 中的 `test:offline` 使用假 DSH CLI，验证安装命令、临时目录隔离、飞书凭证清除，
  以及配置读回零命中或多命中时必须失败；它不证明本机真实 DSH 能安装该包。
- 本机集成验收使用真实 DSH `0.1.0-rc.7`，运行：

```powershell
npm run verify:profile-bundle -- --dsh-bin "<DSH bin.js 的绝对路径>"
```

验证器在系统临时目录创建独立 `DSH_HOME`，清除子进程环境中的 `FEISHU_APP_ID` 与
`FEISHU_APP_SECRET`，以 `--offline --ignore-scripts` 安装临时 tarball，并通过
`--dump-config` 要求 `scientific-reading` 恰好出现一次；最后删除临时目录。它不会使用或
改写用户 `%USERPROFILE%\.dsh\profiles`，也不会触发真实飞书写入。验收前后应对该目录做
只读快照并确认无变化。

随后在 DSH 开发环境执行 `dev_build_plugin`、`dev_inject_plugin` 或 `dev_reload_package`。
需要重新装载 client、宿主环境变量或 package 声明时，优先完整重启 DSH，再运行：

```powershell
node scripts\verify-live.mjs
npm.cmd run verify:restart-recovery
```

### 5.2 修改 Python 引擎

当前 venv 是 editable install，修改相邻引擎仓库后无需复制包。提交前在引擎仓库运行：

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest -q
```

当前基线结果：`399 passed, 1 skipped`。

后台恢复行为验收：

```powershell
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" scripts\verify_restart_recovery.py
```

该命令使用临时数据和虚构论文，验证父进程退出后 detached worker 继续执行，并由新的 CLI
进程读回 job 与 SQLite。它验证上述 Python 运行时实际导入的引擎行为，不校验源码 commit；
在 feature worktree 验证未合并的引擎时，应先把该 worktree 的 `src` 置于 `PYTHONPATH`。

### 5.3 联调顺序

1. Python 引擎定向测试及全量测试。
2. `npm run build:ci` 与 `npm run test:offline`。
3. DSH 重载或重启。
4. `verify-live.mjs` 验证真实路由、client 注册和文献状态。
5. 涉及飞书时先做 preview；没有本次明确确认，不做 sync。

## 6. 建议的下一步

按优先级继续：

client 已纳入正式源码与构建：`client/client.js` 为规范源，生成 `lib/client.js`（已完成）。

1. **做最终表结构下的首次真实飞书写入验收**：只选一篇非敏感测试文献，preview 后取得用户明确确认，再验证 create、重复 sync 的 update/缓存行为及完整读回。当前表仍为 0 条记录，因此这项尚未完成；没有用户针对本次写入的明确确认，不执行 sync。
2. **最后再评估 TS 移植**：只迁移稳定、纯确定性的短路径；MinerU、浅读/精读和 worker 暂时继续留在 Python，避免为“原生”重写成熟逻辑。

## 7. 已知文档偏差与注意事项

- `README.md`、`docs/features.md`、`docs/roadmap.md` 和部分源码头注释仍残留“Phase 0/下一步”的旧状态描述，不能据此判断功能是否完成。
- `docs/roadmap.md` 的飞书章节仍有“在设置卡片填 App ID/Secret”的旧文字；当前实现严格使用宿主环境变量。
- 旧设计提到 git submodule，但当前没有 `.gitmodules`，也没有 vendor 引擎目录。
- `client/client.js` 是 lazy-CJS 规范源，`lib/client.js` 为生成产物；`plugin-check` 会比较两者的新鲜度。
- `legalOnly` 默认必须保持 `true`；机构密码、Cookie、验证码和 MFA 只由用户在可见浏览器中处理。
- 不要把飞书密钥、表 token、用户本地绝对路径或论文资产提交进仓库。

## 8. 当前验收快照

- 插件挂载：18 个工具、8 条路由，重复挂载测试通过。
- 飞书凭证：仅继承宿主环境变量测试通过。
- 插件健康门禁：构建、产物、client 声明和仓库边界通过。
- 插件 CI：Windows + Node 22 + Python 3.11；DSH rc.7 精确依赖闭包从 lockfile 安装，离线门禁通过。
- Profile Bundle：真实 DSH `0.1.0-rc.7` 在临时 `DSH_HOME` 中完成打包、离线安装与唯一配置读回；用户 profile 快照不变。
- DSH 上线验证：论文列表、详情、client 包、模块注册、React 桥接、库状态全部通过。
- 重启恢复：父进程退出后由新 CLI 观察到 `running → completed`，SQLite 状态读回为 `restart_probe_ready`；未直接重启当前 DSH。
- Python 引擎：399 通过、1 跳过。
- 飞书：28 字段、0 记录；三个视图列数与关键列顺序读回正确。

继续开发前先运行第 5 节的全部门禁；完成新阶段后，按默认约定合并回本地 `main`，在 `main` 上重新跑全量测试，再清理临时工作树和分支。
