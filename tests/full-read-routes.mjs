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
mkdirSync(join(fakeRoot, 'scansci_pdf', 'sources'), { recursive: true })
mkdirSync(join(reader, '..'), { recursive: true })
mkdirSync(join(asset, '..'), { recursive: true })
writeFileSync(reader, '<!doctype html><p>new reader</p>')
const readerSha = createHash('sha256').update('<!doctype html><p>new reader</p>').digest('hex')
writeFileSync(asset, Buffer.from('fixture-png'))
const assetSha = createHash('sha256').update(Buffer.from('fixture-png')).digest('hex')
writeFileSync(join(fakeRoot, 'scientific_reading', '__init__.py'), '')
writeFileSync(join(fakeRoot, 'scansci_pdf', '__init__.py'), '')
writeFileSync(join(fakeRoot, 'scansci_pdf', 'auth.py'), 'class WebVPNAuth:\n def login(self,force=False): return False\n')
writeFileSync(join(fakeRoot, 'scansci_pdf', 'sources', '__init__.py'), '')
writeFileSync(join(fakeRoot, 'scansci_pdf', 'sources', 'arxiv.py'), 'def download_arxiv_pdf(url,output_path,config): return None\n')
writeFileSync(join(fakeRoot, 'scansci_pdf', 'main.py'), 'import json,os,sys\ndef app(args=None,standalone_mode=True):\n args=args or sys.argv[1:]; out=args[args.index("--output")+1]; p=os.path.join(out,"download.pdf"); open(p,"wb").write(b"%PDF-1.4\\n"+b"x"*1200+b"\\n%%EOF"); print(json.dumps({"status":"success","quality":"legal","paper":{"pdf_path":p}}))\n')
writeFileSync(join(fakeRoot, 'scientific_reading', '__main__.py'), [
  'import json, os, sys',
  'a=sys.argv[1:]; cmd=next((x for x in a if x in {"full-read-pipeline-start","full-read-pipeline-resume","full-read-pdf-attach-resume","pdf-attach","export-assets","artifact-resolve","library-item-v2","job-status"}), "")',
  `log=${JSON.stringify(log)}`,
  'with open(log,"a",encoding="utf-8") as f: f.write(json.dumps(a)+"\\n")',
  'pid=a[a.index("--paper-id")+1] if "--paper-id" in a else "title_fixture"',
  'if cmd=="full-read-pipeline-start": print(json.dumps({"parent_job_id":"job_0123456789abcdef"}))',
  'elif cmd=="full-read-pipeline-resume": print(json.dumps({"parent_job_id":"job_0123456789abcdef","state":"queued"}))',
  'elif cmd=="pdf-attach": print(json.dumps({"status":"pdf_ready","detail":{"sha256":"' + 'c'.repeat(64) + '","page_count":3,"source_path":"C:/secret/source.pdf"}}))',
  'elif cmd=="full-read-pdf-attach-resume": print(json.dumps({"status":"queued","parent_job_id":"job_0123456789abcdef","sha256":"' + 'c'.repeat(64) + '","page_count":3}))',
  'elif cmd=="export-assets": print(json.dumps({"status":"exported"}))',
  'elif cmd=="library-item-v2": print(json.dumps({"paper_id":pid,"active_job_id":"job_0123456789abcdef"}))',
  'elif cmd=="job-status": print(json.dumps({"paper_id":pid,"status":"waiting_user","detail":{"reason_code":"pdf_required"}}))',
  `elif cmd=="artifact-resolve" and pid=="title_traversal": print(json.dumps({"rel_path":"../secret"}))`,
  `elif cmd=="artifact-resolve" and a[a.index("--kind")+1]=="reader": print(json.dumps({"rel_path":"generations/${generation}/reading/reader.html","manifest":{"reader_sha256":"${readerSha}"}}))`,
  `else: print(json.dumps({"rel_path":"generations/${generation}/exports","manifest":{"contract":"asset-export-v1","paper_id":pid,"source_pdf_sha256":"${'b'.repeat(64)}","assets":[{"export_path":"figures/Fig_01.png","export_sha256":"${assetSha}"}]}}))`,
].join('\n'))
const python = execFileSync('where.exe', ['python'], { encoding: 'utf8' }).split(/\r?\n/).find((x) => x.trim().toLowerCase().endsWith('.exe')).trim()
const oldPath = process.env.PYTHONPATH
process.env.PYTHONPATH = oldPath ? fakeRoot + delimiter + oldPath : fakeRoot
const oldScansciRoot = process.env.SCANSCI_PDF_DATA_DIR
process.env.SCANSCI_PDF_DATA_DIR = join(fixture, 'scansci-config')
const routes = []
registerRoutes({ effect(fn) { fn() }, logger() {}, webServer: { register(r) { routes.push(r); return () => {} } } }, { dataRoot: join(fixture, 'data'), python: 'python', scansciExe: 'untrusted.exe', school: '', legalOnly: true, outputDir: '', loginType: 'carsi', scansciPython: python, enginePython: python, feishuConfig: '' })
const prefix = (path) => routes.find((r) => r.kind === 'prefix' && r.path === path)
const req = (method, url, value = {}) => { const body = JSON.stringify(value); return { method, url, on(event, cb) { if (event === 'data') cb(Buffer.from(body)); if (event === 'end') queueMicrotask(cb) } } }
const res = () => ({ statusCode: 0, body: '', writeHead(s, h) { this.statusCode = s; this.headers = h }, end(v = '') { this.body = Buffer.isBuffer(v) ? v : String(v) } })

