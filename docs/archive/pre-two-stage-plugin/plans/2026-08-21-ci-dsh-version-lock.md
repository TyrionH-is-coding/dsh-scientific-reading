# 插件 CI 与 DSH 版本锁定 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用精确 npm 依赖、lockfile 和 Windows GitHub Actions 固定 DSH rc.7 插件测试基线，并自动运行现有离线门禁。

**Architecture:** 插件独立安装 npm 公开包，不引入 DSH 源码或 Python 引擎 submodule。一个 Node 测试核对兼容契约与安装版本；CI 只执行可在空 runner 上完成的编译和离线测试，跨仓恢复与真实 DSH 读回继续留作本地集成验收。

**Tech Stack:** Node 22、npm lockfile v3、TypeScript 5.9.3、Python 3.11、GitHub Actions Windows runner。

---

### Task 1: 用测试固定兼容契约

**Files:**
- Create: `tests/dsh-compat.mjs`
- Modify: `package.json`

- [ ] **Step 1: 写 RED 测试**

创建 `tests/dsh-compat.mjs`，读取根 `package.json`，要求：

- `dshCompatibility.testedHost === "0.1.0-rc.7"`；
- Node/Python 基线分别为字符串 `22` / `3.11`；
- `dsh-tools`、`dsh-llm`、`dsh-scope`、`dsh-session`、`dsh-settings`、`dsh-timeout` 的 devDependency 都精确为 `0.1.0-rc.7`；
- `@deepseek-ai/cordis` / `schemastery` 与两个 npm alias 精确一致；
- 安装后从各 package 的 `package.json` 读回同样版本。

测试不得访问网络或 DSH 用户配置。

- [ ] **Step 2: 运行 RED**

Run:

```powershell
node tests\dsh-compat.mjs
```

Expected: FAIL，原因是 `dshCompatibility` 和精确 devDependency 尚不存在。

- [ ] **Step 3: 最小修改 package.json**

增加兼容契约、精确 devDependency、npm alias 和脚本：

```json
"build:ci": "tsc -p tsconfig.json && node scripts/build-client.mjs",
"test:compat": "node tests/dsh-compat.mjs",
"test:offline": "node tests/client-build.mjs && node tests/dsh-compat.mjs && node tests/harness.mjs && node tests/feishu-env-only.mjs && node scripts/plugin-check.mjs"
```

现有 peer range 不改。

- [ ] **Step 4: 生成 lockfile 并运行 GREEN**

Run:

```powershell
npm.cmd install --package-lock-only --ignore-scripts --legacy-peer-deps
npm.cmd ci --ignore-scripts --legacy-peer-deps
npm.cmd run build:ci
npm.cmd run test:offline
```

Expected: 全部退出 0；TypeScript 产物与 client 产物新鲜。

### Task 2: 增加 Windows CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: 写 workflow**

在 push 与 pull request 上使用：

```yaml
runs-on: windows-latest
node-version: "22"
python-version: "3.11"
```

依次运行 `npm ci --ignore-scripts --legacy-peer-deps`、`npm run build:ci`、`npm run test:offline`。不得运行 live、restart recovery、下载、MinerU 或飞书 sync。

- [ ] **Step 2: 机械检查 workflow**

用测试或小型标准库脚本断言 workflow 包含上述 runner、版本和三个命令，且不包含被禁止的命令；避免只靠目视检查。

- [ ] **Step 3: 本地复跑 CI 核心**

从干净安装状态执行 Task 1 Step 4 的四个命令并运行 `git diff --check`。

### Task 3: 文档与阶段验收

**Files:**
- Modify: `README.md`
- Modify: `docs/roadmap.md`
- Modify: `docs/handoff-dsh-native.md`

- [ ] **Step 1: 更新真实状态**

记录：

- 已测试宿主 `@deepseek-ai/dsh@0.1.0-rc.7`；
- CI 覆盖 TypeScript/client build、compat、harness、凭证边界和 plugin-check；
- Python 全量测试由引擎仓库 workflow 负责；
- `verify-live` 与 restart recovery 是本地集成门禁，不在无状态 CI 中运行。

把 roadmap 的“CI 冒烟 + 钉 DSH 版本”标为完成。首次真实飞书写入仍需用户针对本次明确确认，不改变优先级和安全规则。

- [ ] **Step 2: 完整验证**

Run:

```powershell
npm.cmd ci --ignore-scripts --legacy-peer-deps
npm.cmd run build:ci
npm.cmd run test:offline
npm.cmd run verify:restart-recovery
node scripts\verify-live.mjs
git diff --check
```

Expected: 全部退出 0；真实服务仍为 18 个工具、8 条路由，测试论文状态仍为 `quick_read_ready`。

### Task 4: 审核、合并与清理

- [ ] **Step 1: medium 规格审查**

确认精确版本、alias、lockfile、workflow 范围和文档边界符合设计，没有把 local integration 冒充 CI。

- [ ] **Step 2: medium 代码质量审查**

检查 Windows shell、npm 缓存/安装可复现性、package export 读取、测试错误信息、workflow 权限与最小化。

- [ ] **Step 3: 本地合并与 main 复验**

快进合并到插件本地 `main`，重跑完整门禁，删除 worktree 和临时分支；不 push GitHub。
