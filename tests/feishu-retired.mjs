import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
for (const file of [
  'engine/src/scientific_reading/feishu_builder.py',
  'engine/src/scientific_reading/feishu_http.py',
  'engine/src/scientific_reading/feishu_models.py',
  'engine/src/scientific_reading/feishu_service.py',
  'tests/feishu-env-only.mjs',
  'engine/tests/test_feishu_http.py',
]) {
  assert.equal(existsSync(join(root, file)), false, `飞书现行文件必须删除：${file}`)
}

for (const file of [
  'src/config.ts',
  'src/cli.ts',
  'src/library_tools.ts',
  'src/routes.ts',
  'client/client.js',
  'engine/src/scientific_reading/__main__.py',
  'engine/src/scientific_reading/batch_service.py',
  'engine/src/scientific_reading/derived_pipeline.py',
  'engine/src/scientific_reading/worker.py',
  'engine/src/scientific_reading/xlsx_snapshot.py',
]) {
  const source = readFileSync(join(root, file), 'utf8')
  assert.doesNotMatch(source, /feishu|飞书/i, `飞书不得留在现行运行文件：${file}`)
}

console.log('PASS: 飞书已退出现行运行面，SQLite 遗留列仅作不可见兼容')
