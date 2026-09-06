import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import crypto from 'node:crypto'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { delimiter, dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const repository = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const plugin = process.env.SR_ASSET_TEST_PLUGIN_ROOT || repository
const { registerLibraryTools } = await import(pathToFileURL(join(plugin, 'lib/library_tools.js')))
const { runEngine } = await import(pathToFileURL(join(plugin, 'lib/cli.js')))
const root = mkdtempSync(join(tmpdir(), 'sr-library-assets-tools-'))
const dataRoot = join(root, '原始库')
const target = join(root, '恢复库')
const archive = join(root, '整库备份.zip')
const python = process.env.SCIENTIFIC_READING_PYTHON || process.env.PYTHON || 'python'
const enginePython = execFileSync(python, ['-c', 'import sys; print(sys.executable)'], {
  encoding: 'utf8', windowsHide: true,
}).trim()
const previousPath = process.env.PYTHONPATH
process.env.PYTHONPATH = [
  ...(process.env.SR_ASSET_TEST_ENGINE_ROOT
    ? [process.env.SR_ASSET_TEST_ENGINE_ROOT]
    : [join(repository, 'engine/src'), join(repository, 'engine')]),
  repository,
].join(delimiter)
const config = {
  dataRoot, enginePython, python, scansciExe: 'scansci-pdf', school: '',
  legalOnly: true, outputDir: '', loginType: 'carsi', scansciPython: '',
}
const tools = new Map()
registerLibraryTools({
  effect(setup) { setup() },
  tools: { register(tool) { tools.set(tool.name, tool); return () => {} } },
}, config)
const call = (name, args) => tools.get(name).execute(args)
const sha = (file) => crypto.createHash('sha256').update(readFileSync(file)).digest('hex')
let passed = false
try {
  const seeded = JSON.parse(execFileSync(python, ['-c', [
    'import json, sys, scientific_reading',
    'from pathlib import Path',
    'from scripts.reading_asset_fixture import seed_reading_assets',
    'from scientific_reading.evidence_locator import build_locator',
    'from scientific_reading.review_service import ReviewService',
    'result = seed_reading_assets(Path(sys.argv[1]))',
    'root = Path(sys.argv[1])',
    'blocks = json.loads((root / result["active_generation"] / "parsed/mineru/source_map.json").read_text(encoding="utf-8"))["blocks"]',
    'block = next(b for b in blocks if b["text"] and len(b["text"]) < 500)',
    'locator = build_locator(root, result["paper_id"], block["block_id"], block["text"])',
    'review = ReviewService(root)',
    'confirmed = review.confirm_conclusions("fixture-review", [{"conclusion_type": "定位检查", "conclusion_text": "定位回跳验证", "basis": "paper", "evidence": locator}])',
    'review.close()',
    'result["conclusion_id"] = confirmed["conclusion_ids"][0]',
    'result["locator"] = locator',
    'result["engine_import"] = scientific_reading.__file__',
    'print(json.dumps(result))',
  ].join('\n'), dataRoot], { encoding: 'utf8', windowsHide: true, env: process.env }).trim())
  const readerSha = sha(join(dataRoot, seeded.reader))
  await assert.rejects(() => call('sr_library_backup', { output: 'relative.zip' }), /absolute_output_required/)
  const backup = await call('sr_library_backup', { output: archive })
  assert.equal(backup.status, 'completed', JSON.stringify(backup))
  assert.equal(backup.sha256, sha(archive))
  const restored = await call('sr_library_restore', { archive, target })
  assert.equal(restored.status, 'completed', JSON.stringify(restored))
  assert.equal(restored.automatic_resume, false)
  assert.equal(sha(join(target, seeded.reader)), readerSha)
  assert.equal(sha(join(dataRoot, seeded.reader)), readerSha)
  assert.equal(config.dataRoot, dataRoot)
  const repeated = await call('sr_library_restore', { archive, target })
  assert.equal(repeated.status, 'failed')
  const installed = { ...config, dataRoot: target }
  const artifact = await runEngine(installed, ['artifact-resolve', '--paper-id', seeded.paper_id, '--kind', 'reader'])
  assert.equal(artifact.ok, true, JSON.stringify(artifact))
  const restoredStatus = JSON.parse(readFileSync(join(target, 'jobs', seeded.job_id, 'status.json'), 'utf8'))
  assert.equal(restoredStatus.state, 'interrupted')
  assert.equal(restoredStatus.pid, null)
  const rebuilt = await call('sr_library_search_rebuild', {})
  assert.ok(rebuilt.documents > 0, JSON.stringify(rebuilt))
  const queries = {}
  for (const query of ['IL-6', 'aPS/PT', '血栓', '血栓风险', '10.1234/reading.assets', '独立验证', '定位回跳', 'no-such-query-918273']) {
    const started = performance.now()
    const result = await runEngine(installed, ['library-list-v2', '--query', query])
    assert.equal(result.ok, true, JSON.stringify(result))
    const items = result.json.items
    queries[query] = { total: result.json.total, types: items.flatMap(item => item.search_matches.map(match => match.content_type)), elapsed_ms: Math.round(performance.now() - started) }
    assert.equal(items.length, query.startsWith('no-such') ? 0 : 1, query)
    if (query === '独立验证') {
      const match = items[0].search_matches.find(match => match.content_type === 'conclusion')
      assert.equal(match.evidence_status, 'legacy_unverified')
    }
    if (query === '定位回跳') {
      const match = items[0].search_matches.find(match => match.content_type === 'conclusion')
      assert.equal(match.evidence_status, 'location_verified')
      assert.equal(match.source.source_map_sha256, seeded.locator.source_map_sha256)
      assert.equal(match.scientific_validity, 'not_assessed')
    }
  }
  const evidence = {
    status: 'passed', root, plugin: resolve(plugin), engine_import: seeded.engine_import,
    source: dataRoot, restored: target, paper_id: seeded.paper_id,
    generations: seeded.generations, job_id: seeded.job_id, reader: seeded.reader,
    conclusion_id: seeded.conclusion_id, locator: seeded.locator,
    reader_sha256: readerSha, backup, restore: restored, queries,
  }
  writeFileSync(join(root, 'evidence.json'), JSON.stringify(evidence, null, 2), 'utf8')
  passed = true
  console.log('PASS: 实际工具经 Python CLI 完成整库备份、恢复、Reader 读回和分层检索')
  if (process.env.SR_ASSET_TEST_KEEP === '1') console.log(JSON.stringify(evidence))
} finally {
  if (previousPath === undefined) delete process.env.PYTHONPATH
  else process.env.PYTHONPATH = previousPath
  if (passed && process.env.SR_ASSET_TEST_KEEP !== '1') {
    assert.equal(dirname(resolve(root)), resolve(tmpdir()))
    assert.ok(root.includes('sr-library-assets-tools-'))
    rmSync(root, { recursive: true, force: true })
  } else if (!passed) console.error(`验收现场保留：${root}`)
}
