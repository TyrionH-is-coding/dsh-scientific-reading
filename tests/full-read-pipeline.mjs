import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

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
