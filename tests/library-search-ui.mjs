import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { delimiter, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { registerRoutes } from '../lib/routes.js'

const root = fileURLToPath(new URL('..', import.meta.url))
const source = readFileSync(join(root, 'client', 'client.js'), 'utf8')

function namedFunctionSource(name) {
  const start = source.indexOf(`function ${name}(`)
  assert.notEqual(start, -1, `缺少可测试函数：${name}`)
  const bodyStart = source.indexOf('{', start)
  let depth = 0
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1
    if (source[index] === '}') depth -= 1
    if (depth === 0) return source.slice(start, index + 1)
  }
  throw new Error(`函数未闭合：${name}`)
}

function loadNamedFunction(name, dependencies = {}) {
  const names = Object.keys(dependencies)
  return Function(...names, `return (${namedFunctionSource(name)})`)(
    ...names.map((key) => dependencies[key]),
  )
}

class FakeNode {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase()
    this.className = ''
    this.textContent = ''
    this.children = []
    this.attributes = {}
    this.href = ''
    this.target = ''
    this.rel = ''
  }
  appendChild(child) {
    this.children.push(child)
    return child
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value)
  }
}

globalThis.document = { createElement(tagName) { return new FakeNode(tagName) } }
const el = loadNamedFunction('el')
const searchMatchModel = loadNamedFunction('searchMatchModel')
const renderSearchMatches = loadNamedFunction('renderSearchMatches', {
  el,
  searchMatchModel,
})

const verifiedId = 'review_0123456789abcdef0123456789abcdef'
const rendered = renderSearchMatches({
  search_matches: [
    { content_type: 'metadata', snippet: '<img src=x onerror=alert(1)> DOI: 10.1/example' },
    { content_type: 'abstract_en', snippet: 'Interleukin-6 signal.' },
    { content_type: 'abstract_zh', snippet: '凝血信号。' },
    {
      content_type: 'conclusion',
      snippet: '<script>alert(1)</script> 用户确认结论',
      conclusion_id: verifiedId,
      basis: 'paper',
      evidence_status: 'location_verified',
      scientific_validity: 'not_assessed',
      claim_support: 'location_only',
      evidence_url: `/sr/evidence?conclusion_id=${encodeURIComponent(verifiedId)}`,
      source: { reader_url: 'javascript:alert(1)' },
      links: { primary: 'https://evil.example/' },
    },
  ],
})

assert.equal(rendered.className, 'sr-search-matches')
assert.equal(rendered.attributes['aria-label'], '检索命中')
assert.equal(rendered.children.length, 4)
const nodes = []
function collect(node) {
  nodes.push(node)
  node.children.forEach(collect)
}
collect(rendered)
assert.equal(nodes.some((node) => node.tagName === 'IMG' || node.tagName === 'SCRIPT'), false, '片段必须仅作为 textContent')
assert.equal(nodes.some((node) => node.textContent.includes('<script>')), true, '文本内容不得被解释为 DOM')
assert.deepEqual(
  nodes.filter((node) => node.className === 'sr-search-kind').map((node) => node.textContent),
  ['元数据', '英文摘要', '中文摘要', '已确认结论'],
)
assert.equal(nodes.some((node) => node.textContent === '依据：论文定位'), true)
assert.equal(nodes.some((node) => node.textContent === '定位有效'), true)
assert.equal(nodes.some((node) => node.textContent === '科学有效性未评估'), true)
const evidenceLinks = nodes.filter((node) => node.tagName === 'A')
assert.equal(evidenceLinks.length, 1)
assert.equal(evidenceLinks[0].href, `/sr/evidence?conclusion_id=${encodeURIComponent(verifiedId)}`)
assert.equal(evidenceLinks[0].target, '_blank')
assert.equal(evidenceLinks[0].rel, 'noopener')
assert.equal(nodes.some((node) => String(node.href).includes('evil.example')), false, '不得信任结果内来源 URL')

