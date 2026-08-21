# DSH 原生开发交接

> 交接日期：2026-08-21  
> 用途：从当前可运行版本继续在 DSH 内原生开发。本文记录的是实际代码、运行环境与实测结果；旧文档中的 Phase 标签若与本文冲突，以本文和代码为准。

## 1. 当前基线

| 项目 | 当前状态 |
|---|---|
| DSH 插件仓库 | `dsh-scientific-reading`，实现基线 `1cbf8d2`，分支 `main` |
| Python 引擎仓库 | `Scientific-Reading-for-Newbies`，基线 `8f57ed6`，分支 `main` |
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

在插件仓库中修改 `src/*.ts`；当前文献页是例外，直接维护 `lib/client.js`。构建 host：

```powershell
node "D:\Vibe Coding\_tsc\node_modules\typescript\lib\tsc.js" -p tsconfig.json
```

本地门禁：

```powershell
node tests\harness.mjs
node tests\feishu-env-only.mjs
node scripts\plugin-check.mjs
```

随后在 DSH 开发环境执行 `dev_build_plugin`、`dev_inject_plugin` 或 `dev_reload_package`。需要重新装载 client、宿主环境变量或 package 声明时，优先完整重启 DSH，再运行：

```powershell
node scripts\verify-live.mjs
```

### 5.2 修改 Python 引擎

当前 venv 是 editable install，修改相邻引擎仓库后无需复制包。提交前在引擎仓库运行：

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest -q
```

当前基线结果：`395 passed, 1 skipped`。

### 5.3 联调顺序

1. Python 引擎定向测试及全量测试。
2. TypeScript 构建与三个本地插件门禁。
3. DSH 重载或重启。
4. `verify-live.mjs` 验证真实路由、client 注册和文献状态。
5. 涉及飞书时先做 preview；没有本次明确确认，不做 sync。

## 6. 建议的下一步

按优先级继续：

1. **把 client 纳入正式源码与构建**：目前只有手写 `lib/client.js`，没有对应的 `src/client`；这是继续做原生 UI 前最值得先还的工程债。
2. **完成重启恢复演练**：在解析或浅读任务运行中重启 DSH，确认独立 worker 继续执行，重启后 `sr_job_status` 和 SQLite 状态能够恢复。
3. **做最终表结构下的首次真实飞书写入验收**：只选一篇非敏感测试文献，preview 后取得用户明确确认，再验证 create、重复 sync 的 update/缓存行为及完整读回。当前表仍为 0 条记录，因此这项尚未完成。
4. **补 CI 与版本锁定**：至少自动运行 TypeScript 构建、harness、凭证边界测试和 Python 全量测试；再明确 DSH 兼容版本。
5. **最后再评估 TS 移植**：只迁移稳定、纯确定性的短路径；MinerU、浅读/精读和 worker 暂时继续留在 Python，避免为“原生”重写成熟逻辑。

## 7. 已知文档偏差与注意事项

- `README.md`、`docs/features.md`、`docs/roadmap.md` 和部分源码头注释仍残留“Phase 0/下一步”的旧状态描述，不能据此判断功能是否完成。
- `docs/roadmap.md` 的飞书章节仍有“在设置卡片填 App ID/Secret”的旧文字；当前实现严格使用宿主环境变量。
- 旧设计提到 git submodule，但当前没有 `.gitmodules`，也没有 vendor 引擎目录。
- `lib/client.js` 是手写 lazy-CJS bundle；`plugin-check` 能检查它存在和注册契约，但不能检查其源码新鲜度。
- `legalOnly` 默认必须保持 `true`；机构密码、Cookie、验证码和 MFA 只由用户在可见浏览器中处理。
- 不要把飞书密钥、表 token、用户本地绝对路径或论文资产提交进仓库。

## 8. 当前验收快照

- 插件挂载：18 个工具、8 条路由，重复挂载测试通过。
- 飞书凭证：仅继承宿主环境变量测试通过。
- 插件健康门禁：构建、产物、client 声明和仓库边界通过。
- DSH 上线验证：论文列表、详情、client 包、模块注册、React 桥接、库状态全部通过。
- Python 引擎：395 通过、1 跳过。
- 飞书：28 字段、0 记录；三个视图列数与关键列顺序读回正确。

继续开发前先运行第 5 节的全部门禁；完成新阶段后，按默认约定合并回本地 `main`，在 `main` 上重新跑全量测试，再清理临时工作树和分支。
