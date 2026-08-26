import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const source = readFileSync(join(root, 'client', 'client.js'), 'utf8')
function loadNamedFunction(name) {
  const start = source.indexOf(`function ${name}(`)
  assert.notEqual(start, -1, `缺少可测试函数：${name}`)
  const bodyStart = source.indexOf('{', start)
  let depth = 0
  for (let i = bodyStart; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1
    if (source[i] === '}') depth -= 1
    if (depth === 0) return Function(`return (${source.slice(start, i + 1)})`)()
  }
}

const isSafeHttpUrl = loadNamedFunction('isSafeHttpUrl')
const pairAbstractParagraphs = loadNamedFunction('pairAbstractParagraphs')
const paperEntryModel = loadNamedFunction('paperEntryModel')
const createPaperActionController = loadNamedFunction('createPaperActionController')
const createDrawerSessionController = loadNamedFunction('createDrawerSessionController')
const nextDialogFocus = loadNamedFunction('nextDialogFocus')
const createLiteratureLifecycle = loadNamedFunction('createLiteratureLifecycle')

assert.equal(isSafeHttpUrl('https://example.test/record'), true)
assert.equal(isSafeHttpUrl('http://example.test/record'), true)
for (const malicious of ['javascript:alert(1)', 'data:text/html,bad', 'file:///secret', '//example.test']) assert.equal(isSafeHttpUrl(malicious), false)
assert.deepEqual(pairAbstractParagraphs('English one.\n\nEnglish two.', '中文一。\n\n中文二。'), [
  { en: 'English one.', zh: '中文一。' }, { en: 'English two.', zh: '中文二。' },
])
assert.deepEqual(pairAbstractParagraphs('', ''), [])

const disabled = paperEntryModel({ abstract_status: 'missing', has_pdf: false, has_reader: false, feishu_sync_state: 'unconfigured', feishu_record_url: '' }, isSafeHttpUrl)
assert.equal(disabled.quick.disabledReason, '待补摘要')
assert.equal(disabled.pdf.disabledReason, '尚无 PDF 原件')
assert.equal(disabled.reader.label, '开始精读')
assert.equal(disabled.feishu.label, '飞书未配置')
const ready = paperEntryModel({ abstract_status: 'ready', has_pdf: true, has_reader: true, feishu_sync_state: 'synced', feishu_record_url: 'https://example.test/r' }, isSafeHttpUrl)
assert.equal(paperEntryModel({ abstract_status: 'completed' }, isSafeHttpUrl).quick.disabledReason, '', 'worker completed 状态也必须可浅读')
assert.equal(paperEntryModel({ full_read_status: 'running' }, isSafeHttpUrl).reader.disabledReason, '精读已排队或处理中')
for (const status of ['精读排队', '获取 PDF', '解析全文', '翻译与生成', '需要用户处理', 'queued', 'running', 'needs_user', 'waiting_user']) {
  assert.equal(paperEntryModel({ full_read_status: status }, isSafeHttpUrl).reader.disabledReason, '精读已排队或处理中', status)
}
for (const status of ['精读完成', 'completed', 'full_read_ready']) {
  assert.equal(paperEntryModel({ full_read_status: status, has_reader: false }, isSafeHttpUrl).reader.disabledReason, '精读 HTML 待校验', status)
}
assert.equal(paperEntryModel({ full_read_status: '处理失败' }, isSafeHttpUrl).reader.disabledReason, '', '失败状态允许从更多菜单重试而非 busy')
assert.equal(ready.reader.href, '/sr/reader/')
assert.equal(ready.feishu.href, 'https://example.test/r')
assert.equal(paperEntryModel({ feishu_sync_state: 'synced', feishu_record_url: 'javascript:alert(1)' }, isSafeHttpUrl).feishu.href, '')

const calls = []
const scheduled = []
const patches = []
let detailResolve
const fakeApi = (path, options = {}) => {
  calls.push([path, options.method || 'GET', options.signal])
  if (path.endsWith('/full-read')) return Promise.resolve({ parent_job_id: 'job_0123456789abcdef' })
  if (path.includes('/job/')) return Promise.resolve({ status: 'waiting_user', detail: { reason_code: 'pdf_required' } })
  if (path.includes('/paper/')) return new Promise((resolve) => { detailResolve = resolve })
  throw new Error(path)
}
const controller = createPaperActionController({
  api: fakeApi,
  schedule: (fn) => { scheduled.push(fn); return scheduled.length },
  cancel: () => {},
  onPatch: (id, patch) => patches.push([id, patch]),
  onRefresh: (id) => patches.push([id, { refreshed: true }]),
})
const first = controller.loadDetail('library_one')
const second = controller.loadDetail('library_one')
assert.equal(first, second, '题名与摘要必须共用一次详情加载')
detailResolve({ item: { title: 'Paper', abstract_en: 'EN', abstract_zh: '中', abstract_status: 'ready' }, outputs: [] })
assert.equal((await first).abstract.abstract_en, 'EN')
assert.equal(calls.filter(([path]) => path === '/sr/api/paper/library_one').length, 1)
assert.equal(calls.filter(([path]) => path.endsWith('/abstract')).length, 0, '详情不得额外启动 abstract 子进程')