for (const [basis, label] of Object.entries({
  personal: '个人判断', inference: '推断', question: '待核问题', legacy: '旧版记录',
})) {
  assert.equal(searchMatchModel({ content_type: 'conclusion', snippet: 'x', conclusion_id: verifiedId, basis, evidence_status: 'not_provided' }).basisLabel, label)
}
for (const [evidenceStatus, label] of Object.entries({
  stale: '定位失效', legacy_unverified: '旧版未验证', not_provided: '未提供定位',
})) {
  const model = searchMatchModel({ content_type: 'conclusion', snippet: 'x', conclusion_id: verifiedId, basis: 'paper', evidence_status: evidenceStatus })
  assert.equal(model.evidenceLabel, label)
  assert.equal(model.evidenceHref, '')
}
assert.equal(searchMatchModel({ content_type: 'fulltext', snippet: '不得显示' }), null)
assert.equal(searchMatchModel({ content_type: 'conclusion', snippet: 'x', conclusion_id: 'javascript:alert(1)', basis: 'paper', evidence_status: 'location_verified', claim_support: 'location_only', evidence_url: '/sr/evidence?conclusion_id=javascript%3Aalert(1)' }).evidenceHref, '')
assert.equal(searchMatchModel({ content_type: 'conclusion', snippet: 'x', conclusion_id: verifiedId, basis: 'personal', evidence_status: 'location_verified', claim_support: 'location_only', evidence_url: `/sr/evidence?conclusion_id=${verifiedId}` }).evidenceHref, '')
assert.doesNotMatch(source, /全文搜索/, 'UI 不得声称全文搜索')
assert.match(source, /搜索题名、作者、DOI、摘要或已确认结论/)

if (process.argv.includes('--ui-only')) {
  console.log('PASS: typed 检索命中、XSS 防护与安全证据链接 UI 行为')
  process.exit(0)
}

function response() {
  return {
    statusCode: 0,
    body: '',
    writeHead(status) { this.statusCode = status },
    end(body = '') { this.body = String(body) },
  }
}

const python = execFileSync('where.exe', ['python'], { encoding: 'utf8' })
  .split(/\r?\n/).map((line) => line.trim()).find((line) => line.toLowerCase().endsWith('.exe'))
assert.ok(python)
const fixture = mkdtempSync(join(tmpdir(), 'sr-library-search-ui-'))
const dataRoot = join(fixture, 'data')
const previousPythonPath = process.env.PYTHONPATH
process.env.PYTHONPATH = [join(root, 'engine', 'src'), join(root, 'engine'), previousPythonPath]
  .filter(Boolean).join(delimiter)
process.env.PYTHONDONTWRITEBYTECODE = '1'

try {
  execFileSync(python, ['-m', 'scientific_reading', '--data-root', dataRoot, 'library-ingest'], {
    encoding: 'utf8',
    input: JSON.stringify({
      title: 'Route search paper',
      doi: '10.1000/route-search',
      abstract_en: 'Interleukin route evidence.',
      abstract_zh: '凝血路由证据。',
    }),
    env: process.env,
  })
  const routes = []
  registerRoutes({
    effect(setup) { setup() },
    logger() {},
    webServer: { register(route) { routes.push(route); return () => {} } },
  }, {
    dataRoot,
    python,
    scansciExe: 'scansci-pdf',
    school: '',
    legalOnly: true,
    outputDir: '',
    loginType: 'carsi',
    scansciPython: '',
    enginePython: python,
  })
  const libraryRoute = routes.find((route) => route.kind === 'exact' && route.path === '/sr/api/library')
  assert.ok(libraryRoute)
  const apiResponse = response()
  await libraryRoute.handler({ method: 'GET', url: '/sr/api/library?page=1&page_size=10&q=%E5%87%9D%E8%A1%80' }, apiResponse)
  assert.equal(apiResponse.statusCode, 200)
  const payload = JSON.parse(apiResponse.body)
  assert.equal(payload.total, 1)
  assert.equal(payload.items[0].title, 'Route search paper')
  assert.equal(payload.items[0].search_matches[0].content_type, 'abstract_zh')
  assert.equal(payload.items[0].search_matches[0].snippet, '凝血路由证据。')
  const unfilteredResponse = response()
  await libraryRoute.handler({ method: 'GET', url: '/sr/api/library?page=1&page_size=10' }, unfilteredResponse)
  assert.equal(unfilteredResponse.statusCode, 200)
  assert.equal(Object.hasOwn(JSON.parse(unfilteredResponse.body).items[0], 'search_matches'), false, '无 query 时保持旧响应形状')
} finally {
  if (previousPythonPath === undefined) delete process.env.PYTHONPATH
  else process.env.PYTHONPATH = previousPythonPath
  rmSync(fixture, { recursive: true, force: true })
}

console.log('PASS: typed 检索命中安全渲染，并经真实 library route 读回')
