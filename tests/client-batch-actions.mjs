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

const createSelectionStore = loadNamedFunction('createSelectionStore')
const createBatchController = loadNamedFunction('createBatchController')
const selection = createSelectionStore()
selection.toggle('paper_a', true)
selection.toggle('paper_b', true)
selection.replacePage(['paper_c', 'paper_d'])
assert.deepEqual(selection.values(), ['paper_a', 'paper_b'], '翻页不得丢失既有选择')
selection.toggle('paper_a', false)
assert.deepEqual(selection.values(), ['paper_b'])

let resolveMutation
const guardedSelection = createSelectionStore()
guardedSelection.toggle('paper_x', true)
let guardedNotices = 0
const guarded = createBatchController({
  selection: guardedSelection,
  api() { return new Promise((resolve) => { resolveMutation = resolve }) },
  onSummary() { guardedNotices += 1 },
})
const firstMutation = guarded.submit('queue_full_read', {})
await assert.rejects(guarded.submit('retry_failed', {}), /batch_action_in_progress/)
guardedSelection.toggle('paper_x', false)
guardedSelection.toggle('paper_x', true)
resolveMutation({ summary: { total: 1, created: 1, reused: 0, needs_user: 0, failed: 0 }, children: [{ paper_id: 'paper_x', status: 'created' }] })
await firstMutation
assert.deepEqual(guardedSelection.values(), ['paper_x'], '旧响应不得清除响应前重新选择的同一 paper')
assert.equal(guardedNotices, 1)

let resolveDisposed
const disposedSelection = createSelectionStore()
disposedSelection.toggle('paper_z', true)
let disposedNotices = 0
const disposedController = createBatchController({ selection: disposedSelection, api() { return new Promise((resolve) => { resolveDisposed = resolve }) }, onSummary() { disposedNotices += 1 } })
const disposedMutation = disposedController.submit('queue_full_read', {})
disposedController.dispose()
resolveDisposed({ summary: { total: 1, created: 1 }, children: [{ paper_id: 'paper_z', status: 'created' }] })
await disposedMutation
assert.deepEqual(disposedSelection.values(), ['paper_z'])
assert.equal(disposedNotices, 0, 'dispose 后晚响应不得更新选择或汇总')

const notices = []
const calls = []
const controller = createBatchController({
  selection,
  api(path, options) {
    calls.push([path, JSON.parse(options.body)])
    return Promise.resolve({
      summary: { total: 3, created: 1, reused: 0, needs_user: 1, failed: 1 },
      children: [
        { paper_id: 'paper_b', status: 'created' },
        { paper_id: 'paper_c', status: 'needs_user' },
        { paper_id: 'paper_d', status: 'failed' },
      ],
    })
  },
  onSummary(message) { notices.push(message) },
})
selection.toggle('paper_c', true)
selection.toggle('paper_d', true)
await controller.submit('queue_full_read', {})
assert.equal(calls.length, 1)
assert.deepEqual(calls[0][1].selection, ['paper_b', 'paper_c', 'paper_d'])
assert.deepEqual(selection.values(), ['paper_c', 'paper_d'], '成功项清空，失败与待处理项保留')
assert.equal(notices.length, 1, '父汇总只能生成一条提示')
assert.match(notices[0], /成功 1.*待处理 1.*失败 1/)

for (const label of ['已选 ', '移动文件夹', '添加标签', '移除标签', '加入精读队列', '重试失败任务', '重新同步飞书']) {
  assert.match(source, new RegExp(label), `缺少批量工具栏：${label}`)
}
assert.doesNotMatch(source, /批量删除/, '批量工具栏不得提供删除')
assert.match(source, /aria-live[^\n]*polite|setAttribute\('aria-live', 'polite'\)/, '父汇总必须是独立可访问 live region')
assert.match(source, /setAttribute\('role', 'status'\)/, '父汇总必须使用 status role')
assert.doesNotMatch(source, /AI.*分类算法|classifyInBrowser/, '浏览器不得实现 AI 分类算法')
console.log('PASS: 跨页选择、批量提交和单条父汇总合同')
