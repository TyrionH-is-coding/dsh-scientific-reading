import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { registerReviewTools } from '../lib/review_tools.js'

const registered = []
const calls = []
const ctx = {
  effect(fn) { fn() },
  tools: { register(tool) { registered.push(tool); return () => {} } },
}
const config = { dataRoot: 'unused' }
registerReviewTools(ctx, config, {
  async context(_config, reviewSessionId) {
    calls.push(['context', reviewSessionId])
    return { ok: true, json: { review_session_id: reviewSessionId, paper: { paper_id: 'library_a' } }, stderr: '' }
  },
  async confirm(_config, reviewSessionId, conclusions) {
    calls.push(['confirm', reviewSessionId, conclusions])
    return { ok: true, json: { status: 'confirmed', inserted: conclusions.length }, stderr: '' }
  },
  async refreshXlsx() {
    calls.push(['xlsx-refresh'])
    return { ok: true, json: { status: 'success', path: 'library.xlsx' }, stderr: '' }
  },
  async locate(_config, input) {
    calls.push(['locate', input])
    return { ok: true, json: { contract: 'evidence-locator-v1', ...input }, stderr: '' }
  },
  async prepareCandidate(_config, input) {
    calls.push(['candidate-rebuild', input])
    return { ok: true, json: { status: 'pending', ...input }, stderr: '' }
  },
})

const byName = Object.fromEntries(registered.map((tool) => [tool.name, tool]))
assert.deepEqual(Object.keys(byName).sort(), [
  'sr_candidate_rebuild', 'sr_evidence_locate',
  'sr_review_confirm', 'sr_review_context',
])
assert.equal(Object.hasOwn(byName.sr_review_context.parameters, 'review_session_id'), false)
assert.equal(Object.hasOwn(byName.sr_review_confirm.parameters, 'review_session_id'), false)
const source = readFileSync(new URL('../src/review_tools.ts', import.meta.url), 'utf8')
for (const basis of ['paper', 'personal', 'inference', 'question', 'legacy']) {
  assert.match(source, new RegExp(`['"]${basis}['"]`))
}
for (const field of [
  'contract', 'paper_id', 'source_sha256', 'generation',
  'source_map_sha256', 'block_id', 'page', 'quote',
]) {
  assert.match(source, new RegExp(`${field}: \\{`))
}
assert.match(source, /定位只证明原文位置.*科学有效性/)

const exec = { agent: { id: 'child-a' } }
const located = await byName.sr_evidence_locate.execute({
  paper_id: 'library_a', block_id: 'p0001-m0002',
  quote: 'exact quote', page: 1,
}, exec)
assert.equal(located.contract, 'evidence-locator-v1')
const candidate = await byName.sr_candidate_rebuild.execute({
  paper_id: 'library_a', target_root: 'C:\\candidate',
}, exec)
assert.equal(candidate.status, 'pending')
const context = await byName.sr_review_context.execute({}, exec)
assert.equal(context.review_session_id, 'child-a')

const conclusions = [{
  conclusion_type: '机制',
  conclusion_text: '结论 A',
  evidence_locator: 'Figure 2',
}]
const confirmed = await byName.sr_review_confirm.execute({ conclusions }, exec)
assert.equal(confirmed.status, 'confirmed')
assert.deepEqual(confirmed.xlsx, { status: 'success', path: 'library.xlsx' })
assert.deepEqual(calls, [
  ['locate', {
    paper_id: 'library_a', block_id: 'p0001-m0002',
    quote: 'exact quote', page: 1,
  }],
  ['candidate-rebuild', {
    paper_id: 'library_a', target_root: 'C:\\candidate',
  }],
  ['context', 'child-a'],
  ['confirm', 'child-a', conclusions],
  ['xlsx-refresh'],
])

await assert.rejects(
  () => byName.sr_review_context.execute({}, { agent: undefined }),
  /review_agent_required/,
)

console.log('PASS: 整理工具只信任当前 DSH 子会话身份并在确认后刷新 Excel')
