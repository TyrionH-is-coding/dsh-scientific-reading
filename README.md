# @dsh-external/dsh-scientific-reading

## Phase 1：两段式本地入库（本地离线实现完成）

已接入 SQLite 骨架优先返回、持久 `derived-enqueue`（题录 → Abstract agent gate → XLSX → 可选飞书）、只读 XLSX 快照、fake/配置飞书系统字段、文件夹标签和可撤销批量归类。插件只把 canonical `paper_id` 与可选配置路径交给引擎，由引擎从 SQLite 主库刷新 `metadata.json`；不会用调用方 payload 覆盖题录。Abstract 只接受 `sr_abstract_submit` 提交的 agent 翻译，不自动伪造；XLSX 只读，飞书个人字段不回写。Zotero 新流程已停用，旧字段/预览确认工具仅作为 legacy 兼容。运行 `npm.cmd run test:foundation` 可在临时 data root 完成离线验收；不联网、不写真实飞书。未提供本阶段 Profile/3080 只读探针时，验收明确输出 `not_verified`，不把它们算作门禁通过。全文获取、MinerU、全文翻译和精读页面仍不属于 Phase 1 完成范围。

`sr_ingest` 与 `POST /sr/api/library` 在本地事务完成后先返回 `paper_id` 和 `derived: pending`。派生编排产生的 `active_job_id` 及失败状态由引擎持久写入 SQLite 主库，可用 `sr_job_status` 或 `GET /sr/api/job/<job_id>` 查询；插件不等待派生完成，也不自行覆盖主库题录。

文献工作流插件（Phase 0：下载段已可用）。把 Scientific-Reading-for-Newbies 的
完整文献流水线搬进 DSH：下载 → 解析 → 入库 → 笔记。

继续在 DSH 内原生开发前，请先阅读 [`docs/handoff-dsh-native.md`](docs/handoff-dsh-native.md)；该文档记录当前实际基线、验证命令、飞书最终结构和已知旧文档偏差。

## 当前状态（Phase 0）

已注入 DSH 并热重载验证，工具：

| 工具 | 作用 |
|---|---|
| `sr_setup` | 检查/安装 scansci-pdf + 合法来源配置（默认关 Sci-Hub） |
| `sr_scansci_status` | 下载器健康 + 学校/输出目录/合法开关总览 |
| `sr_scansci_fetch` | DOI/URL → PDF 落盘 + 元数据 JSON |
| `sr_scansci_login` | 机构登录（CARSI/WebVPN/Cookie，浏览器弹出，密码不经过插件） |
| `sr_scansci_set_school` | 设置学校 |

## 构建与注入

客户端唯一规范源码是 `client/client.js`，不要直接编辑 `lib/client.js`。修改客户端后运行
`node scripts/build-client.mjs`，并以 `node scripts/build-client.mjs --check` 确认产物最新；
`plugin-check` 也会比较源码和产物，过期时失败。

当前已测试宿主基线为 `@deepseek-ai/dsh@0.1.0-rc.7`，CI 使用 Node 22、Python 3.11
和 `package-lock.json` 中的精确插件依赖。首次安装或 lockfile 更新后可在空依赖目录复现：

```powershell
npm.cmd ci --ignore-scripts --legacy-peer-deps
npm.cmd run build:ci
npm.cmd run test:offline
```

`--legacy-peer-deps` 是有意的：插件 CI 只安装编译与挂载冒烟实际加载的最小闭包，
其余 peer 由真实 DSH 宿主提供；不会把接近 200 个宿主包复制进插件开发依赖。

## Profile Bundle

当前插件可作为 Profile Bundle 打包并安装到指定 DSH profile：

```powershell
npm run build:ci
npm pack --ignore-scripts
dsh plugin --profile web add .\dsh-external-dsh-scientific-reading-0.0.1.tgz --offline --ignore-scripts
dsh --profile web --dump-config
```

交付前还要用同一个真实 DSH 入口完成两项隔离验收：

```powershell
npm run verify:profile-bundle -- --dsh-bin "<DSH bin.js 的绝对路径>"
npm run verify:profile-runtime -- --dsh-bin "<DSH bin.js 的绝对路径>"
```

前者验证 tarball 安装与配置唯一性，后者会复用已安装的 scientific-reading Python 引擎，
启动一个临时 Profile，并实际请求根页、client、论文列表/详情、浅读与精读页面。两项都只
使用系统临时目录，不修改用户 Profile，也不会触发飞书写入。

