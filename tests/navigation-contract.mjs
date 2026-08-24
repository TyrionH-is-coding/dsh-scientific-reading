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
  'cmd=next((x for x in a if x in {"library-list-v2","folder-list","library-item-v2","artifact-resolve","full-read-pipeline-start","full-read-pipeline-resume","export-assets","job-status"}), "")',
  `pid=${JSON.stringify(paperId)}`,
  `gen=${JSON.stringify(generation)}`,
  `reader_sha=${JSON.stringify(createHash('sha256').update(reader).digest('hex'))}`,
  `pdf_sha=${JSON.stringify(createHash('sha256').update(pdf).digest('hex'))}`,
  'if cmd=="library-list-v2": print(json.dumps({"items":[{"paper_id":pid,"title":"Navigation","authors_short":"A et al.","year":2024,"folder":None,"tags":["NLP",7],"abstract_status":"ready","full_read_status":"not_started","feishu_sync_state":"synced","has_pdf":True,"has_reader":True,"feishu_record_url":"https://example.invalid/record","last_error":{"children":[{"stack":"Traceback","api_secret":"TOKEN"}]},"abstract_en":"SECRET ABSTRACT","required_input":{"secret":"TOKEN"},"unexpected":"drop"},{"paper_id":7,"title":{},"authors_short":[],"year":2024.5,"folder":9,"tags":"bad","abstract_status":{},"full_read_status":False,"feishu_sync_state":[],"has_pdf":"yes","has_reader":1,"feishu_record_url":{},"last_error":7}],"page":-4,"page_size":"bad","total":-1,"jobs":{"running":-2,"queued":"bad"},"required_input":{"secret":"TOKEN"}}))',
  'elif cmd=="folder-list": print(json.dumps([]))',
  'elif cmd=="library-item-v2": print(json.dumps({"paper_id":pid,"title":"Tokenization study","abstract_en":7,"abstract_zh":{},"abstract_status":False,"active_job_id":"job_0123456789abcdef","last_error":"Traceback SECRET token","message":"password leaked","nested":{"safe":"citation","stack":"Traceback","api_secret":"TOKEN"},"feishu_record_url":"https://example.invalid/record"}))',
  'elif cmd=="artifact-resolve":',
  '  kind=a[a.index("--kind")+1]',
  '  if kind=="reader": print(json.dumps({"rel_path":f"generations/{gen}/reading/reader.html","sha256":reader_sha}))',
  '  elif kind=="pdf": print(json.dumps({"rel_path":f"generations/{gen}/source.pdf","sha256":pdf_sha}))',
  '  elif kind=="exports": print(json.dumps({"rel_path":f"generations/{gen}/exports","manifest":{"assets":[]}}))',
  '  else: sys.exit(2)',
  'elif cmd=="full-read-pipeline-start": print(json.dumps({"parent_job_id":"job_0123456789abcdef"}))',
  'elif cmd=="full-read-pipeline-resume": print(json.dumps({"parent_job_id":"job_0123456789abcdef","state":"queued","required_input":{"kind":"gate","nested":{"safe":"ok","stack":"Traceback"},"message":"SECRET token"},"api_secret":"TOKEN"}))',
  'elif cmd=="export-assets": print(json.dumps({"parent_job_id":"job_fedcba9876543210","status":"queued"}))',
  'elif cmd=="job-status":',
  '  jid=a[a.index("--job-id")+1]',
  '  if jid=="job_fedcba9876543210": print("engine SECRET traceback", file=sys.stderr); sys.exit(1)',
  '  print(json.dumps({"job_id":jid,"status":"running","required_input":{"kind":"gate","nested":{"safe":"ok","stack":"Traceback"},"message":"SECRET token"},"api_secret":"TOKEN"}))',
].join('\n'), 'utf8')
const oldPythonPath = process.env.PYTHONPATH
process.env.PYTHONPATH = oldPythonPath ? fakeRoot + delimiter + oldPythonPath : fakeRoot

