import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { delimiter, join } from 'node:path'
import { tmpdir } from 'node:os'
import { registerRoutes } from '../lib/routes.js'

delete process.env.FEISHU_APP_ID
delete process.env.FEISHU_APP_SECRET
const fixture = mkdtempSync(join(tmpdir(), 'sr-full-routes-'))
const fakeRoot = join(fixture, 'fake')
const log = join(fixture, 'engine.log')
const paperId = 'title_fixture'
const generation = 'a'.repeat(16)
const paperRoot = join(fixture, 'data', 'papers', paperId)
const reader = join(paperRoot, 'generations', generation, 'reading', 'reader.html')
const asset = join(paperRoot, 'generations', generation, 'exports', 'figures', 'Fig_01.png')
mkdirSync(join(fakeRoot, 'scientific_reading'), { recursive: true })
mkdirSync(join(reader, '..'), { recursive: true })
mkdirSync(join(asset, '..'), { recursive: true })
writeFileSync(reader, '<!doctype html><p>new reader</p>')
const readerSha = createHash('sha256').update('<!doctype html><p>new reader</p>').digest('hex')
writeFileSync(asset, Buffer.from('fixture-png'))
const assetSha = createHash('sha256').update(Buffer.from('fixture-png')).digest('hex')
writeFileSync(join(fakeRoot, 'scientific_reading', '__init__.py'), '')
writeFileSync(join(fakeRoot, 'scientific_reading', '__main__.py'), [
  'import json, os, sys',
  'a=sys.argv[1:]; cmd=next((x for x in a if x in {"full-read-pipeline-start","full-read-pipeline-resume","pdf-attach","export-assets","artifact-resolve","library-item-v2","job-status"}), "")',
  `log=${JSON.stringify(log)}`,
  'with open(log,"a",encoding="utf-8") as f: f.write(json.dumps(a)+"\\n")',
  'pid=a[a.index("--paper-id")+1] if "--paper-id" in a else "title_fixture"',
  'if cmd=="full-read-pipeline-start": print(json.dumps({"parent_job_id":"job_0123456789abcdef"}))',
  'elif cmd=="full-read-pipeline-resume": print(json.dumps({"parent_job_id":"job_0123456789abcdef","state":"queued"}))',
  'elif cmd=="pdf-attach": print(json.dumps({"status":"pdf_ready"}))',
  'elif cmd=="export-assets": print(json.dumps({"status":"exported"}))',
  'elif cmd=="library-item-v2": print(json.dumps({"paper_id":pid,"active_job_id":"job_0123456789abcdef"}))',
  'elif cmd=="job-status": print(json.dumps({"status":"waiting_user","reason_code":"pdf_required"}))',
  `elif cmd=="artifact-resolve" and pid=="title_traversal": print(json.dumps({"rel_path":"../secret"}))`,
  `elif cmd=="artifact-resolve" and a[a.index("--kind")+1]=="reader": print(json.dumps({"rel_path":"generations/${generation}/reading/reader.html","manifest":{"reader_sha256":"${readerSha}"}}))`,
  `else: print(json.dumps({"rel_path":"generations/${generation}/exports","manifest":{"contract":"asset-export-v1","paper_id":pid,"source_pdf_sha256":"${'b'.repeat(64)}","assets":[{"export_path":"figures/Fig_01.png","export_sha256":"${assetSha}"}]}}))`,
].join('\n'))
const python = execFileSync('where.exe', ['python'], { encoding: 'utf8' }).split(/\r?\n/).find((x) => x.trim().toLowerCase().endsWith('.exe')).trim()
const oldPath = process.env.PYTHONPATH
process.env.PYTHONPATH = oldPath ? fakeRoot + delimiter + oldPath : fakeRoot
const routes = []
registerRoutes({ effect(fn) { fn() }, logger() {}, webServer: { register(r) { routes.push(r); return () => {} } } }, { dataRoot: join(fixture, 'data'), python: 'python', scansciExe: 'scansci-pdf', school: '', legalOnly: true, outputDir: '', loginType: 'carsi', scansciPython: '', enginePython: python, feishuConfig: '' })
const prefix = (path) => routes.find((r) => r.kind === 'prefix' && r.path === path)
const req = (method, url, value = {}) => { const body = JSON.stringify(value); return { method, url, on(event, cb) { if (event === 'data') cb(Buffer.from(body)); if (event === 'end') queueMicrotask(cb) } } }
const res = () => ({ statusCode: 0, body: '', writeHead(s, h) { this.statusCode = s; this.headers = h }, end(v = '') { this.body = Buffer.isBuffer(v) ? v : String(v) } })

try {
  for (const [url, body] of [[`/sr/api/paper/${paperId}/start`, {}], [`/sr/api/paper/${paperId}/export`, {}]]) {
    const out = res(); await prefix('/sr/api/paper').handler(req('POST', url, body), out); assert.equal(out.statusCode, 200)
  }
  const continued = res(); await prefix('/sr/api/job').handler(req('POST', '/sr/api/job/job_0123456789abcdef/continue', {}), continued); assert.equal(continued.statusCode, 200)
  const badJob = res(); await prefix('/sr/api/job').handler(req('POST', '/sr/api/job/not-a-job/continue', {}), badJob); assert.equal(badJob.statusCode, 404)
  const payload = { pdf_b64: Buffer.alloc(1200, 1).toString('base64') }
  const a = res(), b = res(); await Promise.all([prefix('/sr/api/paper').handler(req('POST', `/sr/api/paper/${paperId}/attach`, payload), a), prefix('/sr/api/paper').handler(req('POST', `/sr/api/paper/${paperId}/attach`, payload), b)])
  assert.equal(a.statusCode, 200); assert.equal(b.statusCode, 200)
  const rows = readFileSync(log, 'utf8').trim().split(/\r?\n/).map(JSON.parse).filter((x) => x.includes('pdf-attach'))
  const paths = rows.map((x) => x[x.indexOf('--pdf') + 1]); assert.equal(new Set(paths).size, 2); assert.ok(paths.every((x) => x.endsWith('.pdf') && !existsSync(x)))
  const traversal = res(); await prefix('/sr/api/paper').handler(req('GET', '/sr/api/paper/title_traversal/reader'), traversal); assert.equal(traversal.statusCode, 404)
  const readerOut = res(); await prefix('/sr/api/paper').handler(req('GET', `/sr/api/paper/${paperId}/reader`), readerOut); assert.equal(readerOut.statusCode, 200)
  writeFileSync(reader, '<!doctype html><p>tampered</p>')
  const tampered = res(); await prefix('/sr/api/paper').handler(req('GET', `/sr/api/paper/${paperId}/reader`), tampered); assert.equal(tampered.statusCode, 409)
  const manifest = res(); await prefix('/sr/api/paper').handler(req('GET', `/sr/api/paper/${paperId}/exports`), manifest); assert.equal(manifest.statusCode, 200)
  const download = res(); await prefix('/sr/api/paper').handler(req('GET', `/sr/api/paper/${paperId}/exports/figures/Fig_01.png`), download); assert.equal(download.statusCode, 200); assert.deepEqual(download.body, Buffer.from('fixture-png'))
  console.log('PASS: 精读动态路由、并发 attach 清理与资产 allowlist/SHA 合同')
} finally {
  if (oldPath === undefined) delete process.env.PYTHONPATH; else process.env.PYTHONPATH = oldPath
  rmSync(fixture, { recursive: true, force: true })
}
