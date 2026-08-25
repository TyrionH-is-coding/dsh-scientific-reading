# DSH Scientific Reading 实机缺陷修复实施计划

> 执行方式：在隔离 worktree 中按 TDD 逐项完成；每个任务单独提交。所有隔离门禁通过前，不修改用户 `web` Profile，也不中断当前 3080。

**目标：** 修复 Profile Bundle 实际启动、浅读/精读路由、文献总数与桌面布局问题，并新增真实 DSH 启动验收；通过后持久安装到 `web` Profile 并完成实机复验。

**约束：** 只做设计文档列明的最小改动；不改 Python 引擎业务、不改飞书字段、不联网下载论文、不触发真实飞书写入、不推送远端。

---

## 任务 1：统一 DSH 宿主依赖名

**文件：**

- 修改：`src/config.ts`
- 修改：`package.json`
- 修改：`package-lock.json`
- 修改：`tests/dsh-compat.mjs`
- 生成：`lib/config.js`、`lib/config.d.ts`

### 1.1 先写失败测试

在 `tests/dsh-compat.mjs` 中增加以下契约：

```js
const configSource = readFileSync(join(root, 'src', 'config.ts'), 'utf8')
assert.match(configSource, /from ['"]@deepseek-ai\/schemastery['"]/)
assert.doesNotMatch(configSource, /from ['"]schemastery['"]/)
assert.equal(manifest.peerDependencies?.['@deepseek-ai/schemastery'], '^3.18.0')
assert.equal(Object.hasOwn(manifest.peerDependencies ?? {}, 'schemastery'), false)
assert.equal(Object.hasOwn(manifest.devDependencies ?? {}, 'schemastery'), false)
```

同时从 `expectedDependencies` 与已安装包检查中移除非 scoped 的 `schemastery` 别名。

运行并确认失败：

```powershell
npm run test:compat
```

预期：旧导入名、旧 peer 或旧 dev alias 导致断言失败。

### 1.2 最小实现

```ts
import z from '@deepseek-ai/schemastery'
```

将 peer 改为 `@deepseek-ai/schemastery`，删除 dev alias `schemastery`，运行：

```powershell
npm install --package-lock-only --ignore-scripts --legacy-peer-deps
npm run build:ci
npm run test:compat
```

预期：构建与兼容契约通过，生成代码不再导入旧别名。

### 1.3 提交

```powershell
git add src/config.ts package.json package-lock.json tests/dsh-compat.mjs lib/config.js lib/config.d.ts
git commit -m "修复：统一DSH宿主配置依赖"
```

---

## 任务 2：修复浅读与精读路由

**文件：**

- 新增：`tests/reading-routes.mjs`
- 修改：`src/routes.ts`
- 修改：`scripts/verify-live.mjs`
- 修改：`package.json`
- 修改：`tests/ci-workflow.mjs`
- 生成：`lib/routes.js`、`lib/routes.d.ts`

### 2.1 建立路由回归测试

测试用临时 `dataRoot` 创建以下文件：

```text
papers/doi_10.48550_arxiv.1706.03762/reading/quick_read.md
papers/doi_10.48550_arxiv.1706.03762/reading/full/output/reader_full.html
```

使用假的 `ctx.webServer.register()` 捕获 `registerRoutes()` 注册的 handler，并用轻量 response 双对象调用：

```js
await reading.handler({ url: `/sr/reading/${paperId}`, method: 'GET' }, response)
assert.equal(response.statusCode, 200)
assert.match(response.body, /fixture quick read/)

await reader.handler({ url: `/sr/reader/${paperId}`, method: 'GET' }, response)
assert.equal(response.statusCode, 200)
assert.match(response.body, /fixture full reader/)
```

同时断言非法 ID 与缺失文件返回 404。先运行：

```powershell
npm run build:ci
node tests/reading-routes.mjs
```

预期：两个合法 URL 在旧实现下均失败。

### 2.2 最小修复

两个路由统一使用：

