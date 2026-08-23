import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { delimiter, join } from 'node:path'
import { tmpdir } from 'node:os'

import { registerRoutes } from '../lib/routes.js'

const python = execFileSync('where.exe', ['python'], { encoding: 'utf8' })
  .split(/\r?\n/).map((line) => line.trim()).find((line) => line.toLowerCase().endsWith('.exe'))
assert.ok(python)
const fixture = mkdtempSync(join(tmpdir(), 'sr-library-api-'))
const fakeRoot = join(fixture, 'fake')
const logPath = join(fixture, 'engine.log')
const responseMarker = join(fixture, 'response-ended')
mkdirSync(join(fakeRoot, 'scientific_reading'), { recursive: true })
writeFileSync(join(fakeRoot, 'scientific_reading', '__init__.py'), '', 'utf8')
writeFileSync(join(fakeRoot, 'scientific_reading', '__main__.py'), [
  'import json, os, sys',
  'args = sys.argv[1:]',
  `log_path = ${JSON.stringify(logPath)}`,
  `marker_path = ${JSON.stringify(responseMarker)}`,
  'payload = sys.stdin.read()',
  'with open(log_path, "a", encoding="utf-8") as log: log.write(json.dumps({"args": args, "response_ended": os.path.exists(marker_path)}) + "\\n")',
  'command = next((x for x in args if x in {"library-list-v2", "folder-list", "library-ingest", "derived-enqueue"}), "")',
  'if command == "library-list-v2": print(json.dumps({"items": [{"paper_id": "library_demo"}], "page": 2, "page_size": 7}))',
  'elif command == "folder-list": print(json.dumps([{"folder_id": "f1", "name": "Inbox"}]))',
  'elif command == "library-ingest": print(json.dumps({"status": "ingested", "paper_id": "library_demo"}))',
  'else: print(json.dumps({"status": "queued"}))',
].join('\n'), 'utf8')
const previousPythonPath = process.env.PYTHONPATH
process.env.PYTHONPATH = previousPythonPath ? fakeRoot + delimiter + previousPythonPath : fakeRoot

const routes = []
const ctx = {
  effect(setup) { setup() },
  logger() {},
  webServer: { register(route) { routes.push(route); return () => {} } },
}
const config = {
  dataRoot: join(fixture, 'data'), python: 'python', scansciExe: 'scansci-pdf', school: '',
  legalOnly: true, outputDir: '', loginType: 'carsi', scansciPython: '', enginePython: python,
  feishuConfig: '',
}
function response() {
  return { statusCode: 0, headers: {}, body: '', ended: false, writeHead(status, headers) { this.statusCode = status; this.headers = headers }, end(body = '') { this.body = String(body); this.ended = true; writeFileSync(responseMarker, 'ended', 'utf8') } }
}
function route(kind, path) { const found = routes.find((r) => r.kind === kind && r.path === path); assert.ok(found, `缺少路由 ${kind}:${path}`); return found }
function request(method, url, body = '') {
  return { method, url, on(event, callback) { if (event === 'data' && body) callback(Buffer.from(body)); if (event === 'end') queueMicrotask(callback) } }
}

try {
  registerRoutes(ctx, config)
  const list = response()
  await route('exact', '/sr/api/library').handler({ method: 'GET', url: '/sr/api/library?page=2&page_size=7&query=cell&folder=f1&tags=a,b&status=ready' }, list)
  assert.equal(list.statusCode, 200)
  assert.deepEqual(JSON.parse(list.body), { items: [{ paper_id: 'library_demo' }], page: 2, page_size: 7 })

  const folders = response()
  await route('exact', '/sr/api/folders').handler({ method: 'GET', url: '/sr/api/folders' }, folders)
  assert.equal(folders.statusCode, 200)
  assert.deepEqual(JSON.parse(folders.body), [{ folder_id: 'f1', name: 'Inbox' }])

  const bad = response()
  await route('prefix', '/sr/api/abstract').handler({ method: 'GET', url: '/sr/api/abstract/../../secret' }, bad)
  assert.equal(bad.statusCode, 404)
  assert.deepEqual(JSON.parse(bad.body), { error: 'bad_paper_id' })

  rmSync(responseMarker, { force: true })
  const ingest = response()
  await route('exact', '/sr/api/library').handler(request('POST', '/sr/api/library', JSON.stringify({ title: 'Caller payload must not become canonical metadata' })), ingest)
  assert.equal(ingest.statusCode, 200)
  assert.equal(ingest.ended, true, 'POST 必须先返回本地结果')
  let derivedEntry
  for (let i = 0; i < 30 && !derivedEntry; i++) {
    if (existsSync(logPath)) {
      derivedEntry = readFileSync(logPath, 'utf8').split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line)).find((entry) => entry.args.includes('derived-enqueue'))
    }
    if (!derivedEntry) await new Promise((resolve) => setTimeout(resolve, 25))
  }
  assert.ok(derivedEntry, 'POST 必须最终提交 derived-enqueue')
  assert.equal(derivedEntry.response_ended, true, 'derived-enqueue 必须在响应结束后调用')
  assert.equal(derivedEntry.args.includes('--paper-id'), true)
  assert.equal(derivedEntry.args.includes('library_demo'), true)
  assert.equal(derivedEntry.args.includes('--metadata'), false)
  assert.equal((readFileSync(logPath, 'utf8').split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line)).filter((entry) => entry.args.includes('derived-enqueue')).length), 1)
  console.log('PASS: 主库/文件夹/摘要轻量 API 稳定 JSON 与路径校验')
} finally {
  if (previousPythonPath === undefined) delete process.env.PYTHONPATH
  else process.env.PYTHONPATH = previousPythonPath
  rmSync(fixture, { recursive: true, force: true })
}
