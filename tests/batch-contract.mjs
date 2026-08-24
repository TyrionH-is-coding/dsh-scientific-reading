import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { delimiter, join } from 'node:path'
import { tmpdir } from 'node:os'
import { registerRoutes } from '../lib/routes.js'

delete process.env.FEISHU_APP_ID
delete process.env.FEISHU_APP_SECRET
const python = execFileSync('where.exe', ['python'], { encoding: 'utf8' }).split(/\r?\n/).map((line) => line.trim()).find((line) => line.toLowerCase().endsWith('.exe'))
assert.ok(python)
const fixture = mkdtempSync(join(tmpdir(), 'sr-batch-contract-'))
const fakeRoot = join(fixture, 'fake')
const inputLog = join(fixture, 'input.log')
mkdirSync(join(fakeRoot, 'scientific_reading'), { recursive: true })
writeFileSync(join(fakeRoot, 'scientific_reading', '__init__.py'), '', 'utf8')
writeFileSync(join(fakeRoot, 'scientific_reading', '__main__.py'), [
  'import json, sys',
  'a=sys.argv[1:]; payload=sys.stdin.read()',
  `open(${JSON.stringify(inputLog)}, "a", encoding="utf-8").write(json.dumps({"args":a,"payload":json.loads(payload)}) + "\\n")`,
  'print(json.dumps({"parent_job_id":"job_0123456789abcdef","status":"queued","summary":{"total":len(json.loads(payload)["selection"])},"children":[{"paper_id":"library_1","status":"failed","error":"Traceback: SECRET token leaked"}],"stack":"Traceback SECRET","api_secret":"TOKEN"}))',
].join('\n'), 'utf8')
const oldPythonPath = process.env.PYTHONPATH
process.env.PYTHONPATH = oldPythonPath ? fakeRoot + delimiter + oldPythonPath : fakeRoot
const routes = []
const ctx = { effect(fn) { fn() }, logger() {}, webServer: { register(route) { routes.push(route); return () => {} } } }
const config = { dataRoot: join(fixture, 'data'), python: 'python', scansciExe: 'scansci-pdf', school: '', legalOnly: true, outputDir: '', loginType: 'carsi', scansciPython: '', enginePython: python, feishuConfig: '' }
const response = () => ({ statusCode: 0, headers: {}, body: '', writeHead(status, headers) { this.statusCode = status; this.headers = headers }, end(body = '') { this.body = String(body) } })
const request = (method, body = '', oversized = false) => ({ method, url: '/sr/api/batch', on(event, cb) { if (event === 'data' && body) cb(oversized ? Buffer.alloc(1024 * 1024 + 1) : Buffer.from(body)); if (event === 'end') queueMicrotask(cb) }, destroy() {} })
async function call(method, value, oversized = false) { const res = response(); const route = routes.find((item) => item.path === '/sr/api/batch'); assert.ok(route); await route.handler(request(method, typeof value === 'string' ? value : JSON.stringify(value), oversized), res); return res }

try {
  registerRoutes(ctx, config)
  assert.equal((await call('GET', '')).statusCode, 405)
  assert.equal((await call('POST', { action: 'delete', selection: ['library_1'] })).statusCode, 400)
  assert.equal((await call('POST', { action: 'unknown', selection: ['library_1'] })).statusCode, 400)
  assert.equal((await call('POST', { action: 'move_folder', selection: [] })).statusCode, 400)
  assert.equal((await call('POST', { action: 'move_folder', selection: ['../secret'] })).statusCode, 400)
  assert.equal((await call('POST', { action: 'feishu_resync', selection: ['library_1'], payload: { feishu_record_url: 'https://evil.invalid' } })).statusCode, 400)
  assert.equal((await call('POST', '{}', true)).statusCode, 413)
  const duplicate = await call('POST', { action: 'queue_full_read', selection: ['library_1', 'library_1'], payload: {} })
  assert.equal(duplicate.statusCode, 200, '引擎负责稳定去重，HTTP 不得拆分或改变原请求')

  const allowed = ['move_folder', 'add_tags', 'remove_tags', 'queue_full_read', 'retry_failed', 'feishu_resync']
  for (const action of allowed) {
    const result = await call('POST', { action, selection: ['library_1'], payload: {} })
    assert.equal(result.statusCode, 200, action)
    assert.deepEqual(JSON.parse(result.body), { parent_job_id: 'job_0123456789abcdef', status: 'queued', summary: { total: 1 }, children: [{ paper_id: 'library_1', status: 'failed', error: 'redacted' }] })
  }

  const selection = Array.from({ length: 101 }, (_, index) => `library_${index + 1}`)
  const result = await call('POST', { action: 'queue_full_read', selection, payload: { note: 'one request' } })
  assert.equal(result.statusCode, 200)
  const entries = readFileSync(inputLog, 'utf8').split(/\r?\n/).filter(Boolean).map(JSON.parse)
  const last = entries.at(-1)
  assert.equal(entries.length, allowed.length + 2)
  assert.equal(last.args.includes('batch-submit'), true)
  assert.deepEqual(last.payload.selection, selection)

  console.log('PASS: 批量 HTTP 合同固定白名单、单次完整转发与安全错误')
} finally {
  if (oldPythonPath === undefined) delete process.env.PYTHONPATH
  else process.env.PYTHONPATH = oldPythonPath
  rmSync(fixture, { recursive: true, force: true })
}
