import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'


const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const pagePath = path.join(repositoryRoot, 'review', 'index.html')
const html = await fs.readFile(pagePath, 'utf8')

for (const id of [
  'case-select',
  'version-baseline',
  'version-candidate',
  'viewport-desktop',
  'viewport-tablet',
  'viewport-mobile',
  'build-status',
  'test-status',
  'reader-frame',
  'failure-banner',
]) {
  assert.match(html, new RegExp(`id=["']${id}["']`), `缺少审核控件 ${id}`)
}

assert.doesNotMatch(html, /评论系统|截图上传|WebSocket|Playwright/i)
assert.doesNotMatch(html, /<script[^>]+src=/i)
assert.doesNotMatch(html, /<link[^>]+href=/i)
assert.match(html, /setInterval\(pollManifest,\s*800\)/)
assert.match(html, /cache:\s*['"]no-store['"]/)
assert.match(html, /data-width=["']100%["']/)
assert.match(html, /data-width=["']900px["']/)
assert.match(html, /data-width=["']390px["']/)
assert.match(html, /candidate_stale/)
assert.match(html, /scrollRatio/)
assert.match(html, /data-block/)

const scriptMatch = /<script>([\s\S]*?)<\/script>/.exec(html)
assert.ok(scriptMatch, '审核页必须内嵌一段脚本')
const context = {
  URL,
  location: { origin: 'http://127.0.0.1:8895' },
  document: {
    readyState: 'loading',
    addEventListener() {},
  },
  globalThis: null,
  console,
  setInterval() {},
  fetch: async () => { throw new Error('boot must not run in contract test') },
}
context.globalThis = context
vm.runInNewContext(scriptMatch[1], context, { filename: pagePath })

const helpers = context.__readerReviewTest
assert.ok(helpers, '审核页必须暴露纯函数测试边界')
assert.equal(helpers.viewportWidth('desktop'), '100%')
assert.equal(helpers.viewportWidth('tablet'), '900px')
assert.equal(helpers.viewportWidth('mobile'), '390px')
assert.equal(
  helpers.positionAnchorSelector,
  'article .reading-block[data-block], article h2[id], article h3[id], article h4[id], article h5[id], article h6[id]',
)
assert.equal(
  helpers.candidateUrl(
    { candidate_url: '/content/candidate/formula-outline/reader.html?revision=1' },
    7,
  ),
  '/content/candidate/formula-outline/reader.html?revision=7',
)
assert.equal(
  helpers.urlForVersion(
    {
      baseline_url: '/content/baseline/formula-outline/reader.html',
      candidate_url: '/content/candidate/formula-outline/reader.html?revision=1',
    },
    'baseline',
    9,
  ),
  '/content/baseline/formula-outline/reader.html',
)

console.log('PASS: Reader 统一审核页静态与纯函数合同通过')
