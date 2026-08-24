import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { delimiter, join } from 'node:path'
import { tmpdir } from 'node:os'

import { registerRoutes } from '../lib/routes.js'

delete process.env.FEISHU_APP_ID
delete process.env.FEISHU_APP_SECRET
const python = execFileSync('where.exe', ['python'], { encoding: 'utf8' }).split(/\r?\n/).map((line) => line.trim()).find((line) => line.toLowerCase().endsWith('.exe'))
assert.ok(python)
const fixture = mkdtempSync(join(tmpdir(), 'sr-navigation-contract-'))
const fakeRoot = join(fixture, 'fake')
const dataRoot = join(fixture, 'data')
const logPath = join(fixture, 'engine.log')
const paperId = 'library_navigation'
const generation = 'a'.repeat(16)
const reader = '<!doctype html><p>canonical reader</p>'
const pdf = Buffer.from('%PDF-1.4\nfixture navigation pdf')
mkdirSync(join(fakeRoot, 'scientific_reading'), { recursive: true })
mkdirSync(join(dataRoot, 'papers', paperId, 'generations', generation, 'reading'), { recursive: true })
mkdirSync(join(dataRoot, 'papers', paperId, 'generations', generation), { recursive: true })
writeFileSync(join(dataRoot, 'papers', paperId, 'generations', generation, 'reading', 'reader.html'), reader, 'utf8')
writeFileSync(join(dataRoot, 'papers', paperId, 'generations', generation, 'source.pdf'), pdf)
writeFileSync(join(fakeRoot, 'scientific_reading', '__init__.py'), '', 'utf8')
writeFileSync(join(fakeRoot, 'scientific_reading', '__main__.py'), [
  'import json, sys',
  'a=sys.argv[1:]',
  `open(${JSON.stringify(logPath)}, "a", encoding="utf-8").write(json.dumps(a) + "\\n")`,
  'cmd=next((x for x in a if x in {"library-list-v2","folder-list","library-item-v2","artifact-resolve","full-read-pipeline-start","export-assets","job-status"}), "")',
  `pid=${JSON.stringify(paperId)}`,
  `gen=${JSON.stringify(generation)}`,
  `reader_sha=${JSON.stringify(createHash('sha256').update(reader).digest('hex'))}`,
  `pdf_sha=${JSON.stringify(createHash('sha256').update(pdf).digest('hex'))}`,
  'if cmd=="library-list-v2": print(json.dumps({"items":[{"paper_id":pid,"title":"Navigation","authors_short":"A et al.","year":2024,"folder":None,"tags":["NLP"],"abstract_status":"ready","full_read_status":"not_started","feishu_sync_state":"synced","has_pdf":True,"has_reader":True,"feishu_record_url":"https://example.invalid/record","last_error":"","abstract_en":"SECRET ABSTRACT","required_input":{"secret":"TOKEN"},"unexpected":"drop"},{"paper_id":"library_sparse"}],"page":1,"page_size":50,"total":2,"jobs":{"running":0,"queued":0},"required_input":{"secret":"TOKEN"}}))',
  'elif cmd=="folder-list": print(json.dumps([]))',
  'elif cmd=="library-item-v2": print(json.dumps({"paper_id":pid,"title":"Navigation","abstract_en":"English","abstract_zh":"中文","abstract_status":"ready","feishu_record_url":"https://example.invalid/record"}))',
  'elif cmd=="artifact-resolve":',
  '  kind=a[a.index("--kind")+1]',
  '  if kind=="reader": print(json.dumps({"rel_path":f"generations/{gen}/reading/reader.html","sha256":reader_sha}))',
  '  elif kind=="pdf": print(json.dumps({"rel_path":f"generations/{gen}/source.pdf","sha256":pdf_sha}))',
  '  else: print(json.dumps({"rel_path":f"generations/{gen}/exports","manifest":{"assets":[]}}))',
  'elif cmd=="full-read-pipeline-start": print(json.dumps({"parent_job_id":"job_0123456789abcdef"}))',
  'elif cmd=="export-assets": print(json.dumps({"parent_job_id":"job_fedcba9876543210","status":"queued"}))',
  'elif cmd=="job-status":',
  '  jid=a[a.index("--job-id")+1]',
  '  if jid=="job_fedcba9876543210": print("engine SECRET traceback", file=sys.stderr); sys.exit(1)',
  '  print(json.dumps({"job_id":jid,"status":"running","required_input":{"kind":"gate"}}))',
].join('\n'), 'utf8')
const oldPythonPath = process.env.PYTHONPATH
process.env.PYTHONPATH = oldPythonPath ? fakeRoot + delimiter + oldPythonPath : fakeRoot

const routes = []
const ctx = { effect(fn) { fn() }, logger() {}, webServer: { register(route) { routes.push(route); return () => {} } } }
const config = { dataRoot, python: 'python', scansciExe: 'scansci-pdf', school: '', legalOnly: true, outputDir: '', loginType: 'carsi', scansciPython: '', enginePython: python, feishuConfig: '' }
const response = () => ({ statusCode: 0, headers: {}, body: '', writeHead(status, headers) { this.statusCode = status; this.headers = headers }, end(body = '') { this.body = body } })
const findRoute = (path) => { const route = routes.find((item) => item.path === path && (!['/sr/api/paper', '/sr/api/job'].includes(path) || item.kind === 'prefix')); assert.ok(route, `缺少路由 ${path}`); return route }
const request = (method, url, body = '') => ({ method, url, on(event, cb) { if (event === 'data' && body) cb(Buffer.from(body)); if (event === 'end') queueMicrotask(cb) } })
async function call(path, method, url, body = '') { const res = response(); await findRoute(path).handler(request(method, url, body), res); return res }

