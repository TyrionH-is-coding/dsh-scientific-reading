import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { ensureScansciConfig, runScansci } from '../lib/cli.js'
import { registerTools } from '../lib/tools.js'

const fixture = mkdtempSync(join(tmpdir(), 'sr-oa-boundary-'))
const oldData = process.env.SCANSCI_PDF_DATA_DIR
process.env.SCANSCI_PDF_DATA_DIR = join(fixture, 'external-scansci')
mkdirSync(process.env.SCANSCI_PDF_DATA_DIR)
const externalConfig = join(process.env.SCANSCI_PDF_DATA_DIR, 'config.json')
const original = JSON.stringify({ carsi_enabled: true, vpnsci_school: 'fixture-school', download_strategy: 'institution' })
writeFileSync(externalConfig, original)
const config = { dataRoot: join(fixture, 'data'), python: 'python', scansciExe: process.execPath, school: 'fixture-school', legalOnly: false, outputDir: '', loginType: 'carsi', scansciPython: '', enginePython: '' }
try {
  const state = await ensureScansciConfig(config)
  assert.notEqual(state.path, externalConfig, 'A 不应读取或写入独立 ScanSci 用户配置')
  assert.equal(readFileSync(externalConfig, 'utf8'), original)
  assert.equal(state.legalOnly, true)
  const saved = JSON.parse(readFileSync(state.path, 'utf8'))
  assert.equal(saved.download_strategy, 'oa_only')
  assert.equal(saved.carsi_enabled, undefined)
  const blocked = await runScansci(process.execPath, ['login'], config)
  assert.equal(blocked.stderr, 'oa_only_operation_not_supported')
  const tools = []
  registerTools({ effect(fn) { fn() }, tools: { register(tool) { tools.push(tool); return () => {} } } }, config)
  assert.ok(!tools.some((tool) => /sr_scansci_(login|set_school)/.test(tool.name)))
  assert.equal(tools.find((tool) => tool.name === 'sr_scansci_fetch').parameters.login_type, undefined)
  const cliSource = readFileSync(new URL('../src/cli.ts', import.meta.url), 'utf8')
  assert.doesNotMatch(cliSource, /\['tool', 'install', 'scansci-pdf'\]|'--user', 'scansci-pdf'/, 'A 安装不得改用户级工具环境或追踪最新版')
  assert.match(cliSource, /--require-hashes/)
  assert.match(cliSource, /oa-requirements\.txt/)
  console.log('PASS: 固定 OA 配置、独立 ScanSci 保护与机构工具退出')
} finally {
  if (oldData === undefined) delete process.env.SCANSCI_PDF_DATA_DIR
  else process.env.SCANSCI_PDF_DATA_DIR = oldData
  rmSync(fixture, { recursive: true, force: true })
}