await controller.startFullRead('library_one')
assert.deepEqual(patches[0], ['library_one', { full_read_status: 'queued', active_job_id: 'job_0123456789abcdef' }])
await scheduled.shift()()
assert.equal(patches.at(-1)[1].needsUser, true)
assert.equal(patches.at(-1)[1].pdfRequired, true)

const pending = controller.loadDetail('library_two')
controller.close()
assert.equal(calls.at(-1)[2].aborted, true, '关闭 drawer 必须中止详情请求')
controller.dispose()
assert.equal(calls.filter(([path]) => path.includes('/job/')).length, 1, '关闭后不得继续轮询')
void pending.catch(() => {})

let pollSignal
let finishJob
const scheduledPoll = []
const polling = createPaperActionController({
  api(path, options = {}) {
    if (path.endsWith('/full-read')) return Promise.resolve({ parent_job_id: 'job_1111111111111111' })
    if (path.includes('/job/')) { pollSignal = options.signal; return new Promise((resolve) => { finishJob = resolve }) }
  },
  schedule(fn) { scheduledPoll.push(fn); return scheduledPoll.length }, cancel() {}, onPatch() {}, onRefresh() {},
})
await polling.startFullRead('library_poll')
const inFlight = scheduledPoll.shift()()
polling.close()
assert.equal(pollSignal.aborted, true, '关闭时必须中止在途 job 请求')
finishJob({ status: 'completed' }); await inFlight

const exportCalls = []
const exportSchedules = []
let exportedAssets
const exporting = createPaperActionController({
  api(path) {
    exportCalls.push(path)
    if (path.endsWith('/export-assets')) return Promise.resolve({ parent_job_id: 'job_2222222222222222', status: 'queued' })
    if (path.includes('/job/')) return Promise.resolve({ status: 'completed' })
    if (path.endsWith('/assets')) return Promise.resolve({ figures: 2, tables: 1, exports_path: 'C:\\safe\\exports' })
  },
  schedule(fn) { exportSchedules.push(fn); return exportSchedules.length }, cancel() {}, onPatch() {}, onRefresh() {}, onAssets(id, assets) { exportedAssets = [id, assets] },
})
await exporting.exportAssets('library_export')
assert.equal(exportCalls.some((path) => path.endsWith('/assets')), false, 'queued export 完成前不得读取资产')
await exportSchedules.shift()()
assert.equal(exportCalls.at(-1), '/sr/api/paper/library_export/assets')
assert.equal(exportedAssets[1].figures, 2)

const failingSchedules = []
const failures = []
const failing = createPaperActionController({
  api(path) { if (path.endsWith('/full-read')) return Promise.resolve({ parent_job_id: 'job_3333333333333333' }); return Promise.reject(new Error('job_unavailable')) },
  schedule(fn) { failingSchedules.push(fn); return failingSchedules.length }, cancel() {}, onPatch(id, patch) { failures.push([id, patch]) }, onRefresh() {},
})
await failing.startFullRead('library_failure')
await failingSchedules.shift()()
assert.equal(failures.at(-1)[1].last_error, 'job_unavailable', '轮询失败必须转为可见安全错误而非未处理 rejection')

for (const action of ['full-read', 'export-assets']) {
  let resolveAction
  let actionSignal
  const latePatches = []
  const lateSchedules = []
  const late = createPaperActionController({
    api(path, options) { actionSignal = options.signal; return new Promise((resolve) => { resolveAction = resolve }) },
    schedule(fn) { lateSchedules.push(fn); return lateSchedules.length }, cancel() {}, onPatch(...args) { latePatches.push(args) }, onRefresh() {},
  })
  const pendingAction = action === 'full-read' ? late.startFullRead('library_late') : late.exportAssets('library_late')
  late.close()
  assert.equal(actionSignal.aborted, true, `关闭时必须中止在途 ${action}`)
  resolveAction({ parent_job_id: 'job_4444444444444444', status: 'queued' })
  await pendingAction
  assert.equal(latePatches.length, 0, `关闭后的 ${action} 响应不得更新行`)
  assert.equal(lateSchedules.length, 0, `关闭后的 ${action} 响应不得启动轮询`)
}

