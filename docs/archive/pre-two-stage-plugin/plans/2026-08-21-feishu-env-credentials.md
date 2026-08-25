# 飞书凭证仅使用宿主环境变量 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除飞书凭证来源矛盾，保证同步只继承 DSH 宿主环境变量且不会把凭证写入插件设置。

**Architecture:** 保留现有 `runCommand()` 的宿主环境继承机制，删除 `engineFeishuSync()` 的设置值覆盖和对应 schema/UI 字段。用临时 Python 模块模拟引擎边界，验证旧设置哨兵不能覆盖宿主环境哨兵；客户端 bundle 作为唯一现存实现纳入版本控制。

**Tech Stack:** TypeScript、Node.js ESM、Python（仅本地测试夹具）、Schemastery、Git

---

### Task 1: 固化凭证来源回归测试

**Files:**
- Create: `tests/feishu-env-only.mjs`

- [ ] **Step 1: 写入失败测试**

测试创建临时 `scientific_reading/__main__.py`，让 `engineFeishuSync()` 调用该模块并只返回环境变量是否来自宿主哨兵。传入运行时旧字段 `feishuAppId=settings-app-id` 与 `feishuAppSecret=settings-secret`，同时把宿主环境设为 `host-app-id` 与 `host-secret`；断言结果必须是宿主值，并断言 `Config.toJSON()` 不包含旧字段。

- [ ] **Step 2: 构建并确认测试按预期失败**

Run:

```powershell
node "D:\Vibe Coding\dsh\dsh-codex\node_modules\typescript\bin\tsc" -p tsconfig.json
node tests\feishu-env-only.mjs
```

Expected: FAIL，指出当前同步仍读取 `settings-app-id` 或 schema 仍含旧字段。

### Task 2: 删除设置凭证链路

**Files:**
- Modify: `src/config.ts`
- Modify: `src/cli.ts`

- [ ] **Step 1: 删除配置字段**

从 `Config` interface 与 schema 删除：

```ts
feishuAppId: string
feishuAppSecret: string
```

- [ ] **Step 2: 删除同步时的环境覆盖**

把 `engineFeishuSync()` 调用收敛为：

```ts
const r = await runEngine(config, [
  'feishu-sync', '--metadata', metadataPath,
  '--config', cfg, '--confirm-write',
])
```

注释明确 worker 自然继承 DSH 宿主环境变量。

- [ ] **Step 3: 构建并确认回归测试通过**

Run:

```powershell
node "D:\Vibe Coding\dsh\dsh-codex\node_modules\typescript\bin\tsc" -p tsconfig.json
node tests\feishu-env-only.mjs
```

Expected: PASS。

### Task 3: 修复设置卡片可复现性

**Files:**
- Modify: `.gitignore`
- Modify and track: `lib/client.js`

- [ ] **Step 1: 删除客户端凭证字段**

从 `SR_FIELDS` 删除 `feishuAppId`、`feishuAppSecret` 两行，保留 `feishuConfig` 路径字段。

- [ ] **Step 2: 仅纳入客户端 bundle**

把 `.gitignore` 中的 `lib/` 改为：

```gitignore
lib/*
!lib/client.js
```

这样服务端构建产物仍被忽略，但干净克隆可获得唯一的客户端实现。

- [ ] **Step 3: 扩展回归测试**

在 `tests/feishu-env-only.mjs` 读取 `lib/client.js`，断言不包含 `feishuAppId` 或 `feishuAppSecret`。

### Task 4: 同步文档与现有测试夹具

**Files:**
- Modify: `README.md`
- Modify: `docs/design.md`
- Modify: `docs/roadmap.md`
- Modify: `src/library_tools.ts`
- Modify: `tests/harness.mjs`

- [ ] **Step 1: 修正文档与工具说明**

统一说明：凭证只来自 DSH 宿主环境变量；设置后必须重启宿主；配置 JSON 不含凭证；真实同步仍需 preview 和逐篇确认。

- [ ] **Step 2: 更新挂载测试配置和工具清单**

给测试配置补 `feishuConfig: ''`，并把当前已经注册的 `sr_full_read`、`sr_feishu_preview`、`sr_feishu_sync`、`sr_zotero_migrate` 加入 `expectedTools`，防止新工具漏注册却仍假通过。

### Task 5: 完整验证与提交

**Files:**
- Verify all changed files

- [ ] **Step 1: 运行完整验证**

Run:

```powershell
node "D:\Vibe Coding\dsh\dsh-codex\node_modules\typescript\bin\tsc" -p tsconfig.json --noEmit
node "D:\Vibe Coding\dsh\dsh-codex\node_modules\typescript\bin\tsc" -p tsconfig.json
node tests\feishu-env-only.mjs
node tests\harness.mjs
node scripts\plugin-check.mjs
```

Expected: 全部退出码为 0，无真实网络或飞书写入。

- [ ] **Step 2: 检查差异与凭证泄漏**

Run:

```powershell
git diff --check
git diff --stat
git grep -n "settings-secret\|host-secret"
```

Expected: `git diff --check` 通过；哨兵字符串只存在于测试；无真实凭证。

- [ ] **Step 3: 中文提交**

```powershell
git add .gitignore README.md docs src tests lib/client.js
git commit -m "修复：飞书凭证仅继承宿主环境变量"
```
