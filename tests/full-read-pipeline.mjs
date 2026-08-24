import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { delimiter, join } from 'node:path'
import { tmpdir } from 'node:os'
import { engineStartFullRead } from '../lib/cli.js'

delete process.env.FEISHU_APP_ID
delete process.env.FEISHU_APP_SECRET

const cli = readFileSync(new URL('../src/cli.ts', import.meta.url), 'utf8')
const tools = readFileSync(new URL('../src/library_tools.ts', import.meta.url), 'utf8')
const routes = readFileSync(new URL('../src/routes.ts', import.meta.url), 'utf8')
const client = readFileSync(new URL('../client/client.js', import.meta.url), 'utf8')
const wrapper = readFileSync(new URL('../scripts/scansci_wrap.py', import.meta.url), 'utf8')

for (const name of ['sr_start_full_read', 'sr_continue_full_read', 'sr_attach_pdf', 'sr_export_assets', 'sr_job_status']) {
  assert.match(tools, new RegExp(`name: '${name}'`))
}
assert.match(cli, /fileURLToPath\(new URL\(WRAP_REL, import\.meta\.url\)\)/)
assert.match(cli, /SR_SCANSCI_PROVIDER_WRAPPER: wrapper/)
assert.doesNotMatch(cli, /engineStartFullRead[\s\S]*config\.scansciExe/)
assert.match(routes, /action === 'start'/)
assert.match(routes, /parts\[1\] === 'continue'/)
assert.doesNotMatch(routes, /reading['"], ['"]full['"], ['"]output['"], ['"]reader_full\.html/)
assert.doesNotMatch(routes, /\|reading\\\/reader\\\.html/)
assert.match(client, /\/start'/)
assert.doesNotMatch(client, /\/parse'/)
assert.doesNotMatch(client, /\/quick-read'/)
assert.doesNotMatch(client, /\/full-read'/)
assert.match(client, /gateReason === 'pdf_required'/)
assert.match(wrapper, /TemporaryDirectory\(prefix="\.scansci-", dir=destination\.parent\)/)
assert.match(wrapper, /set\(payload\) != \{"identifier", "destination", "legal_only"\}/)

console.log('PASS: 单一精读工具、受信 scansci 注入与 gate 路由合同')

const fixture = mkdtempSync(join(tmpdir(), 'sr-trusted-env-'))
const fakeRoot = join(fixture, 'fake')
const envLog = join(fixture, 'env.json')
mkdirSync(join(fakeRoot, 'scientific_reading'), { recursive: true })
writeFileSync(join(fakeRoot, 'scientific_reading', '__init__.py'), '')
writeFileSync(join(fakeRoot, 'scientific_reading', '__main__.py'), `import json,os\njson.dump({'id':os.environ.get('FEISHU_APP_ID'),'secret':os.environ.get('FEISHU_APP_SECRET'),'wrapper':os.environ.get('SR_SCANSCI_PROVIDER_WRAPPER')},open(${JSON.stringify(envLog)},'w'))\nprint(json.dumps({'parent_job_id':'job_0123456789abcdef'}))\n`)
const python = execFileSync('where.exe', ['python'], { encoding: 'utf8' }).split(/\r?\n/).find((line) => line.trim().toLowerCase().endsWith('.exe')).trim()
const old = { PYTHONPATH: process.env.PYTHONPATH, SCANSCI_PDF_DATA_DIR: process.env.SCANSCI_PDF_DATA_DIR, FEISHU_APP_ID: process.env.FEISHU_APP_ID, FEISHU_APP_SECRET: process.env.FEISHU_APP_SECRET }
process.env.PYTHONPATH = old.PYTHONPATH ? fakeRoot + delimiter + old.PYTHONPATH : fakeRoot
process.env.SCANSCI_PDF_DATA_DIR = join(fixture, 'scansci')
process.env.FEISHU_APP_ID = 'fictional-app-id'
process.env.FEISHU_APP_SECRET = 'fictional-secret'
try {
  const result = await engineStartFullRead({ dataRoot: join(fixture, 'data'), python, scansciExe: 'untrusted.exe', school: '', legalOnly: false, outputDir: '', loginType: 'carsi', scansciPython: python, enginePython: python, feishuConfig: '' }, 'title_fixture')
  assert.equal(result.ok, true)
  const childEnv = JSON.parse(readFileSync(envLog, 'utf8'))
  assert.equal(childEnv.id, null); assert.equal(childEnv.secret, null); assert.match(childEnv.wrapper, /scansci_wrap\.py$/)
  const legal = JSON.parse(readFileSync(join(process.env.SCANSCI_PDF_DATA_DIR, 'config.json'), 'utf8'))
  assert.equal(legal.download_strategy, 'legal_only'); assert.equal(legal.scihub_enabled, false)
  console.log('PASS: full-read 子进程隔离飞书 secret 且强制 legal_only 配置')
} finally {
  for (const [key, value] of Object.entries(old)) { if (value === undefined) delete process.env[key]; else process.env[key] = value }
  rmSync(fixture, { recursive: true, force: true })
}