try {
  registerRoutes(ctx, config)

  const list = await call('/sr/api/library', 'GET', '/sr/api/library?page=1&page_size=50&q=cell&folder=&tags=NLP&status=&recent_days=7')
  assert.equal(list.statusCode, 200)
  assert.deepEqual(JSON.parse(list.body), {
    items: [
      { paper_id: paperId, title: 'Navigation', authors_short: 'A et al.', year: 2024, folder: null, tags: ['NLP'], abstract_status: 'ready', full_read_status: 'not_started', feishu_sync_state: 'synced', has_pdf: true, has_reader: true, feishu_record_url: 'https://example.invalid/record', last_error: '' },
      { paper_id: 'library_sparse', title: '', authors_short: '', year: null, folder: null, tags: [], abstract_status: '', full_read_status: '', feishu_sync_state: '', has_pdf: false, has_reader: false, feishu_record_url: '', last_error: '' },
    ],
    page: 1, page_size: 50, total: 2, jobs: { running: 0, queued: 0 },
  })
  const listArgs = readFileSync(logPath, 'utf8').split(/\r?\n/).filter(Boolean).map(JSON.parse)[0]
  assert.deepEqual(listArgs.slice(listArgs.indexOf('library-list-v2')), ['library-list-v2', '--page', '1', '--page-size', '50', '--query', 'cell', '--tag', 'NLP', '--recent-days', '7'])

  for (const url of ['/sr/api/library?page=0', '/sr/api/library?page=1.5', '/sr/api/library?page_size=0', '/sr/api/library?page_size=101', '/sr/api/library?recent_days=-1']) {
    assert.equal((await call('/sr/api/library', 'GET', url)).statusCode, 400, url)
  }
  assert.equal((await call('/sr/api/library', 'PUT', '/sr/api/library')).statusCode, 405)
  assert.equal((await call('/sr/api/folders', 'DELETE', '/sr/api/folders')).statusCode, 405)

  const detail = await call('/sr/api/paper', 'GET', `/sr/api/paper/${paperId}`)
  assert.equal(detail.statusCode, 200)
  assert.equal(JSON.parse(detail.body).item.feishu_record_url, 'https://example.invalid/record')
  const abstract = await call('/sr/api/paper', 'GET', `/sr/api/paper/${paperId}/abstract`)
  assert.deepEqual(JSON.parse(abstract.body), { paper_id: paperId, abstract_en: 'English', abstract_zh: '中文', status: 'ready', active_job_id: null, last_error: null })
  const pdfOut = await call('/sr/api/paper', 'GET', `/sr/api/paper/${paperId}/pdf`)
  assert.equal(pdfOut.statusCode, 200)
  assert.deepEqual(Buffer.from(pdfOut.body), pdf)
  assert.match(pdfOut.headers['Content-Type'], /^application\/pdf/)
  assert.equal((await call('/sr/api/paper', 'POST', `/sr/api/paper/${paperId}/full-read`, '{}')).statusCode, 200)
  assert.equal((await call('/sr/api/paper', 'POST', `/sr/api/paper/${paperId}/export-assets`, '{}')).statusCode, 200)
  assert.equal((await call('/sr/api/paper', 'POST', `/sr/api/paper/${paperId}/abstract`, '{}')).statusCode, 405)
  assert.equal((await call('/sr/api/paper', 'GET', `/sr/api/paper/${paperId}/full-read`)).statusCode, 405)

  for (const url of ['/sr/api/paper/../../secret', '/sr/api/paper/%2e%2e%2fsecret', '/sr/api/paper/library_navigation/pdf/extra']) {
    assert.equal((await call('/sr/api/paper', 'GET', url)).statusCode, 404, url)
  }
  const job = await call('/sr/api/job', 'GET', '/sr/api/job/job_0123456789abcdef')
  assert.equal(job.statusCode, 200)
  assert.deepEqual(JSON.parse(job.body).required_input, { kind: 'gate' })
  const failedJob = await call('/sr/api/job', 'GET', '/sr/api/job/job_fedcba9876543210')
  assert.equal(failedJob.statusCode, 502)
  assert.equal(JSON.stringify(JSON.parse(failedJob.body)).includes('SECRET'), false)
  assert.equal(JSON.stringify(JSON.parse(failedJob.body)).toLowerCase().includes('traceback'), false)
  assert.equal((await call('/sr/api/job', 'POST', '/sr/api/job/job_0123456789abcdef', '{}')).statusCode, 405)
  assert.equal((await call('/sr/api/job', 'GET', '/sr/api/job/job_0123456789abcdef/extra')).statusCode, 404)

  console.log('PASS: 导航 HTTP 合同固定分页、详情、资产、方法与安全边界')
} finally {
  if (oldPythonPath === undefined) delete process.env.PYTHONPATH
  else process.env.PYTHONPATH = oldPythonPath
  rmSync(fixture, { recursive: true, force: true })
}
