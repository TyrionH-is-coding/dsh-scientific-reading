import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { delimiter, join } from 'node:path'
import { tmpdir } from 'node:os'
import { engineStartFullRead } from '../lib/cli.js'
import { registerLibraryTools } from '../lib/library_tools.js'

const cli = readFileSync(new URL('../src/cli.ts', import.meta.url), 'utf8')
const tools = readFileSync(new URL('../src/library_tools.ts', import.meta.url), 'utf8')
const routes = readFileSync(new URL('../src/routes.ts', import.meta.url), 'utf8')
const client = readFileSync(new URL('../client/client.js', import.meta.url), 'utf8')
const wrapper = readFileSync(new URL('../scripts/scansci_wrap.py', import.meta.url), 'utf8')
const preset = readFileSync(new URL('../preset/scientific-reading/agent.cordis.yml', import.meta.url), 'utf8')

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
assert.match(client, /\/full-read'/)
assert.doesNotMatch(client, /\/parse'/)
assert.doesNotMatch(client, /\/quick-read'/)
assert.match(client, /reason_code === 'pdf_required'/)
assert.match(wrapper, /TemporaryDirectory\(prefix="\.scansci-", dir=destination\.parent\)/)
assert.match(wrapper, /set\(payload\) != \{"identifier", "destination", "legal_only"\}/)

const registeredTools = []
registerLibraryTools({ effect(fn) { fn() }, logger() {}, tools: { register(tool) { registeredTools.push(tool); return () => {} } } }, {})
const statusTool = registeredTools.find((tool) => tool.name === 'sr_job_status')
assert.ok(statusTool)
const translationPath = 'D:\\data\\paper\\reading\\full\\batches\\batch-0001.source.json'
const translationRendered = statusTool.output.render({}, {
  job_id: 'job_0123456789abcdef', status: 'waiting_agent', next_action: 'agent',
  detail: { reason_code: 'translate_full_read', required_input: { stage: 'translate_full', batch_id: 'batch-0001', source_sha256: 'a'.repeat(64), source_manifest_path: translationPath } },
}).map((block) => block.text).join('\n')
for (const expected of ['required_input', 'batch-0001', 'full_translation', 'translation_zh', 'highlight']) assert.match(translationRendered, new RegExp(expected))
assert.ok(translationRendered.includes(JSON.stringify(translationPath)), 'required_input 的完整路径必须进入模型可见 render')

const reviewRendered = statusTool.output.render({}, {
  job_id: 'job_0123456789abcdef', status: 'waiting_agent', next_action: 'agent',
  detail: { reason_code: 'review_full_read', required_input: { contract_version: 'full-review-v2', translations_json: 'D:\\data\\translations.json', source_map_json: 'D:\\data\\source_map.json', maximum_full_review_highlights: 2, available_source_block_ids: ['p0001-m0001'], guide_limits: { research_question: 1, key_methods: 2, core_results: 3, limitations: 2 } } },
}).map((block) => block.text).join('\n')
for (const expected of ['translations_json', 'source_map_json', 'maximum_full_review_highlights', 'available_source_block_ids', 'full_review', 'source_block_ids']) assert.match(reviewRendered, new RegExp(expected))
assert.match(preset, /required_input/)
assert.match(preset, /full_translation/)
assert.match(preset, /full_review/)

console.log('PASS: 单一精读工具、受信 scansci 注入与 gate 路由合同')

const fixture = mkdtempSync(join(tmpdir(), 'sr-trusted-env-'))
const fakeRoot = join(fixture, 'fake')
const envLog = join(fixture, 'env.json')
mkdirSync(join(fakeRoot, 'scientific_reading'), { recursive: true })
writeFileSync(join(fakeRoot, 'scientific_reading', '__init__.py'), '')
writeFileSync(join(fakeRoot, 'scientific_reading', '__main__.py'), `import json,os\njson.dump({'wrapper':os.environ.get('SR_SCANSCI_PROVIDER_WRAPPER')},open(${JSON.stringify(envLog)},'w'))\nprint(json.dumps({'parent_job_id':'job_0123456789abcdef'}))\n`)
const python = execFileSync('where.exe', ['python'], { encoding: 'utf8' }).split(/\r?\n/).find((line) => line.trim().toLowerCase().endsWith('.exe')).trim()
const old = { PYTHONPATH: process.env.PYTHONPATH, SCANSCI_PDF_DATA_DIR: process.env.SCANSCI_PDF_DATA_DIR }
process.env.PYTHONPATH = old.PYTHONPATH ? fakeRoot + delimiter + old.PYTHONPATH : fakeRoot
process.env.SCANSCI_PDF_DATA_DIR = join(fixture, 'scansci')
try {
  const result = await engineStartFullRead({ dataRoot: join(fixture, 'data'), python, scansciExe: 'untrusted.exe', school: '', legalOnly: false, outputDir: '', loginType: 'carsi', scansciPython: python, enginePython: python }, 'title_fixture')
  assert.equal(result.ok, true)
  const childEnv = JSON.parse(readFileSync(envLog, 'utf8'))
  assert.match(childEnv.wrapper, /scansci_wrap\.py$/)
  const legal = JSON.parse(readFileSync(join(fixture, 'data', 'oa-downloader', 'config.json'), 'utf8'))
  assert.equal(legal.download_strategy, 'oa_only'); assert.equal(legal.scihub_enabled, false)
  console.log('PASS: full-read 子进程注入受信 provider 且强制 OA-only 配置')
} finally {
  for (const [key, value] of Object.entries(old)) { if (value === undefined) delete process.env[key]; else process.env[key] = value }
  rmSync(fixture, { recursive: true, force: true })
}
