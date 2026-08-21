import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const workflowPath = fileURLToPath(new URL('../.github/workflows/ci.yml', import.meta.url))
assert.equal(existsSync(workflowPath), true, '缺少 CI workflow')

const workflow = readFileSync(workflowPath, 'utf8')

assert.match(workflow, /^on:\s*\r?\n\s+push:\s*\r?\n\s+pull_request:/m, 'workflow 必须覆盖 push 与 pull request')
assert.match(workflow, /runs-on:\s*windows-latest/, 'workflow 必须使用 windows-latest')
assert.match(workflow, /uses:\s*actions\/setup-node@v4[\s\S]*?node-version:\s*["']22["']/, 'workflow 必须配置 Node 22')
assert.match(workflow, /uses:\s*actions\/setup-python@v5[\s\S]*?python-version:\s*["']3\.11["']/, 'workflow 必须配置 Python 3.11')
assert.match(workflow, /npm ci --ignore-scripts --legacy-peer-deps/, 'workflow 必须执行可复现安装')
assert.match(workflow, /npm run build:ci/, 'workflow 必须执行 CI 构建')
assert.match(workflow, /npm run test:offline/, 'workflow 必须执行离线门禁')

for (const forbidden of [
  'verify-live',
  'restart-recovery',
  'scansci',
  'mineru',
  'feishu_sync',
  'sr_feishu_sync',
]) {
  assert.doesNotMatch(workflow, new RegExp(forbidden, 'i'), `workflow 不得运行 ${forbidden}`)
}

console.log('PASS: CI workflow 仅执行离线门禁')
