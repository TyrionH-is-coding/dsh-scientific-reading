import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const script = join(root, 'scripts', 'verify_two_stage_foundation.py')
const engine = process.env.SR_ENGINE_ROOT || join(root, '..', '..', '..', 'Scientific-Reading-for-Newbies', '.worktrees', 'two-stage-workflow')
const python = process.env.PYTHON || join(process.env.USERPROFILE || '', 'scientific-reading-data', '.venv', 'Scripts', 'python.exe')

const output = execFileSync(python, [script], {
  cwd: root,
  encoding: 'utf8',
  env: {
    ...process.env,
    FEISHU_APP_ID: '',
    FEISHU_APP_SECRET: '',
    SR_ENGINE_ROOT: engine,
  },
})
const lines = output.trim().split(/\r?\n/)
assert.equal(lines.length, 1, 'verifier 必须只输出一行 JSON')
const result = JSON.parse(lines[0])
assert.equal(result.status, 'passed')
for (const step of ['skeleton', 'metadata_abstract', 'race_guard', 'xlsx', 'fake_feishu', 'classification', 'undo']) {
  assert.equal(result.steps?.[step], 'passed', `步骤 ${step} 未通过`)
}
assert.equal(result.external_writes, false)
assert.equal(result.profile_3080_unchanged, true)
console.log('PASS: Phase 1 两段式主库离线集成验收')
