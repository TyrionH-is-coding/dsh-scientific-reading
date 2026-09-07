import { python } from './python-runtime.mjs'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { delimiter, join } from 'node:path'
import { tmpdir } from 'node:os'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'

import { runEngine } from '../lib/cli.js'


assert.ok(python)
const fixture = mkdtempSync(join(tmpdir(), 'sr-evidence-adapter-'))
const fakeRoot = join(fixture, 'fake')
const logPath = join(fixture, 'engine.log')
mkdirSync(join(fakeRoot, 'scientific_reading'), { recursive: true })
writeFileSync(join(fakeRoot, 'scientific_reading', '__init__.py'), '', 'utf8')
writeFileSync(join(fakeRoot, 'scientific_reading', '__main__.py'), [
  'import json, sys',
  'args=sys.argv[1:]',
  `open(${JSON.stringify(logPath)}, 'a', encoding='utf-8').write(json.dumps(args)+'\\n')`,
  'print(json.dumps({"status":"ok","command":next(x for x in args if x in {"evidence-locate","resolve-conclusion","candidate-rebuild"})}))',
].join('\n'), 'utf8')
const previousPythonPath = process.env.PYTHONPATH
process.env.PYTHONPATH = previousPythonPath
  ? fakeRoot + delimiter + previousPythonPath
  : fakeRoot
const config = {
  dataRoot: join(fixture, 'data'), python: 'python', scansciExe: 'scansci-pdf', school: '',
  legalOnly: true, outputDir: '', loginType: 'carsi', scansciPython: '', enginePython: python,
  presetId: 'scientific-reading', installPreset: false,
}

try {
  const quote = 'literal $(must-not-execute) `or-this`'
  const located = await runEngine(config, [
    'evidence-locate', '--paper-id', 'library_a',
    '--block-id', 'p0001-m0002', '--quote', quote, '--page', '1',
  ])
  const resolved = await runEngine(config, [
    'resolve-conclusion', '--conclusion-id', 'review_' + 'a'.repeat(32),
  ])
  const candidate = await runEngine(config, [
    'candidate-rebuild', '--paper-id', 'library_a',
    '--target-root', join(fixture, 'candidate'),
  ], { timeoutMs: 120_000 })
  assert.equal(located.ok && resolved.ok && candidate.ok, true)

  const rows = readFileSync(logPath, 'utf8').trim().split(/\r?\n/).map(JSON.parse)
  assert.deepEqual(rows.map((row) => row.find((value) => [
    'evidence-locate', 'resolve-conclusion', 'candidate-rebuild',
  ].includes(value))), [
    'evidence-locate', 'resolve-conclusion', 'candidate-rebuild',
  ])
  assert.equal(rows[0][rows[0].indexOf('--quote') + 1], quote)
  console.log('PASS: 证据定位、结论解析和候选重建通过实际 runEngine 参数数组调用')
} finally {
  if (previousPythonPath === undefined) delete process.env.PYTHONPATH
  else process.env.PYTHONPATH = previousPythonPath
  rmSync(fixture, { recursive: true, force: true })
}
