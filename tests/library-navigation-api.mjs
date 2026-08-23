import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { delimiter, join } from 'node:path'
import { tmpdir } from 'node:os'

import { registerRoutes } from '../lib/routes.js'

const python = execFileSync('where.exe', ['python'], { encoding: 'utf8' })
  .split(/\r?\n/).map((line) => line.trim()).find((line) => line.toLowerCase().endsWith('.exe'))
assert.ok(python)
const fixture = mkdtempSync(join(tmpdir(), 'sr-library-api-'))
const fakeRoot = join(fixture, 'fake')
mkdirSync(join(fakeRoot, 'scientific_reading'), { recursive: true })
writeFileSync(join(fakeRoot, 'scientific_reading', '__init__.py'), '', 'utf8')
writeFileSync(join(fakeRoot, 'scientific_reading', '__main__.py'), [
  'import json, sys',
  'args = sys.argv[1:]',
  'command = next((x for x in args if x in {"library-list-v2", "folder-list", "library-ingest"}), "")',
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
  return { statusCode: 0, headers: {}, body: '', writeHead(status, headers) { this.statusCode = status; this.headers = headers }, end(body = '') { this.body = String(body) } }
}
function route(kind, path) { const found = routes.find((r) => r.kind === kind && r.path === path); assert.ok(found, `缺少路由 ${kind}:${path}`); return found }

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
  console.log('PASS: 主库/文件夹/摘要轻量 API 稳定 JSON 与路径校验')
} finally {
  if (previousPythonPath === undefined) delete process.env.PYTHONPATH
  else process.env.PYTHONPATH = previousPythonPath
  rmSync(fixture, { recursive: true, force: true })
}
