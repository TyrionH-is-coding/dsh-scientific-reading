import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { registerRoutes } from '../lib/routes.js'

const fixture = mkdtempSync(join(tmpdir(), 'sr-reading-routes-'))
const paperId = 'doi_10.48550_arxiv.1706.03762'
const readingDir = join(fixture, 'papers', paperId, 'reading')
const fullOutputDir = join(readingDir, 'full', 'output')

mkdirSync(fullOutputDir, { recursive: true })
writeFileSync(join(readingDir, 'quick_read.md'), '# fixture quick read', 'utf8')
writeFileSync(join(fullOutputDir, 'reader_full.html'), '<!doctype html><p>fixture full reader</p>', 'utf8')

const routes = []
const ctx = {
  effect(setup) { setup() },
  logger() {},
  webServer: {
    register(route) {
      routes.push(route)
      return () => {}
    },
  },
}
const config = {
  dataRoot: fixture,
  python: 'python',
  scansciExe: 'scansci-pdf',
  school: '',
  legalOnly: true,
  outputDir: '',
  loginType: 'carsi',
  scansciPython: '',
  enginePython: '',
  feishuConfig: '',
}

function response() {
  return {
    statusCode: 0,
    headers: {},
    body: '',
    writeHead(statusCode, headers) {
      this.statusCode = statusCode
      this.headers = headers
    },
    end(body = '') {
      this.body = String(body)
    },
  }
}

async function request(path, url) {
  const route = routes.find((candidate) => candidate.kind === 'prefix' && candidate.path === path)
  assert.ok(route, `缺少路由 ${path}`)
  const res = response()
  await route.handler({ method: 'GET', url }, res)
  return res
}

try {
  registerRoutes(ctx, config)

  const reading = await request('/sr/reading', `/sr/reading/${paperId}`)
  assert.equal(reading.statusCode, 200)
  assert.match(reading.headers['Content-Type'], /^text\/html/)
  assert.match(reading.body, /fixture quick read/)

  const reader = await request('/sr/reader', `/sr/reader/${paperId}`)
  assert.equal(reader.statusCode, 200)
  assert.match(reader.headers['Content-Type'], /^text\/html/)
  assert.match(reader.body, /fixture full reader/)

  assert.equal((await request('/sr/reading', '/sr/reading/not-a-paper')).statusCode, 404)
  assert.equal((await request('/sr/reader', '/sr/reader/not-a-paper')).statusCode, 404)
  assert.equal((await request('/sr/reading', '/sr/reading/title_missing')).statusCode, 404)
  assert.equal((await request('/sr/reader', '/sr/reader/title_missing')).statusCode, 404)

  console.log('PASS: 浅读与精读页面路由回归测试')
} finally {
  rmSync(fixture, { recursive: true, force: true })
}