`web` 与 `headless` 是相互独立的 profile；安装到其中一个不会激活另一个。包当前仍保持
`private: true`，用于本地打包交付而非发布到 npm。Profile 激活不授权业务写入；Phase 1
canonical 入库由引擎持久派生管线处理飞书，不走旧 preview/confirm 入口。

如果同名插件此前通过 `dev_inject_plugin` 注册，开发注入会在宿主启动时覆盖 tarball。
转为持久安装前必须先从 super-injector 注销该开发目录，再执行一次 `plugin remove` 后重新
`plugin add <tarball>`；启动后应确认 profile 下的包目录不是指向仓库的 junction。

```powershell
# 注入/重载（DSH dev 工具）
dev_build_plugin / dev_inject_plugin / dev_reload_package
```

## 垫片说明

`scripts/scansci_wrap.py` 修复 scansci-pdf 1.9.0 的三个问题（仅本插件调用路径生效）：

1. 未配置机构时跳过浏览器登录（防空 URL 崩溃）；
2. arXiv 成功返回补 `path` 键（原返回 `file`，fetcher 读 `path` 导致 PDF 永不认领）；
3. 强制 UTF-8 输出（中文 Windows 控制台 GBK 报错）。

## Phase 2/3（未在本阶段完成）

Phase 2 文献页与 Phase 3 全文精读/飞书真实写入/Zotero 迁移仍是后续验收范围。当前保留的路由、旧预览/confirm 及迁移入口只用于 legacy 兼容，不代表这些阶段已完成。

## Legacy/internal 兼容入口

以下能力保留用于旧数据、迁移或后续阶段兼容，不属于 Phase 1 canonical 默认流程：
`sr_init`、`sr_library_check`、`sr_library_ensure`、`sr_parse`、`sr_quick_read`、
`sr_full_read`、`sr_feishu_preview`、`sr_feishu_sync(confirm=true)`、
`sr_feishu_resync` 与 `sr_zotero_migrate`。其中 quick-read、全文精读、旧飞书
preview/confirm 和 Zotero 迁移均不代表 Phase 2/3 已完成。

## 飞书凭证

设置卡片只保存仓库外 `feishu-config-v1` JSON 路径。App ID 与 App Secret 不进入
插件设置或 JSON；请在启动 DSH 的宿主环境中设置后重启 DSH：

```ini
FEISHU_APP_ID=你的AppID
FEISHU_APP_SECRET=你的AppSecret
```

新流程由引擎持久派生管线负责飞书同步：插件仅向 `derived-enqueue` 传递仓库外配置路径，首次入库不执行并发 resync。
`sr_feishu_preview`/`sr_feishu_sync(confirm=true)` 仅保留为 legacy/internal 兼容入口，不属于本阶段新流程。

从旧版升级时，如果曾在设置卡片填写过 `feishuAppId` 或 `feishuAppSecret`，请在
DSH 停止后从 `scientific-reading` 设置分节删除这两个旧键。新版本不会读取它们；
也不会自动改写用户设置文件。当前配置从未填写过这两个字段时无需处理。

## 验证

```powershell
node tests\ci-workflow.mjs       # CI 只能执行离线门禁
node tests\dsh-compat.mjs        # rc.7 兼容契约与安装版本
node scripts\plugin-check.mjs   # 插件健康门禁（构建/产物/边界）
node tests\feishu-env-only.mjs  # 飞书凭证仅继承宿主环境
node tests\harness.mjs          # 挂载冒烟（工具/路由注册 + 重复挂载容忍）
node scripts\verify-live.mjs    # 上线验证（路由/文献页 client/库状态）
```

GitHub Actions 只运行构建与上述离线门禁。`verify-live.mjs` 和
`verify:restart-recovery` 依赖真实 DSH 或相邻 Python 引擎，继续作为本地集成验收；
Python 全量测试由引擎仓库自己的 workflow 负责。

## 路线图

见 `docs/roadmap.md`：Phase 0 下载段 ✅ → Phase 1 本地文献库与两段式派生管线（离线实现完成，Profile/3080 未验证）
→ Phase 2 【文献】标签页（未完成）→ Phase 3 飞书真实写入/精读/迁移（未完成）。
