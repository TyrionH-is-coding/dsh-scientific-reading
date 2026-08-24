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
assert.match(workflow, /runs-on:\s*windows-latest/, 'workflow 必须使用 windows-latest')

const uses = [...workflow.matchAll(/^\s*(?:-\s*)?uses:\s*(\S+)\s*$/gm)].map((match) => match[1])
const runs = [...workflow.matchAll(/^\s*(?:-\s*)?run:\s*(.+?)\s*$/gm)].map((match) => match[1])

assert.deepEqual(uses, [
  'actions/checkout@v4',
  'actions/setup-node@v4',
  'actions/setup-python@v5',
], 'workflow 只能使用允许的 actions')
assert.deepEqual(runs, [
  'npm ci --ignore-scripts --legacy-peer-deps',
  'npm run build:ci',
  'npm run test:offline',
], 'workflow 只能执行离线命令')
assert.equal(manifest.scripts?.['build:ci'], 'tsc -p tsconfig.json && node scripts/build-client.mjs')
assert.equal(manifest.scripts?.['test:offline'], 'node tests/client-build.mjs && node tests/client-ui-contract.mjs && node tests/client-actions.mjs && node tests/client-batch-actions.mjs && node tests/dsh-compat.mjs && node tests/bundle-contract.mjs && node tests/package-contents.mjs && node tests/profile-bundle-verifier.mjs && node tests/profile-runtime-verifier.mjs && node tests/navigation-runtime.mjs && node tests/reading-routes.mjs && node tests/batch-contract.mjs && node tests/two-stage-ingest.mjs && node tests/phase1-plugin-contract.mjs && node tests/library-navigation-api.mjs && node tests/restart-recovery-pid-safety.mjs && node tests/task7-hidden-subprocess.mjs && node tests/ci-workflow.mjs && node tests/harness.mjs && node tests/no-zotero-runtime.mjs && node tests/feishu-env-only.mjs && node scripts/plugin-check.mjs')

console.log('PASS: CI workflow 仅执行离线门禁')
