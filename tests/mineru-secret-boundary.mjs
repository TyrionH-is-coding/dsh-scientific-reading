import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { delimiter, join } from 'node:path'
import { tmpdir } from 'node:os'

import { Config } from '../lib/config.js'
import { registerStatusRoutes } from '../lib/status_routes.js'

const secret = 'fictional-mineru-secret-never-echo'
const python = execFileSync('where.exe', ['python'], { encoding: 'utf8' }).split(/\r?\n/).map((x) => x.trim()).find((x) => x.toLowerCase().endsWith('.exe'))
const fixture = mkdtempSync(join(tmpdir(), 'sr-mineru-secret-'))
const fakeRoot = join(fixture, 'fake')
const logPath = join(fixture, 'argv.json')
mkdirSync(join(fakeRoot, 'scientific_reading'), { recursive: true })
writeFileSync(join(fakeRoot, 'scientific_reading', '__init__.py'), '', 'utf8')
writeFileSync(join(fakeRoot, 'scientific_reading', '__main__.py'), [
  'import json, sys',
  'args=sys.argv[1:]; payload=json.loads(sys.stdin.read() or "{}")',
  `open(${JSON.stringify(logPath)}, 'w', encoding='utf-8').write(json.dumps({'args':args,'has_key':bool(payload.get('api_key'))}))`,
  'command=next((x for x in args if x.startswith("mineru-secret-")), "")',
  'print(json.dumps({"status":"configured" if command=="mineru-secret-save" else "not_configured","source":"secure_store" if command=="mineru-secret-save" else "none","checked_at":None}))',
].join('\n'), 'utf8')
const oldPythonPath = process.env.PYTHONPATH
process.env.PYTHONPATH = oldPythonPath ? fakeRoot + delimiter + oldPythonPath : fakeRoot
const routes = []
const ctx = { effect(fn) { fn() }, logger() {}, webServer: { register(route) { routes.push(route); return () => {} } } }
const config = { dataRoot: join(fixture, 'data'), python: 'python', scansciExe: 'scansci-pdf', school: '', legalOnly: true, outputDir: '', loginType: 'carsi', scansciPython: '', enginePython: python }
const response = () => ({ statusCode: 0, body: '', writeHead(status) { this.statusCode = status }, end(body = '') { this.body = String(body) } })
const headers = { host: '127.0.0.1:3080', origin: 'http://127.0.0.1:3080', 'x-sr-csrf': '1', 'content-type': 'application/json' }
const request = (method, body, suppliedHeaders = headers) => ({ method, url: '/sr/api/settings/mineru-key', headers: suppliedHeaders, on(event, cb) { if (event === 'data' && body) cb(Buffer.from(body)); if (event === 'end') queueMicrotask(cb) }, destroy() {} })

try {
  registerStatusRoutes(ctx, config)
  const route = routes.find((item) => item.path === '/sr/api/settings/mineru-key')
  assert.ok(route)
  const forbidden = response()
  await route.handler(request('POST', JSON.stringify({ api_key: secret }), { host: headers.host, origin: headers.origin }), forbidden)
  assert.equal(forbidden.statusCode, 403)
  const saved = response()
  await route.handler(request('POST', JSON.stringify({ api_key: secret })), saved)
  assert.equal(saved.statusCode, 200)
  assert.equal(saved.body.includes(secret), false)
  const invocation = JSON.parse(readFileSync(logPath, 'utf8'))
  assert.equal(JSON.stringify(invocation.args).includes(secret), false)
  assert.equal(invocation.has_key, true)
  const removed = response()
  await route.handler(request('DELETE', ''), removed)
  assert.equal(removed.statusCode, 200)
  assert.equal(removed.body.includes(secret), false)
  assert.equal(JSON.stringify(Config.toJSON()).includes('mineruApiToken'), false)
  assert.equal(readFileSync(new URL('../client/client.js', import.meta.url), 'utf8').includes(secret), false)
  console.log('PASS: MinerU Key 仅经受保护写入边界传递，不进入配置、argv 或响应')
} finally {
  if (oldPythonPath === undefined) delete process.env.PYTHONPATH
  else process.env.PYTHONPATH = oldPythonPath
  rmSync(fixture, { recursive: true, force: true })
}
