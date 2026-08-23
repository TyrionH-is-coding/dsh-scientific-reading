import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { delimiter, join } from 'node:path'
import { tmpdir } from 'node:os'

import { engineJson, engineStartDetached } from '../lib/cli.js'
import { isPaperId, paperMetadataPath } from '../lib/papers.js'

const python = execFileSync('where.exe', ['python'], { encoding: 'utf8' })
  .split(/\r?\n/).map((line) => line.trim()).find((line) => line.toLowerCase().endsWith('.exe'))
assert.ok(python, '需要 PATH 中存在 python.exe')

const root = await mkdtemp(join(tmpdir(), 'sr-two-stage-ingest-'))
const packageDir = join(root, 'scientific_reading')
const logPath = join(root, 'engine.log')
await writeFile(join(root, 'marker.txt'), '', 'utf8')
await (await import('node:fs/promises')).mkdir(packageDir)
await writeFile(join(packageDir, '__init__.py'), '', 'utf8')
await writeFile(join(packageDir, '__main__.py'), [
  'import json, os, sys, time',
  'args = sys.argv[1:]',
  `log = ${JSON.stringify(logPath)}`,
  'with open(log, "a", encoding="utf-8") as f: f.write(json.dumps(args) + "\\n")',
  'if "--slow" in args: time.sleep(0.8)',
  'command = next((x for x in args if x in {"library-list-v2", "library-ingest", "metadata-enrichment"}), "")',
  'if command == "library-list-v2": print(json.dumps({"items": [{"paper_id": "library_demo"}], "page": 2, "page_size": 7}))',
  'elif command == "library-ingest": print(json.dumps({"status": "ingested", "paper_id": "library_demo", "dedupe": "new"}))',
  'else: print(json.dumps({"status": "queued", "command": command}))',
].join('\n'), 'utf8')

const previousPythonPath = process.env.PYTHONPATH
process.env.PYTHONPATH = previousPythonPath ? root + delimiter + previousPythonPath : root
const config = {
  dataRoot: join(root, 'data'), python: 'python', scansciExe: 'scansci-pdf', school: '',
  legalOnly: true, outputDir: '', loginType: 'carsi', scansciPython: '', enginePython: python,
  feishuConfig: '',
}

try {
  const local = await engineJson(config, ['library-ingest'], { title: 'Local result' })
  assert.equal(local.ok, true)
  assert.equal(local.json?.paper_id, 'library_demo')

  const started = Date.now()
  const detached = await engineStartDetached(config, ['metadata-enrichment', '--slow'], { paper_id: 'library_demo' })
  assert.equal(detached.started, true)
  assert.ok(Date.now() - started < 500, 'detached 调用不得等待派生任务')

  assert.equal(isPaperId('library_demo'), true)
  assert.equal(isPaperId('doi_10.1000_test'), true)
  assert.equal(isPaperId('../outside'), false)
  assert.equal(isPaperId('library_.._secret'), false)
  assert.throws(() => paperMetadataPath(config.dataRoot, '../outside'), /invalid_paper_id/)

  for (let i = 0; i < 20; i++) {
    try {
      const log = await readFile(logPath, 'utf8')
      if (log.includes('metadata-enrichment')) break
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  const log = await readFile(logPath, 'utf8')
  assert.match(log, /metadata-enrichment/)
  console.log('PASS: 两阶段入库本地结果先返回、派生脱离等待且 paper_id 防穿越')
} finally {
  if (previousPythonPath === undefined) delete process.env.PYTHONPATH
  else process.env.PYTHONPATH = previousPythonPath
  await rm(root, { recursive: true, force: true })
}
