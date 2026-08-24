import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { delimiter, join } from 'node:path'
import { registerRoutes } from '../lib/routes.js'

const fixture = mkdtempSync(join(tmpdir(), 'sr-reading-routes-'))
const paperId = 'doi_10.48550_arxiv.1706.03762'
const readingDir = join(fixture, 'papers', paperId, 'reading')
const generationDir = join(fixture, 'papers', paperId, 'generations', 'a'.repeat(16))
const fullOutputDir = join(generationDir, 'output')
const canonicalDir = join(generationDir, 'reading')
const rootLegacyPath = join(fixture, 'papers', paperId, 'reader_full.html')
const auditFlagPath = join(fixture, 'audit-root-reader.flag')
const exportsDir = join(generationDir, 'exports')
const fakeRoot = join(fixture, 'fake')
const python = execFileSync('where.exe', ['python'], { encoding: 'utf8' }).split(/\r?\n/).find((line) => line.trim().toLowerCase().endsWith('.exe')).trim()

mkdirSync(fullOutputDir, { recursive: true })
mkdirSync(canonicalDir, { recursive: true })
mkdirSync(exportsDir, { recursive: true })
mkdirSync(readingDir, { recursive: true })
writeFileSync(join(readingDir, 'quick_read.md'), '# fixture quick read', 'utf8')
const legacyHtml = '<!doctype html><p>fixture full reader</p>'
writeFileSync(join(fullOutputDir, 'reader_full.html'), legacyHtml, 'utf8')
const rootLegacyHtml = '<!doctype html><p>fixture audited root reader</p>'
writeFileSync(rootLegacyPath, rootLegacyHtml, 'utf8')
const canonicalHtml = '<!doctype html><p>fixture canonical reader</p>'
writeFileSync(join(canonicalDir, 'reader.html'), canonicalHtml, 'utf8')
mkdirSync(join(fakeRoot, 'scientific_reading'), { recursive: true })
writeFileSync(join(fakeRoot, 'scientific_reading', '__init__.py'), '', 'utf8')
writeFileSync(join(fakeRoot, 'scientific_reading', '__main__.py'), `import json, os, sys\ncanonical='generations/${'a'.repeat(16)}/reading/reader.html'\ncanonical_abs=${JSON.stringify(join(canonicalDir, 'reader.html'))}\nlegacy='generations/${'a'.repeat(16)}/output/reader_full.html'\nlegacy_abs=${JSON.stringify(join(fullOutputDir, 'reader_full.html'))}\naudit_flag=${JSON.stringify(auditFlagPath)}\nroot_legacy='reader_full.html'\nif '--kind' in sys.argv and sys.argv[sys.argv.index('--kind')+1]=='exports': print(json.dumps({'paper_id':'${paperId}','kind':'exports','rel_path':'generations/${'a'.repeat(16)}/exports','manifest':{'assets':[{'kind':'figure'},{'kind':'figure'},{'kind':'table'}]}}))\nelif os.path.exists(canonical_abs): print(json.dumps({'paper_id':'${paperId}','kind':'reader','rel_path':canonical,'legacy':False,'sha256':'${createHash('sha256').update(canonicalHtml).digest('hex')}'}))\nelif os.path.exists(legacy_abs): print(json.dumps({'paper_id':'${paperId}','kind':'reader','rel_path':legacy,'legacy':True,'sha256':'${createHash('sha256').update(legacyHtml).digest('hex')}'}))\nelse: print(json.dumps({'paper_id':'${paperId}','kind':'reader','rel_path':root_legacy,'legacy':True,'legacy_audited':os.path.exists(audit_flag),'sha256':'${createHash('sha256').update(rootLegacyHtml).digest('hex')}'}))\n`, 'utf8')
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
  unlinkSync(join(fullOutputDir, 'reader_full.html'))
  assert.equal((await request('/sr/reader', `/sr/reader/${paperId}`)).statusCode, 404, '根级旧 reader 没有审计标志时必须拒绝')
  writeFileSync(auditFlagPath, 'audited', 'utf8')
  const auditedRootReader = await request('/sr/reader', `/sr/reader/${paperId}`)
  assert.equal(auditedRootReader.statusCode, 200)
  assert.match(auditedRootReader.body, /fixture audited root reader/)

  const assets = await request('/sr/api/paper', `/sr/api/paper/${paperId}/assets`)
  assert.equal(assets.statusCode, 200)
  const assetBody = JSON.parse(assets.body)
  assert.equal(assetBody.exports_path, exportsDir)
  assert.equal(assetBody.figures, 2)
  assert.equal(assetBody.tables, 1)
  const outsideExports = mkdtempSync(join(tmpdir(), 'sr-outside-exports-'))
  rmSync(exportsDir, { recursive: true, force: true })
  symlinkSync(outsideExports, exportsDir, 'junction')
  assert.equal((await request('/sr/api/paper', `/sr/api/paper/${paperId}/assets`)).statusCode, 404, '资产绝对路径不得穿过 symlink/junction 离开 dataRoot')
  rmSync(exportsDir, { recursive: true, force: true })
  rmSync(outsideExports, { recursive: true, force: true })

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
