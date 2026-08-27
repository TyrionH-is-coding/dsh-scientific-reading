import assert from 'node:assert/strict'

import { runDownloadBatch } from '../lib/download_batch.js'

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
assert.equal(chromeLaunches, 1)
assert.deepEqual(result.challengePaperIds.sort(), ['p7', 'p9'])
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
console.log('PASS: 批量下载先直连、整批一次机构会话并集中挑战项')
