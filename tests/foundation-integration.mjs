import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { tmpdir } from 'node:os'

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const script = join(root, 'scripts', 'verify_two_stage_foundation.py')
const engine = process.env.SR_ENGINE_ROOT || join(root, '..', '..', '..', 'Scientific-Reading-for-Newbies', '.worktrees', 'two-stage-workflow')
const python = process.env.PYTHON || join(process.env.USERPROFILE || '', 'scientific-reading-data', '.venv', 'Scripts', 'python.exe')
const tempPrefix = 'sr-foundation-'
const beforeTemp = new Set(readdirSync(tmpdir()).filter((name) => name.startsWith(tempPrefix)))

delete process.env.FEISHU_APP_ID
delete process.env.FEISHU_APP_SECRET

const output = execFileSync(python, [script], {
  cwd: root,
  encoding: 'utf8',
  env: {
    ...process.env,
    FEISHU_APP_ID: 'placeholder-must-be-ignored',
    FEISHU_APP_SECRET: 'placeholder-must-be-ignored',
    SR_ENGINE_ROOT: engine,
  },
})
const afterTemp = readdirSync(tmpdir()).filter((name) => name.startsWith(tempPrefix))
assert.deepEqual(afterTemp.filter((name) => !beforeTemp.has(name)), [], 'verifier 不得残留自己创建的 Windows 临时目录')
const lines = output.trim().split(/\r?\n/)
assert.equal(lines.length, 1, 'verifier 必须只输出一行 JSON')
const result = JSON.parse(lines[0])
assert.equal(result.status, 'passed_with_limits')
for (const step of ['plugin_dispatch', 'skeleton', 'derived_pipeline', 'metadata_abstract', 'race_guard', 'xlsx', 'fake_feishu', 'classification', 'undo']) {
  assert.equal(result.steps?.[step], 'passed', `步骤 ${step} 未通过`)
}
assert.equal(result.external_writes, false)
assert.equal(result.profile_3080_unchanged, false)
assert.equal(result.profile_3080_gate, 'not_verified')
assert.equal(result.runtime?.before?.profile?.status, 'skipped')
assert.equal(result.runtime?.before?.['3080']?.status, 'skipped')
assert.equal(result.cleanup?.status, 'passed')
assert.equal(result.cleanup?.exists, false)
console.log('PASS: Phase 1 两段式主库离线集成验收（Profile/3080 未提供探针，未伪装为 unchanged）')