const exportFailureSchedules = []
const exportFailurePatches = []
const exportErrors = []
const exportFailure = createPaperActionController({
  api(path) { if (path.endsWith('/export-assets')) return Promise.resolve({ parent_job_id: 'job_5555555555555555' }); return Promise.resolve({ status: 'failed', error: 'export_failed' }) },
  schedule(fn) { exportFailureSchedules.push(fn); return exportFailureSchedules.length }, cancel() {}, onPatch(...args) { exportFailurePatches.push(args) }, onRefresh() {}, onAssetsError(id, error) { exportErrors.push([id, error]) },
})
await exportFailure.exportAssets('library_export_failure')
await exportFailureSchedules.shift()()
assert.deepEqual(exportErrors, [['library_export_failure', 'export_failed']])
assert.equal(exportFailurePatches.length, 0, '资产导出失败不得误标精读失败')

const invalidJob = createPaperActionController({ api() { return Promise.resolve({ parent_job_id: 'job_ABCDEF0123456789' }) }, schedule() { throw new Error('不得轮询') }, cancel() {}, onPatch() { throw new Error('不得更新') }, onRefresh() {} })
await assert.rejects(invalidJob.startFullRead('library_invalid_job'), /任务编号无效/)

assert.match(source, /job\.status === 'waiting_user'[^]*jobDetail\.reason_code === 'pdf_required'/, '持久重载必须从 detail job 恢复 PDF gate')
assert.match(source, /reader\.onload[^]*drawerSessions\.guard/, 'FileReader 晚回调必须经过 drawer session 门控')

const sessions = createDrawerSessionController()
const a = sessions.open('library_a')
const lateReader = { aborted: false, abort() { this.aborted = true } }
sessions.trackReader(a, 'library_a', lateReader)
sessions.close()
assert.equal(lateReader.aborted, true, 'close 必须 abort 正在读取的 FileReader')
const b = sessions.open('library_b')
assert.equal(sessions.guard(a, 'library_a', () => 'A'), undefined, 'A 晚响应不得覆盖 B')
assert.equal(sessions.guard(b, 'library_b', () => 'B'), 'B')
let lateAttach = 0
sessions.guard(a, 'library_a', () => { lateAttach += 1 })
assert.equal(lateAttach, 0, 'A 晚 FileReader 不得 attach 或关闭 B')

const focusables = [{ id: 'close' }, { id: 'pdf' }, { id: 'copy' }]
assert.equal(nextDialogFocus(focusables, focusables[2], false), focusables[0], 'Tab 从末尾循环到开头')
assert.equal(nextDialogFocus(focusables, focusables[0], true), focusables[2], 'Shift+Tab 从开头循环到末尾')

const lifecycleEvents = []
const lifecycleSessions = createDrawerSessionController()
const lifecycleReader = { abort() { lifecycleEvents.push('reader-abort') } }
const lifecycleToken = lifecycleSessions.open('library_lifecycle')
lifecycleSessions.trackReader(lifecycleToken, 'library_lifecycle', lifecycleReader)
const lifecycle = createLiteratureLifecycle(
  lifecycleSessions,
  { close() { lifecycleEvents.push('drawer-close') }, dispose() { lifecycleEvents.push('drawer-dispose') } },
  { close() { lifecycleEvents.push('row-close') }, dispose() { lifecycleEvents.push('row-dispose') } },
)
lifecycle.closeDrawerScope()
assert.deepEqual(lifecycleEvents, ['reader-abort', 'drawer-close'], '关闭 drawer 不得停止行级 parent polling')
lifecycleSessions.open('library_unmount')
lifecycleSessions.trackReader(lifecycleSessions.open('library_unmount'), 'library_unmount', lifecycleReader)
lifecycle.dispose()
assert.deepEqual(lifecycleEvents.slice(-3), ['reader-abort', 'drawer-dispose', 'row-dispose'], '组件 dispose 必须先失效 session/abort reader，再停止两类 controller')

const survivingSchedules = []
let survivingRefresh = 0
const rowPolling = createPaperActionController({
  api(path) { if (path.endsWith('/full-read')) return Promise.resolve({ parent_job_id: 'job_6666666666666666' }); return Promise.resolve({ status: 'completed' }) },
  schedule(fn) { survivingSchedules.push(fn); return survivingSchedules.length }, cancel() {}, onPatch() {}, onRefresh() { survivingRefresh += 1 },
})
const drawerOnly = { close() {}, dispose() {} }
const pollingLifecycle = createLiteratureLifecycle(createDrawerSessionController(), drawerOnly, rowPolling)
await rowPolling.startFullRead('library_survives_drawer')
pollingLifecycle.closeDrawerScope()
await survivingSchedules.shift()()
assert.equal(survivingRefresh, 1, '打开/关闭 drawer 后行级 parent polling 必须继续到 refresh')

console.log('PASS: 文献行、详情缓存、安全 URL 与单篇动作生命周期')
