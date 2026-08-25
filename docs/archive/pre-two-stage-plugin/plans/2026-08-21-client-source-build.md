# Client 正式源码与确定性构建 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将手写 `lib/client.js` 改为由规范源码确定性生成，并让本地门禁可靠拒绝缺失或过期的客户端产物。

**Architecture:** 保留当前已验证的 DSH lazy-CJS 浏览器格式，不引入 bundler。`client/client.js` 成为唯一规范源码；无依赖 Node 脚本负责 LF 规范化、临时文件写入与原子替换，并向构建和健康门禁提供同一内容比较函数。

**Tech Stack:** Node.js ESM、标准库 `fs/promises`、现有 Bash/TypeScript 构建、现有脚本式测试。

---

## 文件结构

- Create `client/client.js`：从当前 `lib/client.js` 原样迁入的规范源码。
- Recreate `lib/client.js`：由构建脚本生成的 DSH 客户端产物。
- Create `scripts/build-client.mjs`：可导入的构建、比较函数和 CLI 入口。
- Create `tests/client-build.mjs`：确定性构建与过期检测测试。
- Modify `scripts/plugin-check.mjs`：增加 client 内容新鲜度检查。
- Modify `scripts/build.sh`：host 编译后生成 client。
- Modify `package.json`：增加 client 构建、检查和测试命令。
- Modify `README.md`：说明规范源码、生成命令和门禁。

### Task 1: 建立规范源与确定性生成器

**Files:**
- Create: `client/client.js`
- Create: `scripts/build-client.mjs`
- Create: `tests/client-build.mjs`
- Modify: `scripts/build.sh`
- Modify: `package.json`
- Recreate: `lib/client.js`

- [ ] **Step 1: 写失败测试**

先创建 `tests/client-build.mjs`。测试用 `spawnSync` 执行仓库尚不存在的构建入口，要求 `--check` 成功；当前应以断言失败证明能力缺失：

```js
import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..')
const script = join(root, 'scripts', 'build-client.mjs')
const check = spawnSync(process.execPath, [script, '--check'], { cwd: root, encoding: 'utf8' })
assert.equal(check.status, 0, check.stderr || check.stdout)

const { buildClient, checkClient } = await import(pathToFileURL(script).href)
const temp = await mkdtemp(join(tmpdir(), 'sr-client-build-'))
try {
  const sourcePath = join(temp, 'client.js')
  const outputPath = join(temp, 'lib-client.js')
  await writeFile(sourcePath, 'line1\r\nline2\r\n', 'utf8')
  await buildClient({ sourcePath, outputPath })
  assert.equal(await readFile(outputPath, 'utf8'), 'line1\nline2\n')
  assert.equal(await checkClient({ sourcePath, outputPath }), true)

  await writeFile(outputPath, 'stale\n', 'utf8')
  assert.equal(await checkClient({ sourcePath, outputPath }), false)

  await buildClient({ sourcePath, outputPath })
  assert.equal(await checkClient({ sourcePath, outputPath }), true)
} finally {
  await rm(temp, { recursive: true, force: true })
}

console.log('PASS: client 确定性构建与过期检测通过')
```

- [ ] **Step 2: 运行测试，确认 RED**

Run: `node tests\client-build.mjs`

Expected: FAIL，`build-client.mjs` 不存在导致 `check.status` 不是 `0`。

- [ ] **Step 3: 迁移规范源码并实现最小生成器**

用 `git mv lib/client.js client/client.js` 保留历史，再创建 `scripts/build-client.mjs`：

```js
import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
export const defaultSourcePath = join(root, 'client', 'client.js')
export const defaultOutputPath = join(root, 'lib', 'client.js')

export function normalizeClientSource(text) {
  return text.replace(/\r\n?/g, '\n')
}

export async function checkClient({ sourcePath = defaultSourcePath, outputPath = defaultOutputPath } = {}) {
  const expected = normalizeClientSource(await readFile(sourcePath, 'utf8'))
  try {
    return await readFile(outputPath, 'utf8') === expected
  } catch (error) {
    if (error && error.code === 'ENOENT') return false
    throw error
  }
}

export async function buildClient({ sourcePath = defaultSourcePath, outputPath = defaultOutputPath } = {}) {
  const output = normalizeClientSource(await readFile(sourcePath, 'utf8'))
  await mkdir(dirname(outputPath), { recursive: true })
  const tempPath = `${outputPath}.${process.pid}.tmp`
  try {
    await writeFile(tempPath, output, 'utf8')
    await rename(tempPath, outputPath)
  } finally {
    await unlink(tempPath).catch((error) => {
      if (!error || error.code !== 'ENOENT') throw error
    })
  }
}

async function main() {
  if (process.argv.includes('--check')) {
    if (!await checkClient()) {
      console.error('client 构建产物缺失或过期：请运行 node scripts/build-client.mjs')
      process.exitCode = 1
      return
    }
    console.log('PASS: client 构建产物为最新')
    return
  }
  await buildClient()
  console.log('client/client.js → lib/client.js')
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main()
}
```

