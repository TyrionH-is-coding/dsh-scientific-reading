# DSH Profile Bundle Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有插件补成可独立打包、可由 DSH Profile Bundle 安装，并能在隔离 profile 中证明唯一激活的交付物。

**Architecture:** 用一个最小 `cordis.patch.yml` 定义 Bundle 层；用 Node 标准库测试 manifest、patch 和 npm dry-run 包清单；再用独立验证器在临时 `DSH_HOME` 中执行真实 tarball 安装和 `--dump-config`。CI 只运行无网络、无业务写入的离线测试，真实 rc.7 激活保留为本地集成门禁。

**Tech Stack:** Node.js 22 ESM、npm lockfile、DSH `0.1.0-rc.7`、pnpm 11、GitHub Actions Windows、PowerShell。

---

## 文件职责

- `cordis.patch.yml`：Profile Bundle 唯一插件行。
- `tests/bundle-contract.mjs`：manifest 与 patch 的静态契约。
- `tests/package-contents.mjs`：消费者可见 npm dry-run 包清单。
- `scripts/verify-profile-bundle.mjs`：临时 home/profile 的真实安装与配置读回。
- `tests/profile-bundle-verifier.mjs`：用假 DSH CLI 验证命令、隔离、清理和零/多命中失败。
- `package.json`：Bundle 声明、精确打包范围和验证命令。
- `tests/ci-workflow.mjs`：继续锁死 CI 允许执行的离线命令链。
- `README.md`、`docs/roadmap.md`、`docs/handoff-dsh-native.md`：安装、验收与兼容边界。

### Task 1: 建立 Bundle manifest/patch 契约

**Files:**
- Create: `cordis.patch.yml`
- Create: `tests/bundle-contract.mjs`
- Modify: `package.json`

- [ ] **Step 1: 先写失败的契约测试**

创建 `tests/bundle-contract.mjs`，完整行为如下：

```js
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))
const patchPath = join(root, 'cordis.patch.yml')

assert.equal(pkg.dsh?.bundle?.patch, './cordis.patch.yml')
assert.equal(pkg.exports?.['./cordis.patch.yml'], './cordis.patch.yml')
assert.ok(pkg.files?.includes('cordis.patch.yml'))
assert.ok(existsSync(patchPath), 'cordis.patch.yml 必须存在')

const patch = readFileSync(patchPath, 'utf8').replaceAll('\r\n', '\n')
assert.equal((patch.match(/^\s*- id:/gm) ?? []).length, 1)
assert.match(patch, /^\s*- id: scientific-reading$/m)
assert.match(patch, /^\s*name: '@dsh-external\/dsh-scientific-reading'$/m)
assert.doesNotMatch(patch, /(?:[A-Za-z]:[\\/]|\/Users\/|\\Users\\|\.\.[\\/])/)

console.log('PASS: Profile Bundle manifest 与 patch 契约通过')
```

- [ ] **Step 2: 运行测试并确认因声明缺失而失败**

Run: `node tests/bundle-contract.mjs`

Expected: FAIL at `pkg.dsh?.bundle?.patch` because the current manifest has no bundle declaration.

- [ ] **Step 3: 添加最小 patch 与 manifest 声明**

创建：

```yaml
# dsh bundle patch: insert the scientific-reading plugin into one profile layer.
- insert:
    - id: scientific-reading
      name: '@dsh-external/dsh-scientific-reading'
```

在 `package.json` 中添加：

```json
"exports": {
  ".": { "types": "./lib/types/index.d.ts", "default": "./lib/index.js" },
  "./client": { "types": "./lib/types/client/index.d.ts", "default": "./lib/client.js" },
  "./cordis.patch.yml": "./cordis.patch.yml",
  "./package.json": "./package.json"
},
"files": [
  "lib",
  "scripts",
  "cordis.patch.yml"
],
"dsh": {
  "bundle": { "patch": "./cordis.patch.yml" },
  "client": {
    "inject": [
      "@deepseek-ai/dsh-client-runtime",
      "@deepseek-ai/dsh-client-ui-slots"
    ],
    "platform": "web"
  }
}
```

