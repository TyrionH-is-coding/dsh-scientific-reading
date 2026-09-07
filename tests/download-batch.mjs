import { python } from './python-runtime.mjs'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { delimiter, join } from 'node:path'

import { readDownloadJob, runDownloadBatch } from '../lib/download_batch.js'
import { registerLibraryTools } from '../lib/library_tools.js'
import { registerRoutes } from '../lib/routes.js'

const papers = new Map(Array.from({ length: 20 }, (_, index) => {
  const number = index + 1
  return [`p${number}`, { paper_id: `p${number}`, doi: `10.1000/${number}` }]
}))
const existing = new Set(['p1', 'p3', 'p5'])
let chromeLaunches = 0
const direct = new Set(['p2', 'p4', 'p6', 'p8', 'p10'])
const chrome = new Set(['p11', 'p12'])
const challenges = new Set(['p7', 'p9'])

const result = await runDownloadBatch([...papers.keys()], {
  async loadPaper(id) { return papers.get(id) },
  async hasPdf(id) { return existing.has(id) },
  async directFetch(id) {
    if (direct.has(id)) return { status: 'completed', pdfPath: `C:/tmp/${id}.pdf` }
    if (challenges.has(id)) return { status: 'anti_automation_challenge' }
    return { status: 'remaining' }
  },
  async openInstitutionSession() { chromeLaunches += 1; return { status: 'ready' } },
  async institutionFetch(id) {
    if (chrome.has(id)) return { status: 'completed', pdfPath: `C:/tmp/${id}.pdf` }
    if (challenges.has(id)) return { status: 'anti_automation_challenge' }
    return { status: 'manual_required' }
  },
  async attachPdf() { return { status: 'completed' } },
})

assert.equal(result.summary.skipped_existing, 3)
assert.equal(chromeLaunches, 0, 'OA 失败不能启动机构会话')
assert.equal(result.summary.manual_required, 12)
assert.deepEqual(result.challengePaperIds, [])
assert.equal(result.children.find((item) => item.paperId === 'p11').status, 'manual_required')
assert.equal(result.children.find((item) => item.paperId === 'p2').status, 'completed')
assert.equal(result.children.length, 20)

const noRemaining = await runDownloadBatch(['p1'], {
  async loadPaper(id) { return papers.get(id) }, async hasPdf() { return true },
  async directFetch() { throw new Error('不得下载') },
  async openInstitutionSession() { throw new Error('不得启动 Chrome') },
  async institutionFetch() { throw new Error('不得下载') }, async attachPdf() { throw new Error('不得挂接') },
})
assert.equal(noRemaining.summary.skipped_existing, 1)

await assert.rejects(() => runDownloadBatch(Array.from({ length: 101 }, (_, i) => `p${i}`), {}), /download_batch_too_large/)

const isolated = await runDownloadBatch(['unreadable', 'bad-attachment', 'ready'], {
  async loadPaper(id) {
    if (id === 'unreadable') throw new Error('library read failed')
    return { paper_id: id, doi: '10.1000/example' }
  },
  async hasPdf(id) {
    if (id === 'bad-attachment') throw new Error('attachment lookup failed')
    return false
  },
  async directFetch(id) { return { status: 'completed', pdfPath: `C:/tmp/${id}.pdf` } },
  async attachPdf() { return { status: 'completed' } },
  async openInstitutionSession() { throw new Error('不得启动 Chrome') },
  async institutionFetch() { throw new Error('不得下载') },
})
assert.deepEqual(isolated.children.map(({ paperId, status }) => ({ paperId, status })), [
  { paperId: 'unreadable', status: 'failed' },
  { paperId: 'bad-attachment', status: 'failed' },
  { paperId: 'ready', status: 'completed' },
])
assert.equal(isolated.summary.failed, 2)
assert.equal(isolated.summary.completed, 1)

