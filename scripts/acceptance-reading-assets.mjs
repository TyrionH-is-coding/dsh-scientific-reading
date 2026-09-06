import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import {
  request, resolveDshRuntime, sanitizedDshEnvironment, snapshot3080,
  startReaderWithRetry, stopOwned,
} from './acceptance-dsh.mjs'

// 使用 acceptance:dsh 已安装的实际包，以及 library-assets-tools 的恢复现场。
const [acceptanceArgument, assetsArgument] = process.argv.slice(2)
assert.ok(acceptanceArgument && assetsArgument, '需要隔离 DSH 验收根与阅读资产 evidence.json 路径')
const acceptanceRoot = path.resolve(acceptanceArgument)
assert.equal(path.dirname(acceptanceRoot), path.resolve(os.tmpdir()))
assert.ok(path.basename(acceptanceRoot).startsWith('dsh-reader-acceptance-'))
const previous = JSON.parse(await fs.readFile(path.join(acceptanceRoot, 'evidence.json'), 'utf8'))
assert.equal(previous.status, 'passed')
assert.equal(previous.tarball_is_source_link, false)
const assets = JSON.parse(await fs.readFile(path.resolve(assetsArgument), 'utf8'))
assert.equal(assets.status, 'passed')
assert.equal(path.dirname(path.resolve(assets.root)), path.resolve(os.tmpdir()))
assert.ok(path.basename(assets.root).startsWith('sr-library-assets-tools-'))
assert.equal(path.dirname(path.resolve(assets.restored)), path.resolve(assets.root))
const profile = path.join(acceptanceRoot, 'dsh-home/profiles/reader-review-acceptance')
const plugin = await fs.realpath(path.join(profile, 'node_modules/@dsh-external/dsh-scientific-reading'))
assert.equal(plugin, await fs.realpath(assets.plugin))
const engineRoot = path.join(acceptanceRoot, 'data/.acceptance-engine')
assert.ok(path.resolve(assets.engine_import).startsWith(engineRoot + path.sep))
const python = process.env.SCIENTIFIC_READING_PYTHON || process.env.PYTHON
assert.ok(python, '需要已验证的 Python 解释器')
const workspaceSeed = path.join(acceptanceRoot, 'seed-assets-workspace.mjs')
await fs.writeFile(workspaceSeed, [
  'import { randomUUID } from "node:crypto"',
  'export const inject = ["workspaceRegistry", "sessions", "sessionPersistence"]',
  'export async function apply(ctx) {',
  '  const cwd = ' + JSON.stringify(assets.restored),
  '  const workspace = await ctx.workspaceRegistry.create(cwd, "阅读资产验收")',
  '  const session = ctx.sessions.create("asset-ui-" + randomUUID(), { meta: { cwd, agentPreset: "scientific-reading" } })',
  '  session.append("session/title", { title: "阅读资产界面验收" })',
  '  session.append("user/message", { id: randomUUID(), role: "user", source: { kind: "user" }, content: [{ type: "text", text: "这是合成本地界面验收夹具，没有启动模型或请求执行任务。" }] }, { surfaceOp: "append" })',
  '  await ctx.parallel("session/flush", session)',
  '  await workspace.attachSession(session.id)',
  '}', '',
].join('\n'), 'utf8')
await fs.writeFile(path.join(profile, 'cordis.patch.yml'), [
  '- id: scientific-reading', '  config:',
  '    dataRoot: ' + JSON.stringify(assets.restored),
  '    enginePython: ' + JSON.stringify(python),
  '    python: ' + JSON.stringify(python),
  '    legalOnly: true', '',
  '- id: session-title-llm',
  '  disabled: true', '',
  // 通过宿主公开 API 注册隔离夹具；浏览器不操作 Windows 原生文件夹对话框。
  '- insert:',
  '    - id: acceptance-workspace-seed',
  '      name: ' + JSON.stringify(pathToFileURL(workspaceSeed).href), '',
].join('\n'), 'utf8')
const env = sanitizedDshEnvironment()
Object.assign(env, { DSH_HOME: path.join(acceptanceRoot, 'dsh-home'), PYTHONPATH: engineRoot })
const runtime = await resolveDshRuntime()
const report = {
  status: 'running', tarball: previous.tarball, tarball_sha256: previous.tarball_sha256,
  plugin, engine_import: assets.engine_import, restored_root: assets.restored,
  schema_version: assets.restore.schema_version, reader_sha256: assets.reader_sha256,
  persistent_3080_before: await snapshot3080(), queries: {},
}
const reportPath = path.join(acceptanceRoot, 'reading-assets-http-evidence.json')
let host
try {
  const started = await startReaderWithRetry({ runtime, env, paperId: assets.paper_id, nonce: 'Recoverable reading asset', evidence: report })
  host = started.host
  const { port } = started
  const query = async (value) => {
    const response = await request(port, '/sr/api/library?page=1&page_size=10&query=' + encodeURIComponent(value), 10_000)
    assert.equal(response.status, 200, response.body)
    return JSON.parse(response.body)
  }
  for (const value of Object.keys(assets.queries)) {
    const found = await query(value)
    assert.equal(found.total, assets.queries[value].total, value)
    const types = found.items.flatMap(item => item.search_matches.map(match => match.content_type))
    assert.deepEqual(types, assets.queries[value].types, value)
    report.queries[value] = { total: found.total, types }
  }
  const located = await query('定位回跳')
  const match = located.items[0].search_matches.find(item => item.content_type === 'conclusion')
  assert.equal(match.evidence_status, 'location_verified')
  assert.equal(match.evidence_url, '/sr/evidence?conclusion_id=' + assets.conclusion_id)
  const jump = await request(port, match.evidence_url, 10_000)
  assert.equal(jump.status, 302, jump.body)
  assert.ok(jump.headers.location.startsWith('/sr/reader/' + assets.paper_id + '#block-'))
  const readerUrl = jump.headers.location.split('#')[0]
  const anchor = decodeURIComponent(jump.headers.location.split('#')[1])
  const reader = await request(port, readerUrl, 10_000)
  assert.equal(reader.status, 200)
  assert.ok(reader.body.includes('id="' + anchor + '"'), '返回的 Reader 必须含真实定位锚点')
  assert.equal(crypto.createHash('sha256').update(reader.body).digest('hex'), assets.reader_sha256)
  report.evidence_jump = { status: jump.status, location: jump.headers.location, anchor_present: true }
  const invalid = await request(port, '/sr/evidence?conclusion_id=..%2Fsecret', 10_000)
  assert.ok(invalid.status >= 400)
  const sourceMap = path.join(assets.restored, 'papers', assets.paper_id, assets.locator.generation, 'parsed/mineru/source_map.json')
  const saved = await fs.readFile(sourceMap)
  try {
    await fs.writeFile(sourceMap, Buffer.concat([saved, Buffer.from('\n')]))
    const stale = await request(port, match.evidence_url, 10_000)
    assert.equal(stale.status, 409, stale.body)
    const results = await query('定位回跳')
    const changed = results.items[0].search_matches.find(item => item.content_type === 'conclusion')
    assert.equal(changed.evidence_status, 'stale')
    assert.ok(!changed.evidence_url)
    report.stale_evidence = { status: stale.status, evidence_status: changed.evidence_status, link_absent: true }
  } finally {
    await fs.writeFile(sourceMap, saved)
  }
  const legacy = (await query('独立验证')).items[0].search_matches.find(item => item.content_type === 'conclusion')
  assert.equal(legacy.evidence_status, 'legacy_unverified')
  assert.ok(!legacy.evidence_url)
  await stopOwned(host)
  host = null
  const restart = {}
  const restarted = await startReaderWithRetry({ runtime, env, paperId: assets.paper_id, nonce: 'Recoverable reading asset', evidence: restart })
  host = restarted.host
  assert.equal(crypto.createHash('sha256').update(restarted.reader.body).digest('hex'), assets.reader_sha256)
  report.restart = { port: restarted.port, reader_unchanged: true, process: restart.process, startup_attempts: restart.startup_attempts }
  report.persistent_3080_after = await snapshot3080()
  assert.deepEqual(report.persistent_3080_after, report.persistent_3080_before)
  report.status = 'passed'
  report.browser_url = `http://127.0.0.1:${restarted.port}/`
  report.reader_url = `http://127.0.0.1:${restarted.port}${jump.headers.location}`
  await fs.writeFile(reportPath, JSON.stringify(report, null, 2), 'utf8')
  console.log(JSON.stringify({ status: 'passed', evidence: reportPath, browser_url: report.browser_url, reader_url: report.reader_url }))
  if (process.argv.includes('--serve')) {
    console.log(`浏览器检查结束后创建停止标记：${path.join(acceptanceRoot, 'stop-reading-assets')}`)
    const deadline = Date.now() + 30 * 60_000
    while (Date.now() < deadline) {
      if (await fs.stat(path.join(acceptanceRoot, 'stop-reading-assets')).then(() => true, () => false)) break
      await new Promise(resolve => setTimeout(resolve, 1000))
    }
  }
} catch (error) {
  report.status = 'failed'
  report.error = String(error.message || error)
  await fs.writeFile(reportPath, JSON.stringify(report, null, 2), 'utf8')
  throw error
} finally {
  if (host) await stopOwned(host)
}