保持其他字段原样，并增加：

```json
"test:bundle": "node tests/bundle-contract.mjs"
```

- [ ] **Step 4: 运行契约与既有兼容测试**

Run: `npm run test:bundle && npm run test:compat`

Expected: both print `PASS` and exit 0.

- [ ] **Step 5: 提交 Task 1**

```powershell
git add -- cordis.patch.yml tests/bundle-contract.mjs package.json
git commit -m "功能：增加Profile Bundle契约"
```

### Task 2: 锁定消费者实际收到的包内容

**Files:**
- Create: `tests/package-contents.mjs`
- Modify: `package.json`
- Modify: `tests/ci-workflow.mjs`

- [ ] **Step 1: 先写失败的 dry-run 包清单测试**

创建 `tests/package-contents.mjs`：

```js
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'))
const before = new Set(readdirSync(root).filter((name) => name.endsWith('.tgz')))
const result = spawnSync(
  'npm',
  ['pack', '--dry-run', '--json', '--ignore-scripts'],
  { cwd: root, encoding: 'utf8', shell: process.platform === 'win32' },
)
assert.equal(result.status, 0, result.stderr)
const report = JSON.parse(result.stdout)[0]
const files = report.files.map((entry) => entry.path.replaceAll('\\', '/'))
const after = new Set(readdirSync(root).filter((name) => name.endsWith('.tgz')))

for (const required of [
  'README.md',
  'package.json',
  'cordis.patch.yml',
  'lib/index.js',
  'lib/client.js',
  'lib/types/index.d.ts',
  'scripts/scansci_wrap.py',
]) assert.ok(files.includes(required), `npm 包缺少 ${required}`)

const referencedFiles = [pkg.main, pkg.types]
for (const value of Object.values(pkg.exports)) {
  if (typeof value === 'string') referencedFiles.push(value)
  else referencedFiles.push(value.default, value.types)
}
for (const reference of referencedFiles.filter(Boolean)) {
  const path = reference.replace(/^\.\//, '')
  assert.ok(files.includes(path), `manifest 指向未打包文件 ${path}`)
}

for (const path of files) {
  assert.ok(
    !path.startsWith('tests/') &&
    !path.startsWith('docs/') &&
    !path.startsWith('src/') &&
    !path.startsWith('client/'),
    `npm 包误含开发文件 ${path}`,
  )
  if (path.startsWith('scripts/')) assert.equal(path, 'scripts/scansci_wrap.py')
  assert.doesNotMatch(path.toLowerCase(), /\.(?:pdf|tif|tiff)$/)
}
assert.deepEqual(after, before, 'dry-run 不得创建 tarball')
console.log(`PASS: npm dry-run 包清单通过（${files.length} 个文件）`)
```

- [ ] **Step 2: 运行测试并确认因开发脚本被打包而失败**

Run: `node tests/package-contents.mjs`

Expected: FAIL because current `files: ["scripts"]` includes a non-runtime helper and
`exports["./client"].types` points to the absent `lib/types/client/index.d.ts`.

- [ ] **Step 3: 收窄 files 并接入离线门禁**

把 `package.json.files` 改为：

```json
"files": [
  "lib",
  "scripts/scansci_wrap.py",
  "cordis.patch.yml"
]
```

同时把不存在的 client 类型声明从导出中移除；client 默认入口不变：

```json
"./client": { "default": "./lib/client.js" }
```

增加：

```json
"test:package": "node tests/package-contents.mjs"
```

把 `test:offline` 更新为下面这条完整且唯一允许的链：

```json
"test:offline": "node tests/client-build.mjs && node tests/dsh-compat.mjs && node tests/bundle-contract.mjs && node tests/package-contents.mjs && node tests/ci-workflow.mjs && node tests/harness.mjs && node tests/feishu-env-only.mjs && node scripts/plugin-check.mjs"
```

同步更新 `tests/ci-workflow.mjs` 对 `manifest.scripts['test:offline']` 的精确期望字符串；workflow 的 `run` allowlist 不变。

