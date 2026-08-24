import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdirSync, mkdtempSync, rmSync, unlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { delimiter, join } from 'node:path'
import { registerRoutes } from '../lib/routes.js'

const fixture = mkdtempSync(join(tmpdir(), 'sr-reading-routes-'))
const paperId = 'doi_10.48550_arxiv.1706.03762'
const readingDir = join(fixture, 'papers', paperId, 'reading')
const generationDir = join(fixture, 'papers', paperId, 'generations', 'a'.repeat(16))
const fullOutputDir = join(generationDir, 'output')
const canonicalDir = join(generationDir, 'reading')
const fakeRoot = join(fixture, 'fake')
const python = execFileSync('where.exe', ['python'], { encoding: 'utf8' }).split(/\r?\n/).find((line) => line.trim().toLowerCase().endsWith('.exe')).trim()

mkdirSync(fullOutputDir, { recursive: true })
mkdirSync(canonicalDir, { recursive: true })
mkdirSync(readingDir, { recursive: true })
writeFileSync(join(readingDir, 'quick_read.md'), '# fixture quick read', 'utf8')
const legacyHtml = '<!doctype html><p>fixture full reader</p>'
writeFileSync(join(fullOutputDir, 'reader_full.html'), legacyHtml, 'utf8')
const canonicalHtml = '<!doctype html><p>fixture canonical reader</p>'
writeFileSync(join(canonicalDir, 'reader.html'), canonicalHtml, 'utf8')
mkdirSync(join(fakeRoot, 'scientific_reading'), { recursive: true })
writeFileSync(join(fakeRoot, 'scientific_reading', '__init__.py'), '', 'utf8')
writeFileSync(join(fakeRoot, 'scientific_reading', '__main__.py'), `import json, os\ncanonical='generations/${'a'.repeat(16)}/reading/reader.html'\ncanonical_abs=${JSON.stringify(join(canonicalDir, 'reader.html'))}\nlegacy='generations/${'a'.repeat(16)}/output/reader_full.html'\nif os.path.exists(canonical_abs): print(json.dumps({'paper_id':'${paperId}','kind':'reader','rel_path':canonical,'legacy':False,'sha256':'${createHash('sha256').update(canonicalHtml).digest('hex')}'}))\nelse: print(json.dumps({'paper_id':'${paperId}','kind':'reader','rel_path':legacy,'legacy':True,'sha256':'${createHash('sha256').update(legacyHtml).digest('hex')}'}))\n`, 'utf8')
const previousPythonPath = process.env.PYTHONPATH
process.env.PYTHONPATH = previousPythonPath ? fakeRoot + delimiter + previousPythonPath : fakeRoot

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
  enginePython: python,
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
  assert.match(reader.body, /fixture canonical reader/)
  assert.doesNotMatch(reader.body, /fixture full reader/)
  unlinkSync(join(canonicalDir, 'reader.html'))
  const legacyReader = await request('/sr/reader', `/sr/reader/${paperId}`)
  assert.equal(legacyReader.statusCode, 200)
  assert.match(legacyReader.body, /fixture full reader/)

  assert.equal((await request('/sr/reading', '/sr/reading/not-a-paper')).statusCode, 404)
  assert.equal((await request('/sr/reader', '/sr/reader/not-a-paper')).statusCode, 404)
  assert.equal((await request('/sr/reader', `/sr/reader/${paperId}/extra`)).statusCode, 404)
  assert.equal((await request('/sr/reader', `/sr/reader/${paperId}/../secret`)).statusCode, 404)
  assert.equal((await request('/sr/reading', '/sr/reading/title_missing')).statusCode, 404)
  assert.equal((await request('/sr/reader', '/sr/reader/title_missing')).statusCode, 404)

  console.log('PASS: 浅读与精读页面路由回归测试')
} finally {
  if (previousPythonPath === undefined) delete process.env.PYTHONPATH
  else process.env.PYTHONPATH = previousPythonPath
  rmSync(fixture, { recursive: true, force: true })
}