try {
  for (const [url, body] of [[`/sr/api/paper/${paperId}/start`, {}], [`/sr/api/paper/${paperId}/export`, {}]]) {
    const out = res(); await prefix('/sr/api/paper').handler(req('POST', url, body), out); assert.equal(out.statusCode, 200)
  }
  const continued = res(); await prefix('/sr/api/job').handler(req('POST', '/sr/api/job/job_0123456789abcdef/continue', {}), continued); assert.equal(continued.statusCode, 200)
  const badJob = res(); await prefix('/sr/api/job').handler(req('POST', '/sr/api/job/not-a-job/continue', {}), badJob); assert.equal(badJob.statusCode, 404)
  const payload = { pdf_b64: Buffer.alloc(1200, 1).toString('base64'), job_id: 'job_0123456789abcdef' }
  const a = res(), b = res(); await prefix('/sr/api/paper').handler(req('POST', `/sr/api/paper/${paperId}/attach`, payload), a); await prefix('/sr/api/paper').handler(req('POST', `/sr/api/paper/${paperId}/attach`, payload), b)
  assert.equal(a.statusCode, 200); assert.equal(b.statusCode, 200)
  for (const output of [a, b]) { const value = JSON.parse(output.body); assert.equal(value.parent_job_id, 'job_0123456789abcdef'); assert.equal(value.sha256, 'c'.repeat(64)); assert.equal('source_path' in value, false); assert.equal('pdf_path' in value, false); assert.equal('raw' in value, false) }
  const rows = readFileSync(log, 'utf8').trim().split(/\r?\n/).map(JSON.parse).filter((x) => x.includes('full-read-pdf-attach-resume'))
  const paths = rows.map((x) => x[x.indexOf('--pdf') + 1]); assert.equal(new Set(paths).size, 2); assert.ok(paths.every((x) => x.endsWith('.pdf') && !existsSync(x)))
  const atomicJobs = rows.map((x) => x[x.indexOf('--job-id') + 1]); assert.ok(atomicJobs.every((x) => x === 'job_0123456789abcdef'))
  const downloaded = res(); await prefix('/sr/api/paper').handler(req('POST', `/sr/api/paper/${paperId}/download`, { identifier: '10.1/fixture', job_id: 'job_0123456789abcdef' }), downloaded); assert.equal(downloaded.statusCode, 200); const safeDownload = JSON.parse(downloaded.body); assert.equal(safeDownload.parent_job_id, 'job_0123456789abcdef'); assert.equal('source_path' in safeDownload, false); assert.equal('pdf_path' in safeDownload, false); assert.equal('raw' in safeDownload, false)
  const traversal = res(); await prefix('/sr/api/paper').handler(req('GET', '/sr/api/paper/title_traversal/reader'), traversal); assert.equal(traversal.statusCode, 404)
  const readerOut = res(); await prefix('/sr/api/paper').handler(req('GET', `/sr/api/paper/${paperId}/reader`), readerOut); assert.equal(readerOut.statusCode, 200)
  const head = res(); await prefix('/sr/reader').handler(req('HEAD', `/sr/reader/${paperId}`), head); assert.equal(head.statusCode, 200); assert.equal(head.body, '')
  const method = res(); await prefix('/sr/reader').handler(req('POST', `/sr/reader/${paperId}`), method); assert.equal(method.statusCode, 405)
  writeFileSync(reader, '<!doctype html><p>tampered</p>')
  const tampered = res(); await prefix('/sr/api/paper').handler(req('GET', `/sr/api/paper/${paperId}/reader`), tampered); assert.equal(tampered.statusCode, 409)
  const manifest = res(); await prefix('/sr/api/paper').handler(req('GET', `/sr/api/paper/${paperId}/exports`), manifest); assert.equal(manifest.statusCode, 200)
  const download = res(); await prefix('/sr/api/paper').handler(req('GET', `/sr/api/paper/${paperId}/exports/figures/Fig_01.png`), download); assert.equal(download.statusCode, 200); assert.deepEqual(download.body, Buffer.from('fixture-png'))
  console.log('PASS: 精读动态路由、并发 attach 清理与资产 allowlist/SHA 合同')
} finally {
  if (oldPath === undefined) delete process.env.PYTHONPATH; else process.env.PYTHONPATH = oldPath
  if (oldScansciRoot === undefined) delete process.env.SCANSCI_PDF_DATA_DIR; else process.env.SCANSCI_PDF_DATA_DIR = oldScansciRoot
  rmSync(fixture, { recursive: true, force: true })
}
