import assert from 'node:assert/strict'

import { createReviewSessionOpener, registerReviewSessionRoutes } from '../lib/review_sessions.js'

const parent = (id, preset = 'scientific-reading') => ({
  id,
  session: { header: { id, agentPreset: preset } },
})

{
  let starts = 0
  const opener = createReviewSessionOpener({
    async readState() {
      return { status: 'bound', parent_session_id: 'parent-a', paper_id: 'library_a', review_session_id: 'child-a', title: 'Paper A' }
    },
    getParent() { throw new Error('reused binding must not require live parent') },
    async startContinuable() { starts += 1; throw new Error('must not start') },
    async bind() { throw new Error('must not bind') },
  }, 'scientific-reading')

  assert.deepEqual(await opener.open('parent-a', 'library_a'), {
    status: 'reused', parent_session_id: 'parent-a', paper_id: 'library_a',
    review_session_id: 'child-a', mode: 'continuable',
  })
  assert.equal(starts, 0)
}

{
  const seen = []
  const liveParent = parent('parent-a')
  const opener = createReviewSessionOpener({
    async readState() { return { status: 'missing', parent_session_id: 'parent-a', paper_id: 'library_a', title: 'Paper A' } },
    getParent(id) { assert.equal(id, 'parent-a'); return liveParent },
    async startContinuable(spec) { seen.push(spec); return { childId: 'child-created', messageId: 'message-a' } },
    async bind(parentSessionId, paperId, childId) {
      assert.deepEqual([parentSessionId, paperId, childId], ['parent-a', 'library_a', 'child-created'])
      return { status: 'created', parent_session_id: parentSessionId, paper_id: paperId, review_session_id: childId }
    },
  }, 'scientific-reading')

  const result = await opener.open('parent-a', 'library_a')
  assert.equal(result.status, 'created')
  assert.equal(result.review_session_id, 'child-created')
  assert.equal(seen[0].provider, 'fork')
  assert.equal(seen[0].label, 'Paper A')
  assert.equal(seen[0].request.parent, liveParent)
  const prompt = seen[0].request.prompt.map((block) => block.text || '').join('\n')
  assert.match(prompt, /library_a/)
  assert.match(prompt, /parent-a/)
  assert.match(prompt, /候选关键结论/)
  assert.match(prompt, /sr_review_confirm/)
}

{
  let resolveState
  let reads = 0
  let starts = 0
  const opener = createReviewSessionOpener({
    readState() {
      reads += 1
      return new Promise((resolve) => { resolveState = resolve })
    },
    getParent() { return parent('parent-a') },
    async startContinuable() { starts += 1; return { childId: 'child-a', messageId: 'message-a' } },
    async bind() { return { status: 'created', parent_session_id: 'parent-a', paper_id: 'library_a', review_session_id: 'child-a' } },
  }, 'scientific-reading')

  const first = opener.open('parent-a', 'library_a')
  const second = opener.open('parent-a', 'library_a')
  assert.equal(reads, 1)
  resolveState({ status: 'missing', parent_session_id: 'parent-a', paper_id: 'library_a', title: 'Paper A' })
  assert.deepEqual(await first, await second)
  assert.equal(starts, 1)
}

{
  const opener = createReviewSessionOpener({
    async readState() { return { status: 'missing', parent_session_id: 'ordinary', paper_id: 'library_a', title: 'Paper A' } },
    getParent() { return parent('ordinary', 'standard') },
    async startContinuable() { throw new Error('must not start') },
    async bind() { throw new Error('must not bind') },
  }, 'scientific-reading')
  await assert.rejects(() => opener.open('ordinary', 'library_a'), /parent_not_literature_session/)
}

{
  const routes = []
  const ctx = { effect(fn) { fn() }, webServer: { register(route) { routes.push(route); return () => {} } } }
  const opener = { async open() { return { status: 'reused', parent_session_id: 'parent-a', paper_id: 'library_a', review_session_id: 'child-a', mode: 'continuable' } } }
  registerReviewSessionRoutes(ctx, { presetId: 'scientific-reading' }, opener)
  const route = routes.find((item) => item.path === '/sr/api/reviews/open')
  assert.ok(route)
  const response = () => ({ statusCode: 0, body: '', writeHead(status) { this.statusCode = status }, end(body = '') { this.body = String(body) } })
  const request = (headers) => ({
    method: 'POST', url: '/sr/api/reviews/open', headers,
    on(event, callback) {
      if (event === 'data') callback(Buffer.from(JSON.stringify({ parent_session_id: 'parent-a', paper_id: 'library_a' })))
      if (event === 'end') queueMicrotask(callback)
    },
    destroy() {},
  })
  const denied = response()
  await route.handler(request({ host: 'localhost:3000', origin: 'https://evil.invalid', 'x-sr-csrf': '1' }), denied)
  assert.equal(denied.statusCode, 403)
  const allowed = response()
  await route.handler(request({ host: 'localhost:3000', origin: 'http://localhost:3000', 'x-sr-csrf': '1' }), allowed)
  assert.equal(allowed.statusCode, 200)
  assert.equal(JSON.parse(allowed.body).review_session_id, 'child-a')
}

console.log('PASS: 整理入口幂等创建真实 continuable 子会话并守住文献父会话边界')