const fixture = mkdtempSync(join(tmpdir(), 'sr-download-recovery-'))
const dataRoot = join(fixture, 'data')
const jobsRoot = join(dataRoot, 'jobs', 'downloads')
const fakeRoot = join(fixture, 'fake')
const saveLog = join(fixture, 'download-save.jsonl')

assert.ok(python)
mkdirSync(join(fakeRoot, 'scientific_reading'), { recursive: true })
writeFileSync(join(fakeRoot, 'scientific_reading', '__init__.py'), '', 'utf8')
writeFileSync(join(fakeRoot, 'scientific_reading', '__main__.py'), [
  'import json, os, pathlib, sys',
  'args=sys.argv[1:]; payload=json.load(sys.stdin)',
  `open(${JSON.stringify(saveLog)}, "a", encoding="utf-8").write(json.dumps({"args":args,"payload":payload}) + "\\n")`,
  'job_id=args[args.index("--job-id")+1]',
  'if os.environ.get("SR_TEST_DOWNLOAD_SAVE_FAIL") == "1": print(json.dumps({"status":"failed","error":"backup_in_progress"})); raise SystemExit(4)',
  'data_root=pathlib.Path(args[args.index("--data-root")+1])',
  'target=data_root / "jobs" / "downloads" / (job_id + ".json")',
  'target.parent.mkdir(parents=True, exist_ok=True)',
  'target.write_text(json.dumps(payload), encoding="utf-8")',
  'print(json.dumps({"status":"saved","job_id":job_id}))',
].join('\n'), 'utf8')
const oldPythonPath = process.env.PYTHONPATH
process.env.PYTHONPATH = oldPythonPath ? fakeRoot + delimiter + oldPythonPath : fakeRoot
const config = { dataRoot, python: 'python', scansciExe: 'scansci-pdf', school: '', legalOnly: true, outputDir: '', loginType: 'carsi', scansciPython: '', enginePython: python }
const writeJob = (jobId, value) => {
  mkdirSync(jobsRoot, { recursive: true })
  writeFileSync(join(jobsRoot, jobId + '.json'), JSON.stringify({ parent_job_id: jobId, selection: ['p1'], ...value }), 'utf8')
}

