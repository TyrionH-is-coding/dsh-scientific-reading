import assert from 'node:assert/strict'

import { registerRoutes } from '../lib/routes.js'

const validId = 'review_' + 'a'.repeat(32)
const staleId = 'review_' + 'b'.repeat(32)
const pdfId = 'review_' + 'c'.repeat(32)
const personalId = 'review_' + 'd'.repeat(32)
const missingId = 'review_' + 'e'.repeat(32)
const calls = []
const values = {
  [validId]: {
    conclusion_id: validId,
    paper_id: 'library_a',
    basis: 'paper', evidence_status: 'location_verified', claim_support: 'location_only',
    links: {
      reader: { available: true, fragment: 'block-p0001-m0002' },
      pdf: { available: true, page: 1 },
    },
  },
  [staleId]: {
    conclusion_id: staleId,
    paper_id: 'library_a',
    basis: 'paper', evidence_status: 'stale', claim_support: 'not_source_supported',
    links: null,
  },
  [pdfId]: {
    conclusion_id: pdfId,
    paper_id: 'library_a',
    basis: 'paper', evidence_status: 'location_verified', claim_support: 'location_only',
    links: {
      reader: { available: false, fragment: null },
      pdf: { available: true, page: 7 },
    },
  },
  [personalId]: {
    conclusion_id: personalId,
    paper_id: 'library_a',
    basis: 'personal', evidence_status: 'not_provided', claim_support: 'not_source_supported',
    links: { reader: { available: true, fragment: 'block-p0001-m0002' } },
  },
}
const routes = []
const ctx = {
  effect(setup) { setup() },
  logger() {},
  webServer: { register(route) { routes.push(route); return () => {} } },
}
const config = { dataRoot: 'unused' }
registerRoutes(ctx, config, {
  async resolveConclusion(_config, conclusionId) {
    calls.push(conclusionId)
    if (conclusionId === missingId) {
      return { ok: false, json: { status: 'failed', error: 'conclusion_not_found' }, stderr: '' }
    }
    return { ok: true, json: values[conclusionId], stderr: '' }
  },
})
const route = routes.find((item) => item.kind === 'exact' && item.path === '/sr/evidence')
assert.ok(route)
const response = () => ({
  statusCode: 0, headers: {}, body: '',
  writeHead(status, headers = {}) { this.statusCode = status; this.headers = headers },
  end(body = '') { this.body = String(body) },
})
const request = (url, method = 'GET') => ({ method, url })

const reader = response()
await route.handler(request(`/sr/evidence?conclusion_id=${validId}`), reader)
assert.equal(reader.statusCode, 302)
assert.equal(reader.headers.Location, '/sr/reader/library_a#block-p0001-m0002')
assert.equal(reader.headers['Cache-Control'], 'no-store')

const pdf = response()
await route.handler(request(`/sr/evidence?conclusion_id=${pdfId}`), pdf)
assert.equal(pdf.statusCode, 302)
assert.equal(pdf.headers.Location, '/sr/api/paper/library_a/pdf#page=7')

const stale = response()
await route.handler(request(`/sr/evidence?conclusion_id=${staleId}`), stale)
assert.equal(stale.statusCode, 409)
assert.deepEqual(JSON.parse(stale.body), {
  error: 'evidence_stale', conclusion_id: staleId, evidence_status: 'stale',
})

const personal = response()
await route.handler(request(`/sr/evidence?conclusion_id=${personalId}`), personal)
assert.equal(personal.statusCode, 409)
assert.equal(JSON.parse(personal.body).error, 'evidence_unavailable')

const missing = response()
await route.handler(request(`/sr/evidence?conclusion_id=${missingId}`), missing)
assert.equal(missing.statusCode, 404)

const invalid = response()
await route.handler(request('/sr/evidence?conclusion_id=../../secret'), invalid)
assert.equal(invalid.statusCode, 400)
assert.equal(calls.includes('../../secret'), false)

console.log('PASS: 动态证据路由只为当前有效 paper 定位跳转到固定 Reader/PDF 路径')
