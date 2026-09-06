import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { delimiter, join } from 'node:path'
import { tmpdir } from 'node:os'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'

import {
  engineReviewBind,
  engineReviewConfirm,
  engineReviewContext,
  engineReviewOpenState,
  engineXlsxRefresh,
} from '../lib/cli.js'

const python = execFileSync('where.exe', ['python'], { encoding: 'utf8' })
  .split(/\r?\n/).map((line) => line.trim()).find((line) => line.toLowerCase().endsWith('.exe'))
assert.ok(python)
const fixture = mkdtempSync(join(tmpdir(), 'sr-review-adapter-'))
const fakeRoot = join(fixture, 'fake')
const logPath = join(fixture, 'engine.log')
mkdirSync(join(fakeRoot, 'scientific_reading'), { recursive: true })
writeFileSync(join(fakeRoot, 'scientific_reading', '__init__.py'), '', 'utf8')
writeFileSync(join(fakeRoot, 'scientific_reading', '__main__.py'), [
  'import json, sys',
  'args=sys.argv[1:]; payload=json.load(sys.stdin)',
  `open(${JSON.stringify(logPath)}, 'a', encoding='utf-8').write(json.dumps({'args':args,'payload':payload})+'\\n')`,
  'print(json.dumps({"status":"ok"}))',
].join('\n'), 'utf8')
const oldPythonPath = process.env.PYTHONPATH
process.env.PYTHONPATH = oldPythonPath ? fakeRoot + delimiter + oldPythonPath : fakeRoot
const config = {
  dataRoot: join(fixture, 'data'), python: 'python', scansciExe: 'scansci-pdf', school: '',
  legalOnly: true, outputDir: '', loginType: 'carsi', scansciPython: '', enginePython: python,
  presetId: 'scientific-reading', installPreset: false,
}

try {
  await engineReviewOpenState(config, 'parent-a', 'library-a')
  await engineReviewBind(config, 'parent-a', 'library-a', 'child-a')
  await engineReviewContext(config, 'child-a')
  await engineReviewConfirm(config, 'child-a', [{ conclusion_type: '发现', conclusion_text: '内容', evidence_locator: 'p.1' }])
  await engineXlsxRefresh(config)

  const rows = readFileSync(logPath, 'utf8').trim().split(/\r?\n/).map(JSON.parse)
  assert.deepEqual(rows.map((row) => row.args.at(-1)), [
    'review-session-get', 'review-session-bind', 'review-context', 'review-confirm', 'xlsx-refresh',
  ])
  assert.deepEqual(rows[0].payload, { parent_session_id: 'parent-a', paper_id: 'library-a' })
  assert.equal(rows[1].payload.review_session_id, 'child-a')
  assert.deepEqual(rows[2].payload, { review_session_id: 'child-a' })
  assert.equal(rows[3].payload.conclusions.length, 1)
  assert.deepEqual(rows[4].payload, {})
  console.log('PASS: 整理会话引擎适配器只通过 JSON stdin 传递绑定与结论')
} finally {
  if (oldPythonPath === undefined) delete process.env.PYTHONPATH
  else process.env.PYTHONPATH = oldPythonPath
  rmSync(fixture, { recursive: true, force: true })
}
