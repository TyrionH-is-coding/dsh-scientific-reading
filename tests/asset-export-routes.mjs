import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

delete process.env.FEISHU_APP_ID
delete process.env.FEISHU_APP_SECRET

const routes = readFileSync(new URL('../src/routes.ts', import.meta.url), 'utf8')
const cli = readFileSync(new URL('../src/cli.ts', import.meta.url), 'utf8')
assert.match(routes, /action === 'export'/)
assert.match(routes, /action === 'assets'/)
assert.match(routes, /engineResolveArtifact\(config, id, 'exports'\)/)
assert.match(cli, /\['artifact-resolve', '--paper-id', paperId, '--kind', kind\]/)
assert.match(routes, /asset_sha_mismatch/)

console.log('PASS: 图表导出路由只消费引擎验证的 artifact resolver')