```ts
const id = decodeURIComponent((req.url ?? '').slice(prefix.length)).split('/').filter(Boolean)[0] ?? ''
```

不新增路由抽象。更新 `verify-live.mjs`，在已有测试论文详情通过后再请求：

```text
/sr/reading/doi_10.48550_arxiv.1706.03762
```

并要求 200 且正文非空。

### 2.3 纳入离线门禁并验证

新增脚本 `test:reading-routes`，插入 `test:offline`；同步更新 `tests/ci-workflow.mjs` 的精确脚本契约。

```powershell
npm run build:ci
npm run test:reading-routes
npm run test:offline
```

### 2.4 提交

```powershell
git add src/routes.ts lib/routes.js lib/routes.d.ts tests/reading-routes.mjs scripts/verify-live.mjs package.json tests/ci-workflow.mjs
git commit -m "修复：恢复浅读与精读页面路由"
```

---

## 任务 3：修正文献总数与桌面布局

**文件：**

- 新增：`tests/client-ui-contract.mjs`
- 修改：`client/client.js`
- 修改：`package.json`
- 修改：`tests/ci-workflow.mjs`
- 生成：`lib/client.js`

### 3.1 先锁定客户端契约

新增静态契约测试，要求源码包含：

```js
state.countLabel.textContent = '全部文献（' + state.papers.length + '）'
```

并锁定三项最小布局结构：中栏 `min-width:420px`、右栏 `width:clamp(340px,38%,500px)`、表格 `table-layout:fixed` 和 `min-width:520px`；标题/DOI 单元格必须设置完整 `title` 提示与省略显示。

先运行：

```powershell
node tests/client-ui-contract.mjs
```

预期：计数更新与布局契约均失败。

### 3.2 最小实现

- 创建左栏总数时保存到 `state.countLabel`；每次 `renderTable()` 入口同步总数。
- 左栏收窄到 160 px。
- 中栏采用 `flex:1 1 460px;min-width:420px`。
- 右栏采用 `width:clamp(340px,38%,500px)`。
- 主体允许横向滚动；表格采用固定布局与最小宽度。
- 状态/年份不换行；标题与 DOI 省略，`title` 保留完整内容。
- 状态标签补充白字、圆角、内边距与稳定行高。

不增加主题、分页或新组件抽象。

### 3.3 构建并验证

新增 `test:client-ui`，插入 `test:offline`；更新 CI 契约。

```powershell
npm run build:client
npm run test:client-ui
npm run test:client
npm run test:offline
```

### 3.4 提交

```powershell
git add client/client.js lib/client.js tests/client-ui-contract.mjs package.json tests/ci-workflow.mjs
git commit -m "修复：改善文献列表计数与桌面布局"
```

---

## 任务 4：新增真实 Profile Bundle 启动验收

**文件：**

- 新增：`scripts/verify-profile-runtime.mjs`
- 新增：`tests/profile-runtime-verifier.mjs`
- 修改：`package.json`
- 修改：`tests/ci-workflow.mjs`
- 修改：`docs/PHASE4_HANDOFF.md`（若实际交接文档名称不同，以现有 Profile Bundle 说明文件为准）

### 4.1 先写 fake DSH 失败/成功测试

fake DSH 必须覆盖：

1. `--version` 返回 `0.1.0-rc.7`；
2. `plugin --profile scientific-reading-runtime-test add <tarball> --offline --ignore-scripts`；
3. `web --profile scientific-reading-runtime-test --host 127.0.0.1 --port 0` 启动本地 HTTP server 并输出 URL；
4. success 模式提供根页、client、浅读、精读；failure 模式在 ready 前退出；
5. 捕获环境，断言临时 `DSH_HOME`/`USERPROFILE` 已清理且飞书凭证未泄漏。

先运行：

```powershell
node tests/profile-runtime-verifier.mjs
```

预期：验证器尚不存在，测试失败。

### 4.2 实现隔离启动验证器

`scripts/verify-profile-runtime.mjs --dsh-bin <绝对路径>` 执行：

