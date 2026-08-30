# 设置页与高校认证重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` task-by-task；每项按 TDD 红—绿—重构执行。

**Goal:** 把“设置与状态”重做为面向普通用户的高校选择、WebVPN 登录状态、MinerU 和文献库状态页；高校列表来自 ScanSci，认证会话可持久复用且只在过期时提示重新认证。

**Architecture:** 插件通过自带 `scansci_wrap.py` 调用 ScanSci Python API，避免解析 Rich 文本；DSH 设置存储只保存学校选择，ScanSci 的持久浏览器 profile 继续保存认证 cookie。浏览器页面只显示用户能理解和操作的状态，技术路径留在内部配置和诊断日志中。所有 PDF 获取固定合法来源。

**Tech Stack:** TypeScript、Cordis settings/webServer、纯 DOM 客户端、Python、ScanSci 1.9、Node 合同测试。

---

### Task 1: 建立隔离基线

**Files:**
- Read: `docs/superpowers/specs/2026-08-30-settings-institution-auth-redesign.md`
- Read: `docs/superpowers/specs/2026-08-30-paper-review-child-session-design.md`
- Create: `.worktrees/settings-review-mvp`

- [ ] 检测当前是否已在 worktree、确认 `.worktrees` 被忽略，并从当前 `HEAD` 创建 `feature/settings-review-mvp`。
- [ ] 将主工作树现有 tracked diff 和本次需要的未跟踪源码/测试复制到隔离 worktree；不移动、不清理主工作树。
- [ ] 运行 `npm.cmd ci --ignore-scripts --legacy-peer-deps`、`npm.cmd run build:ci`、相关 Node/Python 测试，记录基线。
- [ ] 如果基线失败，只修复与复制/依赖有关的问题；产品测试失败则先报告，不掩盖成新功能结果。

### Task 2: 为 ScanSci 增加结构化高校与会话适配

**Files:**
- Modify: `scripts/scansci_wrap.py`
- Modify: `src/cli.ts`
- Create: `tests/scansci-institution-adapter.mjs`

- [ ] 先写失败测试：包装器 `schools-json` 返回稳定数组，每项包含学校显示名和 ScanSci 登录能力；`session-status-json` 只返回 `none|valid|expired|unreachable`；任何输出不含 cookie/profile 内容。
- [ ] 运行 `node tests\scansci-institution-adapter.mjs`，确认因命令不存在失败。
- [ ] 在 `scansci_wrap.py` 内部调用 `scansci_pdf.schools.list_schools()` 和 `sources.instsci.session_status(config)`，JSON 输出；不维护第二份高校名单。
- [ ] 在 `src/cli.ts` 增加 `listScansciSchools()`、`readScansciSessionStatus()` 和结构化类型，固定使用包装器 Python。
- [ ] 运行适配测试和 `npm.cmd run typecheck`。
- [ ] 中文提交：`功能：接入高校列表与认证会话状态`。

### Task 3: 固定合法下载配置并保存学校选择

**Files:**
- Modify: `src/cli.ts`
- Modify: `src/config.ts`
- Modify: `src/settings.ts`
- Modify: `tests/mineru-secret-boundary.mjs`
- Create: `tests/institution-settings.mjs`

- [ ] 写失败测试：`ensureScansciConfig()` 无论旧设置如何都写入 `download_strategy=legal_only`、`scihub_enabled=false`；高校更新通过 `ctx.settings.update()` 持久化。
- [ ] 运行测试确认当前 `legalOnly=false` 路径失败。
- [ ] 从用户可配置 schema 和插件设置卡移除 `legalOnly`、`loginType`、Python/exe/profile/path 等普通入口；保留代码内部兼容默认值，不破坏旧 cordis 配置启动。
- [ ] 学校更新只接受 ScanSci 列表中的精确名称；保存后同步 ScanSci config，并自动选择 ScanSci 对应认证方式。
- [ ] 运行设置、兼容和安全边界测试。
- [ ] 中文提交：`安全：固定合法文献下载来源`。

### Task 4: 实现高校认证 HTTP 状态机

**Files:**
- Modify: `src/status_routes.ts`
- Modify: `src/index.ts`
- Create: `tests/institution-auth-routes.mjs`

- [ ] 写失败路由测试：
  - `GET /sr/api/settings/institutions` 返回结构化高校列表；
  - `POST /sr/api/settings/institution` 保存学校；
  - `POST /sr/api/settings/institution/login` 一次只启动一个登录任务；
  - `GET /sr/api/settings/institution/login` 返回任务状态；
  - 所有写请求要求同源与 CSRF；
  - 返回体不泄露路径、cookie 或命令行。
- [ ] 运行 `node tests\institution-auth-routes.mjs` 确认失败。
- [ ] 实现状态映射：`school_required`、`login_required`、`waiting_user`、`checking`、`connected`、`reauth_required`、`unreachable`、`failed`。
- [ ] 登录调用 ScanSci 现有 `login`，使用其持久浏览器 profile；登录结束后再次读取真实 session status，只有 `valid` 映射为 `connected`。
- [ ] 重复登录请求复用正在运行的任务，不并发弹多个浏览器。
- [ ] 运行路由测试、`tests/settings-status-routes.mjs` 和 typecheck。
- [ ] 中文提交：`功能：加入高校认证状态与重新登录`。

### Task 5: 重做“设置与状态”页面

**Files:**
- Modify: `client/client.js`
- Modify: `tests/client-ui-contract.mjs`
- Create: `tests/client-institution-settings.mjs`

- [ ] 写失败 UI 合同：页面包含学校搜索/选择、`登录高校 WebVPN` 或 `重新认证`、认证状态、MinerU Key、文献库状态；不存在 Python、可执行文件、profile、登录协议、合法来源开关。
- [ ] 运行两个客户端测试确认失败。
- [ ] 用现有色彩和 DOM 结构实现四个简单区块：高校访问、PDF 获取、MinerU 解析、文献库；取消泛化技术状态卡和全局“重新检测全部”。
- [ ] 状态文案只使用用户语义：“未选择高校”“需要登录”“等待你在浏览器完成登录”“已连接”“登录已过期，需要重新认证”“暂时无法确认”。
- [ ] 登录按钮轮询任务，卸载时取消定时器/请求；高校搜索只过滤后端列表。
- [ ] 移除普通插件设置页的字段表单，不在普通会话显示文献设置入口。
- [ ] 运行客户端合同、构建和离线回归。
- [ ] 中文提交：`界面：重做高校认证与设置状态页`。

### Task 6: 真实验收

**Files:**
- Modify: `docs/superpowers/plans/2026-08-30-settings-institution-auth-redesign.md`（只追加执行记录）

- [ ] 用本机 ScanSci 读取高校列表并核对非空、中文名称正常、无重复主键。
- [ ] 在干净测试数据根选择一所学校，验证配置落盘但 UI/日志不泄露 profile 内容。
- [ ] 启动一次可见登录，人工完成后验证 cookie profile 在 DSH 重启后仍被判为 `connected`；若真实账号环境无法完成，明确记录未完成，不能声称通过。
- [ ] 人为使用过期/空 profile 验证 `reauth_required` 或 `login_required` 及重新认证按钮。
- [ ] 运行 `npm.cmd test`；检查 `git diff --check` 与工作树范围。