try {
  const legacyJobId = 'job_1000000000000001'
  writeJob(legacyJobId, { status: 'queued' })
  const legacy = await readDownloadJob(config, legacyJobId)
  assert.equal(legacy.status, 'failed')
  assert.equal(legacy.next_action, 'user')
  assert.equal(legacy.job_id, legacyJobId)
  assert.equal(legacy.detail.reason_code, 'download_process_restarted')
  assert.deepEqual(legacy.selection, ['p1'])
  assert.equal(JSON.parse(readFileSync(join(jobsRoot, legacyJobId + '.json'), 'utf8')).status, 'failed')
  const firstSave = readFileSync(saveLog, 'utf8').trim().split(/\r?\n/).map(JSON.parse)[0]
  assert.deepEqual(firstSave.args.slice(-3), ['download-job-save', '--job-id', legacyJobId])
  assert.equal(firstSave.payload.status, 'failed')
  assert.equal(firstSave.payload.detail.reason_code, 'download_process_restarted')

  const failedSaveJobId = 'job_1000000000000008'
  writeJob(failedSaveJobId, { status: 'running', owner_pid: 2147483647 })
  process.env.SR_TEST_DOWNLOAD_SAVE_FAIL = '1'
  await assert.rejects(() => readDownloadJob(config, failedSaveJobId), /download_job_save_failed/)
  delete process.env.SR_TEST_DOWNLOAD_SAVE_FAIL
  assert.equal(JSON.parse(readFileSync(join(jobsRoot, failedSaveJobId + '.json'), 'utf8')).status, 'running', '引擎拒绝保存时不得伪报 failed 已落盘')

  const deadJobId = 'job_1000000000000002'
  writeJob(deadJobId, { status: 'running', owner_pid: 2147483647 })
  const dead = await readDownloadJob(config, deadJobId)
  assert.equal(dead.status, 'failed')
  assert.equal(dead.next_action, 'user')
  assert.equal(dead.detail.reason_code, 'download_process_restarted')

  const concurrentJobId = 'job_1000000000000007'
  writeJob(concurrentJobId, { status: 'running' })
  const concurrent = await Promise.all(Array.from({ length: 8 }, () => readDownloadJob(config, concurrentJobId)))
  assert.ok(concurrent.every((job) => job?.status === 'failed' && job.next_action === 'user'), '并发查询重启任务不能丢失状态')
  assert.equal(JSON.parse(readFileSync(join(jobsRoot, concurrentJobId + '.json'), 'utf8')).status, 'failed')

  const liveJobId = 'job_1000000000000003'
  writeJob(liveJobId, { status: 'running', owner_pid: process.pid })
  const live = await readDownloadJob(config, liveJobId)
  assert.equal(live.status, 'running')
  assert.equal(live.next_action, 'poll')
  assert.equal(live.job_id, liveJobId)

  const completedJobId = 'job_1000000000000004'
  writeJob(completedJobId, { status: 'completed', summary: { completed: 1, skipped_existing: 0, failed: 0, manual_required: 0, anti_automation_challenge: 0 } })
  assert.equal((await readDownloadJob(config, completedJobId)).next_action, 'done')

  const partialJobId = 'job_1000000000000005'
  writeJob(partialJobId, { status: 'completed', summary: { completed: 0, skipped_existing: 0, failed: 1, manual_required: 1, anti_automation_challenge: 0 } })
  assert.equal((await readDownloadJob(config, partialJobId)).next_action, 'user')

  const failedJobId = 'job_1000000000000006'
  writeJob(failedJobId, { status: 'failed' })
  assert.equal((await readDownloadJob(config, failedJobId)).next_action, 'user')

  const routes = []
  registerRoutes({ effect(fn) { fn() }, logger() {}, webServer: { register(route) { routes.push(route); return () => {} } } }, config)
  const response = () => ({ statusCode: 0, body: '', writeHead(status) { this.statusCode = status }, end(body = '') { this.body = String(body) } })
  const request = (url) => ({ method: 'GET', url, on() {} })
  const callRoute = async (path, url) => {
    const route = routes.find((item) => item.kind === 'prefix' && item.path === path)
    assert.ok(route)
    const res = response()
    await route.handler(request(url), res)
    assert.equal(res.statusCode, 200)
    return JSON.parse(res.body)
  }
  const directRoute = await callRoute('/sr/api/download-batch', `/sr/api/download-batch/${partialJobId}`)
  const genericRoute = await callRoute('/sr/api/job', `/sr/api/job/${partialJobId}`)
  assert.deepEqual(directRoute, genericRoute)
  assert.equal(directRoute.job_id, partialJobId)
  assert.equal(directRoute.next_action, 'user')

  const tools = []
  registerLibraryTools({ effect(fn) { fn() }, logger() {}, tools: { register(tool) { tools.push(tool); return () => {} } } }, config)
  const statusTool = tools.find((tool) => tool.name === 'sr_job_status')
  assert.ok(statusTool)
  const toolValue = await statusTool.execute({ job_id: partialJobId })
  const rendered = statusTool.output.render({}, toolValue).map((block) => block.text).join('\n')
  assert.match(rendered, new RegExp(partialJobId))
  assert.match(rendered, /next_action=user/)
  assert.doesNotMatch(rendered, /undefined/)
} finally {
  delete process.env.SR_TEST_DOWNLOAD_SAVE_FAIL
  if (oldPythonPath === undefined) delete process.env.PYTHONPATH
  else process.env.PYTHONPATH = oldPythonPath
  rmSync(fixture, { recursive: true, force: true })
}
console.log('PASS: 批量仅获取 OA，失败等待本地 PDF，预检查异常和重启不阻塞其他条目')
