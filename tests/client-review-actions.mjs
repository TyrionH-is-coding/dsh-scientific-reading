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
  throw new Error(`函数未闭合：${name}`)
}

const createReviewSessionController = loadNamedFunction('createReviewSessionController')
const calls = []
let resolveOpen
const sessions = {
  list: { getSnapshot() { return { current: 'parent-literature' } } },
  refreshSubagents(parentSessionId) { calls.push(['refresh', parentSessionId]); return Promise.resolve() },
  openSubagent(spec) { calls.push(['open-subagent', spec]) },
}
const controller = createReviewSessionController({
  sessions,
  api(path, options) {
    calls.push(['api', path, options])
    return new Promise((resolve) => { resolveOpen = resolve })
  },
})

const first = controller.open('library_a')
const second = controller.open('library_a')
assert.equal(first, second, '同一父会话同一论文的连点必须合并为一次请求')
assert.equal(calls.filter(([kind]) => kind === 'api').length, 1)
const request = calls[0]
assert.equal(request[1], '/sr/api/reviews/open')
assert.equal(request[2].method, 'POST')
assert.equal(request[2].headers['x-sr-csrf'], '1')
assert.deepEqual(JSON.parse(request[2].body), {
  parent_session_id: 'parent-literature',
  paper_id: 'library_a',
})

resolveOpen({ review_session_id: 'child-review', mode: 'continuable' })
await first
assert.deepEqual(calls.slice(1), [
  ['refresh', 'parent-literature'],
  ['open-subagent', {
    parentSessionId: 'parent-literature',
    childSessionId: 'child-review',
    mode: 'continuable',
  }],
])

const missingParent = createReviewSessionController({
  sessions: { list: { getSnapshot() { return { current: undefined } } } },
  api() { throw new Error('不得请求') },
})
await assert.rejects(() => missingParent.open('library_a'), /literature_parent_session_required/)

assert.match(source, /整理入库/, '文献行必须显示整理入库按钮')
assert.match(source, /createMountController\(function \(\) \{ return renderLiterature\(ctx\.sessions\); \}\)/, '文献页必须使用当前 DSH sessions 服务')

console.log('PASS: 文献页整理入库会幂等打开当前父会话下的 continuable 子会话')