const routes = []
const ctx = { effect(fn) { fn() }, logger() {}, webServer: { register(route) { routes.push(route); return () => {} } } }
const config = { dataRoot, python: 'python', scansciExe: 'scansci-pdf', school: '', legalOnly: true, outputDir: '', loginType: 'carsi', scansciPython: '', enginePython: python, feishuConfig: '' }
const response = () => ({ statusCode: 0, headers: {}, body: '', writeHead(status, headers) { this.statusCode = status; this.headers = headers }, end(body = '') { this.body = body } })
const findRoute = (path) => { const route = routes.find((item) => item.path === path && (!['/sr/api/paper', '/sr/api/job'].includes(path) || item.kind === 'prefix')); assert.ok(route, `缺少路由 ${path}`); return route }
const request = (method, url, body = '') => ({ method, url, on(event, cb) { if (event === 'data' && body) cb(Buffer.isBuffer(body) ? body : Buffer.from(body)); if (event === 'end') queueMicrotask(cb) }, destroy() {} })
async function call(path, method, url, body = '') { const res = response(); await findRoute(path).handler(request(method, url, body), res); return res }

try {
  registerRoutes(ctx, config)

  const list = await call('/sr/api/library', 'GET', '/sr/api/library?page=1&page_size=50&q=cell&folder=&tags=NLP&status=&recent_days=7')
  assert.equal(list.statusCode, 200)
  assert.deepEqual(JSON.parse(list.body), {
    items: [
      { paper_id: paperId, title: 'Navigation', authors_short: 'A et al.', year: 2024, folder: null, tags: ['NLP'], abstract_status: 'ready', full_read_status: 'not_started', feishu_sync_state: 'synced', has_pdf: true, has_reader: true, feishu_record_url: 'https://example.invalid/record', last_error: '' },
      { paper_id: '', title: '', authors_short: '', year: null, folder: null, tags: [], abstract_status: '', full_read_status: '', feishu_sync_state: '', has_pdf: false, has_reader: false, feishu_record_url: '', last_error: '' },
    ],
    page: 1, page_size: 50, total: 2, jobs: { running: 0, queued: 0 },
  })
  assert.doesNotMatch(String(list.body), /traceback|secret|token|password/i)
  const listArgs = readFileSync(logPath, 'utf8').split(/\r?\n/).filter(Boolean).map(JSON.parse)[0]
  assert.deepEqual(listArgs.slice(listArgs.indexOf('library-list-v2')), ['library-list-v2', '--page', '1', '--page-size', '50', '--query', 'cell', '--tag', 'NLP', '--recent-days', '7'])

  for (const url of ['/sr/api/library?page=0', '/sr/api/library?page=1.5', '/sr/api/library?page_size=0', '/sr/api/library?page_size=101', '/sr/api/library?recent_days=-1']) {
    assert.equal((await call('/sr/api/library', 'GET', url)).statusCode, 400, url)
  }
  assert.equal((await call('/sr/api/library', 'PUT', '/sr/api/library')).statusCode, 405)
  assert.equal((await call('/sr/api/folders', 'DELETE', '/sr/api/folders')).statusCode, 405)

  const detail = await call('/sr/api/paper', 'GET', `/sr/api/paper/${paperId}`)
  assert.equal(detail.statusCode, 200)
  const detailBody = JSON.parse(detail.body)
  assert.equal(detailBody.item.title, 'Tokenization study')
  assert.equal(detailBody.item.feishu_record_url, 'https://example.invalid/record')
  assert.equal(detailBody.item.nested.safe, 'citation')
  assert.equal(detailBody.job.required_input.kind, 'gate')
  assert.equal(detailBody.job.required_input.nested.safe, 'ok')
  assert.doesNotMatch(String(detail.body), /traceback|secret|token(?!ization)|password/i)
  const abstract = await call('/sr/api/paper', 'GET', `/sr/api/paper/${paperId}/abstract`)
  assert.deepEqual(JSON.parse(abstract.body), { paper_id: paperId, abstract_en: null, abstract_zh: null, status: '', active_job_id: 'job_0123456789abcdef', last_error: 'redacted' })
  const pdfOut = await call('/sr/api/paper', 'GET', `/sr/api/paper/${paperId}/pdf`)
  assert.equal(pdfOut.statusCode, 200)
  assert.deepEqual(Buffer.from(pdfOut.body), pdf)
  assert.match(pdfOut.headers['Content-Type'], /^application\/pdf/)
  const pdfArgs = readFileSync(logPath, 'utf8').split(/\r?\n/).filter(Boolean).map(JSON.parse).filter((args) => args.includes('artifact-resolve'))
  assert.equal(pdfArgs.some((args) => args.includes('pdf')), true, 'PDF 必须通过引擎活动代次资产合同解析')
  assert.equal((await call('/sr/api/paper', 'POST', `/sr/api/paper/${paperId}/full-read`, '{}')).statusCode, 200)
  assert.equal((await call('/sr/api/paper', 'POST', `/sr/api/paper/${paperId}/export-assets`, '{}')).statusCode, 200)
  assert.equal((await call('/sr/api/paper', 'POST', `/sr/api/paper/${paperId}`, '{}')).statusCode, 405)
  assert.equal((await call('/sr/api/paper', 'POST', `/sr/api/paper/${paperId}/abstract`, '{}')).statusCode, 405)
  assert.equal((await call('/sr/api/paper', 'GET', `/sr/api/paper/${paperId}/full-read`)).statusCode, 405)

  for (const url of ['/sr/api/paper/../../secret', '/sr/api/paper/%2e%2e%2fsecret', '/sr/api/paper/library_navigation/pdf/extra']) {
    assert.equal((await call('/sr/api/paper', 'GET', url)).statusCode, 404, url)
  }
  const job = await call('/sr/api/job', 'GET', '/sr/api/job/job_0123456789abcdef')
  assert.equal(job.statusCode, 200)
  assert.deepEqual(JSON.parse(job.body).required_input, { kind: 'gate', nested: { safe: 'ok' }, message: 'redacted' })
  assert.equal(JSON.stringify(JSON.parse(job.body)).includes('TOKEN'), false)
  const continued = await call('/sr/api/job', 'POST', '/sr/api/job/job_0123456789abcdef/continue', '{}')
  assert.equal(continued.statusCode, 200)
  assert.deepEqual(JSON.parse(continued.body).required_input, { kind: 'gate', nested: { safe: 'ok' }, message: 'redacted' })
  assert.doesNotMatch(String(continued.body), /traceback|secret|token|password/i)
  assert.equal((await call('/sr/api/job', 'GET', '/sr/api/job/job_0123456789abcdef/continue')).statusCode, 405)
  const failedJob = await call('/sr/api/job', 'GET', '/sr/api/job/job_fedcba9876543210')
  assert.equal(failedJob.statusCode, 502)
  assert.equal(JSON.stringify(JSON.parse(failedJob.body)).includes('SECRET'), false)
  assert.equal(JSON.stringify(JSON.parse(failedJob.body)).toLowerCase().includes('traceback'), false)
  assert.equal((await call('/sr/api/job', 'POST', '/sr/api/job/job_0123456789abcdef', '{}')).statusCode, 405)
  assert.equal((await call('/sr/api/job', 'GET', '/sr/api/job/job_0123456789abcdef/extra')).statusCode, 404)

  for (const action of ['full-read', 'export-assets']) {
    const before = readFileSync(logPath, 'utf8').split(/\r?\n/).filter(Boolean).map(JSON.parse).filter((args) => args.includes(action === 'full-read' ? 'full-read-pipeline-start' : 'export-assets')).length
    assert.equal((await call('/sr/api/paper', 'POST', `/sr/api/paper/${paperId}/${action}`, Buffer.alloc(1024 * 1024 + 1))).statusCode, 413)
    assert.equal((await call('/sr/api/paper', 'POST', `/sr/api/paper/${paperId}/${action}`, '{')).statusCode, 400)
    const after = readFileSync(logPath, 'utf8').split(/\r?\n/).filter(Boolean).map(JSON.parse).filter((args) => args.includes(action === 'full-read' ? 'full-read-pipeline-start' : 'export-assets')).length
    assert.equal(after, before, `${action} 非法 body 不得调用引擎`)
  }

  console.log('PASS: 导航 HTTP 合同固定分页、详情、资产、方法与安全边界')
} finally {
  if (oldPythonPath === undefined) delete process.env.PYTHONPATH
  else process.env.PYTHONPATH = oldPythonPath
  rmSync(fixture, { recursive: true, force: true })
}