- [ ] **Step 4: 运行包清单与完整离线门禁**

Run: `npm run test:package && npm run test:offline`

Expected: package list prints `PASS`; offline gate reports 18 tools, 8 routes, and all tests exit 0.

- [ ] **Step 5: 提交 Task 2**

```powershell
git add -- tests/package-contents.mjs tests/ci-workflow.mjs package.json
git commit -m "测试：锁定插件发布包内容"
```

### Task 3: 实现隔离 profile 激活验证器

**Files:**
- Create: `scripts/verify-profile-bundle.mjs`
- Create: `tests/profile-bundle-verifier.mjs`
- Modify: `package.json`
- Modify: `tests/ci-workflow.mjs`

- [ ] **Step 1: 先写假 CLI 行为测试**

```js
import assert from 'node:assert/strict'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const verifier = join(root, 'scripts', 'verify-profile-bundle.mjs')
const fixture = mkdtempSync(join(tmpdir(), 'sr-profile-fixture-'))
const fakeDsh = join(fixture, 'fake-dsh.mjs')
const capture = join(fixture, 'capture.json')

writeFileSync(fakeDsh, `
import assert from 'node:assert/strict'
import { existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'

const args = process.argv.slice(2)
if (args.length === 1 && args[0] === '--version') {
  console.log('0.1.0-rc.7')
  process.exit(0)
}
if (args[0] === 'plugin') {
  assert.deepEqual(args.slice(0, 4), [
    'plugin', '--profile', 'sr-scientific-reading-verify', 'add',
  ])
  assert.ok(existsSync(args[4]), 'tarball 必须存在')
  assert.deepEqual(args.slice(5), ['--offline', '--ignore-scripts'])
  assert.ok(process.env.DSH_HOME?.startsWith(tmpdir()))
  writeFileSync(process.env.FAKE_DSH_CAPTURE, JSON.stringify({
    dshHome: process.env.DSH_HOME,
    secretPresent: Boolean(
      process.env.FEISHU_APP_ID || process.env.FEISHU_APP_SECRET
    ),
  }))
  process.exit(0)
}
if (args.join(' ') === '--profile sr-scientific-reading-verify --dump-config') {
  const row = "- id: scientific-reading\\n  name: '@dsh-external/dsh-scientific-reading'"
  if (process.env.FAKE_DSH_MODE === 'zero') console.log('[]')
  else if (process.env.FAKE_DSH_MODE === 'multi') console.log(row + '\\n' + row)
  else console.log(row)
  process.exit(0)
}
process.exit(9)
`.trimStart(), 'utf8')

function run(mode) {
  return spawnSync(
    process.execPath,
    [verifier, '--dsh-bin', fakeDsh],
    {
      cwd: root,
      encoding: 'utf8',
      env: {
        ...process.env,
        FAKE_DSH_MODE: mode,
        FAKE_DSH_CAPTURE: capture,
        FEISHU_APP_ID: 'must-not-leak',
        FEISHU_APP_SECRET: 'must-not-leak',
      },
    },
  )
}

try {
  const success = run('success')
  assert.equal(success.status, 0, success.stderr)
  assert.match(success.stdout, /profile_bundle_verified/)
  const captured = JSON.parse(readFileSync(capture, 'utf8'))
  assert.equal(captured.secretPresent, false)
  assert.equal(existsSync(captured.dshHome), false)

  const zero = run('zero')
  assert.notEqual(zero.status, 0)
  assert.match(zero.stderr, /profile_bundle_row_count_0/)

  const multi = run('multi')
  assert.notEqual(multi.status, 0)
  assert.match(multi.stderr, /profile_bundle_row_count_2/)
} finally {
  rmSync(fixture, { recursive: true, force: true })
}

console.log('PASS: 隔离 Profile Bundle 验证器通过')
```

- [ ] **Step 2: 运行测试并确认因验证器不存在而失败**

Run: `node tests/profile-bundle-verifier.mjs`

Expected: FAIL because `scripts/verify-profile-bundle.mjs` does not exist.

- [ ] **Step 3: 实现最小验证器**

创建以下完整实现：

```js
#!/usr/bin/env node
import { existsSync, readFileSync } from 'node:fs'
import { mkdir, mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, extname, isAbsolute, join, resolve, sep } from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const profile = 'sr-scientific-reading-verify'
const rowId = 'scientific-reading'
const packageName = '@dsh-external/dsh-scientific-reading'

function tail(value) {
  return String(value ?? '').slice(-2000)
}

function run(prefix, args, { cwd = root, env = process.env, label }) {
  const [command, ...baseArgs] = prefix
  const extension = extname(command).toLowerCase()
  const result = spawnSync(command, [...baseArgs, ...args], {
    cwd,
    env,
    encoding: 'utf8',
    shell: process.platform === 'win32' && ['.cmd', '.bat'].includes(extension),
  })
  if (result.error) throw new Error(`${label}_failed: ${result.error.message}`)
  if (result.status !== 0) {
    throw new Error(
      `${label}_failed: exit=${result.status}; stdout=${tail(result.stdout)}; stderr=${tail(result.stderr)}`,
    )
  }
  return result.stdout
}

function parseDshBin(argv) {
  const index = argv.indexOf('--dsh-bin')
  const value = index >= 0 ? argv[index + 1] : undefined
  if (!value || !isAbsolute(value) || !existsSync(value)) {
    throw new Error('dsh_bin_absolute_existing_file_required')
  }
  return resolve(value)
}

function dshPrefix(dshBin) {
  return ['.js', '.mjs', '.cjs'].includes(extname(dshBin).toLowerCase())
    ? [process.execPath, dshBin]
    : [dshBin]
}

function npmPrefix() {
  const cli = process.env.npm_execpath
  return cli && isAbsolute(cli) && existsSync(cli)
    ? [process.execPath, cli]
    : [process.platform === 'win32' ? 'npm.cmd' : 'npm']
}

function countRows(dump) {
  return dump
    .replaceAll('\r\n', '\n')
    .split(/(?=^\s*-\s+id:)/m)
    .filter((block) => (
      /^\s*-\s+id:\s*scientific-reading\s*$/m.test(block) &&
      /^\s*name:\s*['"]?@dsh-external\/dsh-scientific-reading['"]?\s*$/m.test(block)
    )).length
}

async function main() {
  const dshBin = parseDshBin(process.argv.slice(2))
  const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))
  const expectedVersion = pkg.dshCompatibility?.testedHost
  if (typeof expectedVersion !== 'string') throw new Error('tested_host_required')

  const temporary = await mkdtemp(join(tmpdir(), 'sr-profile-bundle-'))
  const packDirectory = join(temporary, 'pack')
  const dshHome = join(temporary, 'dsh-home')
  await mkdir(packDirectory)

  const env = { ...process.env, DSH_HOME: dshHome, DSH_TELEMETRY_DISABLED: '1' }
  delete env.FEISHU_APP_ID
  delete env.FEISHU_APP_SECRET

  try {
    const prefix = dshPrefix(dshBin)
    const actualVersion = run(prefix, ['--version'], {
      env, label: 'dsh_version',
    }).trim()
    if (actualVersion !== expectedVersion) {
      throw new Error(`dsh_version_mismatch: expected=${expectedVersion}; actual=${actualVersion}`)
    }

    const packOutput = run(npmPrefix(), [
      'pack', '--json', '--ignore-scripts', '--pack-destination', packDirectory,
    ], { env, label: 'npm_pack' })
    const reports = JSON.parse(packOutput)
    if (!Array.isArray(reports) || reports.length !== 1 || !reports[0]?.filename) {
      throw new Error('npm_pack_output_invalid')
    }
    const tarball = join(packDirectory, reports[0].filename)
    if (!existsSync(tarball)) throw new Error('npm_pack_tarball_missing')

    run(prefix, [
      'plugin', '--profile', profile, 'add', tarball, '--offline', '--ignore-scripts',
    ], { env, label: 'dsh_plugin_add' })
    const dump = run(prefix, [
      '--profile', profile, '--dump-config',
    ], { env, label: 'dsh_dump_config' })
    const rowCount = countRows(dump)
    if (rowCount !== 1) throw new Error(`profile_bundle_row_count_${rowCount}`)

    console.log(JSON.stringify({
      status: 'profile_bundle_verified',
      host_version: actualVersion,
      profile,
      row_id: rowId,
    }))
  } finally {
    const target = resolve(temporary)
    const base = resolve(tmpdir()) + sep
    if (!target.startsWith(base) || !basename(target).startsWith('sr-profile-bundle-')) {
      throw new Error('unsafe_temporary_cleanup_target')
    }
    await rm(target, { recursive: true, force: true })
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error))
  process.exitCode = 1
})
```

- [ ] **Step 4: 接入 npm 命令与离线假 CLI 门禁**

增加：

```json
"test:profile-bundle": "node tests/profile-bundle-verifier.mjs",
"verify:profile-bundle": "node scripts/verify-profile-bundle.mjs"
```

把 `tests/profile-bundle-verifier.mjs` 插入 `test:offline` 的
`tests/package-contents.mjs` 之后、`tests/ci-workflow.mjs` 之前，并再次同步
`tests/ci-workflow.mjs` 的完整字符串期望。

- [ ] **Step 5: 运行红绿验证和完整离线门禁**

Run: `npm run test:profile-bundle && npm run test:offline`

Expected: success/zero/multi 三种 fake CLI 情况均按断言通过；完整门禁 exit 0。

- [ ] **Step 6: 提交 Task 3**

```powershell
git add -- scripts/verify-profile-bundle.mjs tests/profile-bundle-verifier.mjs tests/ci-workflow.mjs package.json
git commit -m "测试：验证隔离Profile Bundle激活"
```

### Task 4: 文档、真实 rc.7 验收与阶段收口

**Files:**
- Modify: `README.md`
- Modify: `docs/roadmap.md`
- Modify: `docs/handoff-dsh-native.md`

- [ ] **Step 1: 更新用户与交接文档**

README 增加 Profile Bundle 段落，给出不带本机路径的标准命令：

```powershell
npm run build:ci
npm pack --ignore-scripts
dsh plugin --profile web add .\dsh-external-dsh-scientific-reading-0.0.1.tgz --offline --ignore-scripts
dsh --profile web --dump-config
```

同时说明 web/headless 是独立 profile、当前保持 `private: true`、真实写飞书仍需逐次
确认。handoff 记录离线 CI 与真实 profile 验收的差别；roadmap 将 Profile Bundle
打包与隔离激活标为完成，但只有真实命令通过后才能写完成证据。

- [ ] **Step 2: 在当前机器运行真实 rc.7 临时 profile 验收**

Run:

```powershell
npm run verify:profile-bundle -- --dsh-bin "C:\Users\15694\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\lib\bin.js"
```

Expected: exact JSON status `profile_bundle_verified`; no files appear under the user's existing
`C:\Users\15694\.dsh\profiles` because the verifier overrides `DSH_HOME`.

- [ ] **Step 3: 运行完整阶段门禁**

Run:

```powershell
npm ci --ignore-scripts --legacy-peer-deps
npm run build:ci
npm run test:offline
npm run verify:restart-recovery
node scripts/verify-live.mjs
git diff --check
```

Expected: npm audit 0 vulnerabilities; build passes; offline gate reports 18 tools and 8 routes;
restart recovery prints `restart_recovery_verified`; live verification prints
`PASS: 文献工作流上线验证通过`; diff check has no output.

- [ ] **Step 4: 提交文档**

```powershell
git add -- README.md docs/roadmap.md docs/handoff-dsh-native.md
git commit -m "文档：记录Profile Bundle交付验证"
```

- [ ] **Step 5: medium 审核、合并与清理**

对规格符合性和代码质量依次做 medium 子代理审核；修复所有 Critical/Important 后，
快进合并功能分支到本地 `main`，在 `main` 重跑 Step 2 与 Step 3，再安全删除本阶段
`.worktrees/` worktree 和临时分支。不要推送远端。
