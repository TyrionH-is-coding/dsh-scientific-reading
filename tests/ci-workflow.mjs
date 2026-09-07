import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const workflowPath = join(root, '.github', 'workflows', 'ci.yml')
assert.equal(existsSync(workflowPath), true, '缺少 CI workflow')

const workflow = readFileSync(workflowPath, 'utf8')
const manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))

assert.match(workflow, /^on:\s*\r?\n\s+push:\s*\r?\n\s+pull_request:/m, 'workflow 必须覆盖 push 与 pull request')
assert.match(workflow, /runs-on:\s*\$\{\{ matrix.os \}\}/, 'workflow 必须运行跨平台矩阵')
for (const runner of ['windows-latest', 'ubuntu-22.04', 'ubuntu-24.04-arm', 'macos-14', 'macos-15-intel']) {
  assert.ok(workflow.includes(runner), '缺少平台 ' + runner)
}

const uses = [...workflow.matchAll(/^\s*(?:-\s*)?uses:\s*(\S+)\s*$/gm)].map((match) => match[1])
const runs = [...workflow.matchAll(/^\s*(?:-\s*)?run:\s*(.+?)\s*$/gm)].map((match) => match[1])

assert.deepEqual(uses, [
  'actions/checkout@v4',
  'actions/setup-node@v4',
  'actions/setup-python@v5',
], 'workflow 只能使用允许的 actions')
assert.deepEqual(runs, [
  'npm ci --ignore-scripts --legacy-peer-deps',
  'python -m pip install -e "engine[dev]"',
  'npm run build:ci',
  'npm run test:engine',
  'npm run test:offline',
  'npm run test:assets',
], 'workflow 必须构建单仓库包并运行引擎与插件测试')
assert.match(manifest.scripts?.['build:ci'] ?? '', /build-engine\.mjs/)
assert.equal(manifest.scripts?.['test:engine'], 'node scripts/run-python.mjs -m pytest -q engine/tests')
assert.equal(manifest.scripts?.['verify:restart-recovery'], 'node scripts/run-python.mjs scripts/verify_restart_recovery.py --full-read')
assert.match(manifest.scripts?.['test:offline'] ?? '', /tests\/bundled-engine\.mjs/)
assert.doesNotMatch(manifest.scripts?.['test:offline'] ?? '', /profile|foundation-integration|full-read-integration/)

console.log('PASS: CI workflow 构建内置 wheel 并执行单仓库门禁')
