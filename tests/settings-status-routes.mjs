import { python } from './python-runtime.mjs'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { delimiter, join } from 'node:path'
import { tmpdir } from 'node:os'

import { registerStatusRoutes } from '../lib/status_routes.js'


assert.ok(python)
const fixture = mkdtempSync(join(tmpdir(), 'sr-settings-status-'))
const fakeRoot = join(fixture, 'fake')
const logPath = join(fixture, 'engine.log')
mkdirSync(join(fakeRoot, 'scientific_reading'), { recursive: true })
writeFileSync(join(fakeRoot, 'scientific_reading', '__init__.py'), '', 'utf8')
writeFileSync(join(fakeRoot, 'scientific_reading', '__main__.py'), [
  'import json, sys',
  'args=sys.argv[1:]; payload=sys.stdin.read()',
  `open(${JSON.stringify(logPath)}, 'a', encoding='utf-8').write(json.dumps({'args':args,'payload':payload})+'\\n')`,
  'command=next((x for x in args if x.startswith("environment-")), "")',
  'print(json.dumps({"contract_version":"environment-status-v1","command":command,"onboarding":{"show_settings":command=="environment-status","version":"v1"},"download":{"status":"not_checked","checked_at":None},"institution":{"status":"not_checked","school":"","checked_at":None},"mineru":{"local":{"status":"not_checked","checked_at":None},"api":{"status":"not_checked","checked_at":None},"strategy":"auto"},"library":{"status":"ready","papers":0,"xlsx_pending":0}}))',
].join('\n'), 'utf8')
const oldPythonPath = process.env.PYTHONPATH
process.env.PYTHONPATH = oldPythonPath ? fakeRoot + delimiter + oldPythonPath : fakeRoot

const routes = []
const ctx = { effect(fn) { fn() }, logger() {}, webServer: { register(route) { routes.push(route); return () => {} } } }
const config = { dataRoot: join(fixture, 'data'), python: 'python', scansciExe: 'scansci-pdf', school: '', legalOnly: true, outputDir: '', loginType: 'carsi', scansciPython: '', enginePython: python }
const response = () => ({ statusCode: 0, body: '', writeHead(status) { this.statusCode = status }, end(body = '') { this.body = String(body) } })
const request = (method, url, body = '', headers = {}) => ({ method, url, headers, on(event, callback) { if (event === 'data' && body) callback(Buffer.from(body)); if (event === 'end') queueMicrotask(callback) }, destroy() {} })
const route = (path) => routes.find((item) => item.path === path)
async function call(path, method = 'GET', value = undefined, headers = {}) {
  const res = response()
  const body = value === undefined ? '' : JSON.stringify(value)
  await route(path).handler(request(method, path, body, headers), res)
  return res
}

try {
  registerStatusRoutes(ctx, config)
  assert.ok(!routes.some((route) => route.path.startsWith('/sr/api/settings/institution/')))
  const snapshot = await call('/sr/api/settings/status')
  assert.equal(snapshot.statusCode, 200)
  assert.equal(JSON.parse(snapshot.body).contract_version, 'environment-status-v1')
  let log = readFileSync(logPath, 'utf8').trim().split(/\r?\n/).map(JSON.parse)
  assert.deepEqual(log.map((entry) => entry.args.find((arg) => arg.startsWith('environment-'))), ['environment-status'])

  const sameOrigin = { host: '127.0.0.1:3080', origin: 'http://127.0.0.1:3080', 'x-sr-csrf': '1', 'content-type': 'application/json' }
  assert.equal((await call('/sr/api/settings/recheck', 'POST', { targets: ['download'] }, { ...sameOrigin, origin: 'https://evil.invalid' })).statusCode, 403)
  assert.equal((await call('/sr/api/settings/recheck', 'POST', { targets: ['download'] }, { host: sameOrigin.host, origin: sameOrigin.origin })).statusCode, 403)
  assert.equal((await call('/sr/api/settings/recheck', 'POST', { targets: ['download'] }, sameOrigin)).statusCode, 200)
  assert.equal((await call('/sr/api/settings/mark-presented', 'POST', { version: 'v1' }, sameOrigin)).statusCode, 200)
  assert.equal((await call('/sr/api/settings/recheck', 'POST', { targets: ['institution'] }, sameOrigin)).statusCode, 400)
  assert.equal((await call('/sr/api/settings/recheck', 'POST', { targets: ['cloak'] }, sameOrigin)).statusCode, 400)
  log = readFileSync(logPath, 'utf8').trim().split(/\r?\n/).map(JSON.parse)
  assert.deepEqual(log.map((entry) => entry.args.find((arg) => arg.startsWith('environment-'))), [
    'environment-status', 'environment-recheck', 'environment-mark-presented',
  ])
  console.log('PASS: 设置状态 GET 静态快照，POST 同源 CSRF 与手动检测合同')
} finally {
  if (oldPythonPath === undefined) delete process.env.PYTHONPATH
  else process.env.PYTHONPATH = oldPythonPath
  rmSync(fixture, { recursive: true, force: true })
}