1. 校验真实 DSH 版本等于 manifest 的 `testedHost`；
2. 创建受控临时目录、临时 `DSH_HOME` 和临时 `USERPROFILE`；
3. 创建默认 `scientific-reading-data` 下的浅读/精读 fixture；
4. `npm pack --json --ignore-scripts`；
5. 离线安装 tarball 到隔离 Profile；
6. 启动 DSH 到端口 0，最多等待 30 秒解析 ready URL；
7. 断言根页、client、`/sr/reading/<id>`、`/sr/reader/<id>` 均为 200 且有 marker；
8. 终止 child，验证退出并只清理自身前缀临时目录。

子进程环境中删除 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`，不访问网络或真实用户数据。

### 4.3 脚本与交接说明

新增：

```json
"test:profile-runtime": "node tests/profile-runtime-verifier.mjs",
"verify:profile-runtime": "node scripts/verify-profile-runtime.mjs"
```

fake 测试纳入 `test:offline`，真实验证器保持显式本机门禁，不在 GitHub CI 中依赖已安装 DSH。交接说明明确：`verify:profile-bundle` 仅验证配置，发布前还必须运行 `verify:profile-runtime -- --dsh-bin ...`。

### 4.4 验证与提交

```powershell
npm run test:profile-runtime
npm run test:offline
npm run build:ci
git add scripts/verify-profile-runtime.mjs tests/profile-runtime-verifier.mjs package.json tests/ci-workflow.mjs docs
git commit -m "测试：增加Profile Bundle真实启动门禁"
```

---

## 任务 5：隔离实机验收与阶段性复核

### 5.1 全量本地门禁

```powershell
npm ci --ignore-scripts --legacy-peer-deps
npm run build:ci
npm run typecheck
npm run test:offline
```

### 5.2 真实隔离 DSH 启动

先定位当前 DSH 的实际 JavaScript 入口（不用 `.cmd` 包装器），再运行：

```powershell
npm run verify:profile-bundle -- --dsh-bin <absolute-js-entry>
npm run verify:profile-runtime -- --dsh-bin <absolute-js-entry>
```

要求真实 rc.7 启动、四个 HTTP 断言通过、临时目录清理成功。

### 5.3 浏览器 QA

仅在隔离实例验证：

- 文献 tab 可见；
- “全部文献（1）”与 API 条目一致；
- 搜索、刷新、行点击和详情正常；
- 浅读/精读链接返回 200；
- 普通桌面宽度无标题/年份/DOI 字符级挤压；
- 控制台无新错误。

不点击下载、解析、浅读、精读或飞书同步按钮。

### 5.4 medium 阶段审核

按用户要求，分别进行规格一致性与代码质量审核；只修复本轮范围内的阻断问题。审核通过后提交必要修正。

---

## 任务 6：持久安装、3080 复验与收尾

### 6.1 注入前快照

记录用户 `web` Profile 的 package/lock/patch 文件与校验和，确认 Profile 当前无同名 Bundle；打包并记录本次 tarball SHA-256。

### 6.2 持久安装并重启

使用任务 5 已通过的同一 tarball：

```powershell
dsh plugin --profile web add <verified-tarball> --offline --ignore-scripts
```

随后停止当前 3080，启动真实 `web` Profile；若启动失败，恢复快照并重启原 Profile。

### 6.3 最终实机复验

```powershell
node scripts/verify-live.mjs http://127.0.0.1:3080
```

再做浏览器检查：文献 tab、总数、详情、浅读链接、布局、设置卡片与控制台。不得触发真实飞书写入。

### 6.4 最终审核、合并与清理

进行一次 medium 最终审核；通过后：

```powershell
git checkout main
git merge --ff-only <repair-branch>
npm run build:ci
npm run typecheck
npm run test:offline
git worktree remove <repair-worktree>
git branch -d <repair-branch>
```

最终报告列出：修复项、隔离启动证据、3080 实机证据、测试命令、提交与剩余限制。除非用户另行要求，不推送 GitHub。
