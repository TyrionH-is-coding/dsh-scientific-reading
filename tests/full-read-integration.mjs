import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const engine = process.env.SR_ENGINE_ROOT || join(root, '..', '..', '..', 'Scientific-Reading-for-Newbies', '.worktrees', 'two-stage-workflow')
const python = process.env.PYTHON || join(process.env.USERPROFILE || '', 'scientific-reading-data', '.venv', 'Scripts', 'python.exe')

delete process.env.FEISHU_APP_ID
delete process.env.FEISHU_APP_SECRET

const isolatedEnv = { ...process.env, SR_ENGINE_ROOT: engine }
delete isolatedEnv.FEISHU_APP_ID
delete isolatedEnv.FEISHU_APP_SECRET
const stdout = execFileSync(python, [join(root, 'scripts', 'verify_full_read_pipeline.py')], {
  cwd: root,
  encoding: 'utf8',
  env: isolatedEnv,
})
const lines = stdout.trim().split(/\r?\n/)
assert.equal(lines.length, 1, '验收脚本必须只输出一行 JSON')
const result = JSON.parse(lines[0])
assert.equal(result.status, 'full_read_pipeline_verified')
assert.deepEqual(result.interruptions, [
  'after_pdf_publish',
  'after_mineru',
  'after_translation_batch_1',
  'after_reader_staging',
])
assert.equal(result.completed_stages_repeated, 0)
assert.equal(result.active_reader_count, 1)
assert.match(result.reader_path, /^papers\/[^/]+\/generations\/[a-f0-9]{16}\/reading\/reader\.html$/)
assert.equal(result.sha_alignment, true)
assert.deepEqual(result.exports, { figures: 2, tables: 1, captions: true, manifest: true })
assert.equal(result.external_writes, false)
assert.equal(result.network_used, false)
assert.equal(result.profile_isolated, true)
assert.equal(result.installed_package?.unchanged, true)
assert.equal(result.installed_package?.inventory_unchanged, true)
assert.equal(result.formal_parent?.all_completed, true)
assert.equal(result.formal_parent?.stable_parent_ids, true)
assert.equal(result.formal_parent?.unique_active_parent, true)
assert.equal(result.formal_parent?.all_stage_counts_once, true)
assert.deepEqual(result.tamper_negative, { reader: true, export: true })
assert.equal(result.fixture.pages, 4)
assert.equal(result.fixture.translation_batches, 2)

const packageJson = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))
assert.equal(packageJson.scripts['test:full-read-integration'], 'node tests/full-read-integration.mjs')
const defaultEnv = { ...isolatedEnv }
delete defaultEnv.SR_ENGINE_ROOT
const defaultResult = JSON.parse(execFileSync(python, [join(root, 'scripts', 'verify_full_read_pipeline.py'), '--resolve-engine-only'], {
  cwd: root,
  encoding: 'utf8',
  env: defaultEnv,
}))
assert.equal(defaultResult.engine_root, engine)
console.log('PASS: Phase 2 精读全链路四边界中断恢复与完整性验收')
