import { python } from './python-runtime.mjs'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { delimiter, join } from 'node:path'
import { tmpdir } from 'node:os'

import { registerStatusRoutes } from '../lib/status_routes.js'


const fixture = mkdtempSync(join(tmpdir(), 'sr-excel-action-'))
const fakeRoot = join(fixture, 'fake')
const logPath = join(fixture, 'argv.json')
mkdirSync(join(fakeRoot, 'scientific_reading'), { recursive: true })
writeFileSync(join(fakeRoot, 'scientific_reading', '__init__.py'), '', 'utf8')
writeFileSync(join(fakeRoot, 'scientific_reading', '__main__.py'), [
  'import json, sys',
  'args=sys.argv[1:]',
  `open(${JSON.stringify(logPath)}, 'w', encoding='utf-8').write(json.dumps(args))`,
  'print(json.dumps({"status":"opened","paper_id":args[args.index("--paper-id")+1],"row":7}))',
].join('\n'), 'utf8')
const oldPythonPath = process.env.PYTHONPATH
process.env.PYTHONPATH = oldPythonPath ? fakeRoot + delimiter + oldPythonPath : fakeRoot
const routes = []
const ctx = { effect(fn) { fn() }, logger() {}, webServer: { register(route) { routes.push(route); return () => {} } } }
const config = { dataRoot: join(fixture, 'data'), python: 'python', scansciExe: 'scansci-pdf', school: '', legalOnly: true, outputDir: '', loginType: 'carsi', scansciPython: '', enginePython: python }
const response = () => ({ statusCode: 0, body: '', writeHead(status) { this.statusCode = status }, end(body = '') { this.body = String(body) } })
const request = (method, url) => ({ method, url, headers: {}, on(event, cb) { if (event === 'end') queueMicrotask(cb) }, destroy() {} })

try {
  registerStatusRoutes(ctx, config)
  const route = routes.find((item) => item.path === '/sr/api/excel/locate')
  assert.ok(route)
  const good = response()
  await route.handler(request('POST', '/sr/api/excel/locate?paper_id=library_safe'), good)
  assert.equal(good.statusCode, 200)
  assert.deepEqual(JSON.parse(good.body), { status: 'opened', paper_id: 'library_safe', row: 7 })
  assert.deepEqual(JSON.parse(readFileSync(logPath, 'utf8')).slice(-3), ['xlsx-locate', '--paper-id', 'library_safe'])
  const injected = response()
  await route.handler(request('POST', '/sr/api/excel/locate?paper_id=../secret&A1=cmd'), injected)
  assert.equal(injected.statusCode, 400)
  console.log('PASS: Excel 定位只接受 paper_id，不接受路径或单元格参数')
} finally {
  if (oldPythonPath === undefined) delete process.env.PYTHONPATH
  else process.env.PYTHONPATH = oldPythonPath
  rmSync(fixture, { recursive: true, force: true })
}