运行 `node scripts\build-client.mjs` 重新生成 `lib/client.js`。

- [ ] **Step 4: 接入正式构建入口**

在 `scripts/build.sh` 的 TypeScript 编译后增加：

```bash
echo "=== Building client/client.js → lib/client.js ==="
node scripts/build-client.mjs
```

在 `package.json` 的 scripts 中增加：

```json
"build:client": "node scripts/build-client.mjs",
"check:client": "node scripts/build-client.mjs --check",
"test:client": "node tests/client-build.mjs"
```

保留已有 `build` 与 `typecheck`。

- [ ] **Step 5: 运行 GREEN 与产物等价验证**

Run:

```powershell
node tests\client-build.mjs
node scripts\build-client.mjs --check
git diff --exit-code -- lib\client.js
```

Expected: 两个脚本均 PASS；生成后的 `lib/client.js` 与阶段开始时的运行内容一致。

- [ ] **Step 6: 提交 Task 1**

```powershell
git add client/client.js lib/client.js scripts/build-client.mjs scripts/build.sh tests/client-build.mjs package.json
git commit -m "构建：纳入客户端规范源码"
```

### Task 2: 将内容新鲜度纳入健康门禁与文档

**Files:**
- Modify: `scripts/plugin-check.mjs`
- Modify: `README.md`
- Test: `tests/client-build.mjs`

- [ ] **Step 1: 写门禁失败测试**

在 `tests/client-build.mjs` 的临时目录场景中，保留把产物写成 `stale\n` 的步骤，并在重建前明确断言比较结果为 `false`。运行测试确认现有生成器测试通过，但当前 `plugin-check.mjs` 尚未导入或调用 `checkClient`，由源码断言先形成 RED：

```js
const pluginCheck = await readFile(join(root, 'scripts', 'plugin-check.mjs'), 'utf8')
assert.match(pluginCheck, /checkClient/)
```

- [ ] **Step 2: 运行测试，确认 RED**

Run: `node tests\client-build.mjs`

Expected: FAIL，错误指出 `plugin-check.mjs` 不含 `checkClient`。

- [ ] **Step 3: 在健康门禁复用同一比较函数**

在 `scripts/plugin-check.mjs` 顶部导入：

```js
import { checkClient } from './build-client.mjs'
```

把“客户端声明一致性”扩展为：

```js
if (pkg.dsh?.client) {
  if (!pkg.exports?.['./client']) failures.push('dsh.client 声明但 exports 缺 ./client')
  try { await stat(join(root, 'lib', 'client.js')) } catch { failures.push('dsh.client 声明但 lib/client.js 不存在') }
  try {
    if (!await checkClient()) failures.push('client 构建产物缺失或过期: client/client.js → lib/client.js')
  } catch (error) {
    failures.push('client 新鲜度检查失败: ' + (error instanceof Error ? error.message : String(error)))
  }
}
```

- [ ] **Step 4: 更新 README**

在构建说明中明确：

```markdown
客户端唯一规范源码是 `client/client.js`；不要直接编辑 `lib/client.js`。修改后运行：

```powershell
node scripts\build-client.mjs
node scripts\build-client.mjs --check
```

`plugin-check.mjs` 会比较规范源码与生成产物，过期时直接失败。
```

- [ ] **Step 5: 运行阶段验证**

Run:

```powershell
node tests\client-build.mjs
node tests\harness.mjs
node tests\feishu-env-only.mjs
node scripts\plugin-check.mjs
node scripts\verify-live.mjs
git diff --check
```

Expected: 全部退出 0；挂载仍为 18 个工具、8 条路由；真实文献页 client、React 桥接与库状态验证通过。

- [ ] **Step 6: 提交 Task 2**

```powershell
git add scripts/plugin-check.mjs tests/client-build.mjs README.md
git commit -m "测试：校验客户端构建新鲜度"
```

### Task 3: 阶段审核、合并与清理

**Files:**
- Verify: all files from Tasks 1-2

- [ ] **Step 1: 规格符合性审查**

由 medium 推理 reviewer 只读检查：无 UI 行为变化、无新增运行时依赖、规范源唯一、构建确定、`--check` 与插件门禁都能识别过期产物。

- [ ] **Step 2: 代码质量审查**

规格批准后，由另一名 medium 推理 reviewer 检查 Windows 路径、原子替换、错误传播、测试隔离、构建脚本与 package scripts 一致性。

- [ ] **Step 3: 功能分支完整验证**

Run:

```powershell
node tests\client-build.mjs
node tests\harness.mjs
node tests\feishu-env-only.mjs
node scripts\plugin-check.mjs
node scripts\verify-live.mjs
git diff --check HEAD~2..HEAD
```

Expected: 全部退出 0。

- [ ] **Step 4: 合并本地 main 并复验**

按用户默认约定快进合并到本地 `main`，随后在 `main` 重跑 Step 3 的全部命令。确认通过后移除本阶段 worktree 并删除临时分支；不 push GitHub。

