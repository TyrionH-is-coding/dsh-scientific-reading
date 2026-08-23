import assert from 'node:assert/strict'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const root = fileURLToPath(new URL('..', import.meta.url))
const verifierSource = readFileSync(join(root, 'scripts', 'verify-profile-runtime.mjs'), 'utf8')
assert.match(verifierSource, /timeout: COMMAND_TIMEOUT_MS/, '前置同步命令必须设置超时')
assert.match(verifierSource, /dsh_shutdown_failed/, '验证器必须拒绝无法确认退出的 DSH 子进程')
const fixture = mkdtempSync(join(tmpdir(), 'sr-runtime-fixture-'))
const fakeDsh = join(fixture, 'fake-dsh.mjs')

writeFileSync(fakeDsh, `
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { resolve, sep } from 'node:path'
import { tmpdir } from 'node:os'

const args = process.argv.slice(2)
const capturePath = process.env.FAKE_DSH_CAPTURE

function capture(extra) {
  let current = {}
  if (capturePath && existsSync(capturePath)) current = JSON.parse(readFileSync(capturePath, 'utf8'))
  writeFileSync(capturePath, JSON.stringify({ ...current, ...extra }))
}

if (args.length === 1 && args[0] === '--version') {
  console.log('0.1.0-rc.7')
  process.exit(0)
}

if (args[0] === 'plugin') {
  const expected = ['plugin', '--profile', 'web', 'add']
  const expectedEnd = ['--offline', '--ignore-scripts']
  if (args.length !== 7 || !expected.every((value, index) => args[index] === value) ||
      !existsSync(args[4]) || !expectedEnd.every((value, index) => args[index + 5] === value) ||
      !process.env.DSH_HOME || !process.env.DSH_HOME.startsWith(resolve(tmpdir()) + sep)) {
    process.exit(8)
  }
  capture({
    dshHome: process.env.DSH_HOME,
    userProfile: process.env.USERPROFILE,
    secretPresentAtInstall: Boolean(process.env.FEISHU_APP_ID || process.env.FEISHU_APP_SECRET),
  })
  process.exit(0)
}

const expectedStart = ['--profile', 'web', '--host', '127.0.0.1', '--port', '0']
if (args.length === expectedStart.length && expectedStart.every((value, index) => args[index] === value)) {
  capture({ secretPresentAtStart: Boolean(process.env.FEISHU_APP_ID || process.env.FEISHU_APP_SECRET) })
  if (process.env.FAKE_DSH_MODE === 'failure') {
    console.error("Cannot find package 'schemastery'")
    process.exit(23)
  }
  const paperId = 'doi_10.48550_arxiv.1706.03762'
  const requests = []
  const server = createServer((req, res) => {
    requests.push(req.url)
    capture({ requests })
    const bodies = {
      '/': '<!doctype html><p>fake dsh root</p>',
      '/plugins/@dsh-external/dsh-scientific-reading/client.js': 'window.__ModuleLoader__.load({})',
      '/sr/api/papers': JSON.stringify({ papers: [{ paper_id: paperId, title: 'Attention Is All You Need' }] }),
      ['/sr/api/paper/' + paperId]: JSON.stringify({ paper_id: paperId, item: { title: 'Attention Is All You Need' } }),
      ['/sr/reading/' + paperId]: '<!doctype html><p>fixture quick read</p>',
      ['/sr/reader/' + paperId]: '<!doctype html><p>fixture full reader</p>',
    }
    const body = bodies[req.url]
    res.writeHead(body ? 200 : 404, { 'Content-Type': 'text/html; charset=utf-8' })
    res.end(body || 'not found')
  })
  server.listen(0, '127.0.0.1', () => {
    const address = server.address()
    console.log('dsh web: http://127.0.0.1:' + address.port)
  })
  const stop = () => server.close(() => process.exit(0))
  process.on('SIGTERM', stop)
  process.on('SIGINT', stop)
  await new Promise(() => {})
}

process.exit(9)
`, 'utf8')

function run(mode) {
  const capturePath = join(fixture, `capture-${mode}.json`)
  writeFileSync(capturePath, '{}', 'utf8')
  const result = spawnSync(process.execPath, [join(root, 'scripts', 'verify-profile-runtime.mjs'), '--dsh-bin', fakeDsh], {
    cwd: root,
    encoding: 'utf8',
    timeout: 60_000,
    env: {
      ...process.env,
      FAKE_DSH_MODE: mode,
      FAKE_DSH_CAPTURE: capturePath,
      SR_PROFILE_RUNTIME_FAKE_ENGINE: '1',
      FEISHU_APP_ID: 'must-not-leak',
      FEISHU_APP_SECRET: 'must-not-leak',
      npm_execpath: '',
    },
  })
  return { result, capture: JSON.parse(readFileSync(capturePath, 'utf8')) }
}

function assertIsolatedCapture(capture) {
  assert.equal(capture.secretPresentAtInstall, false)
  assert.equal(capture.secretPresentAtStart, false)
  assert.equal(existsSync(capture.dshHome), false)
  assert.equal(existsSync(capture.userProfile), false)
}

try {
  const success = run('success')
  assert.equal(success.result.status, 0, success.result.stderr)
  assert.match(success.result.stdout, /profile_runtime_verified/)
  assertIsolatedCapture(success.capture)
  assert.deepEqual(success.capture.requests, [
    '/',
    '/plugins/@dsh-external/dsh-scientific-reading/client.js',
    '/sr/api/papers',
    '/sr/api/paper/doi_10.48550_arxiv.1706.03762',
    '/sr/reading/doi_10.48550_arxiv.1706.03762',
    '/sr/reader/doi_10.48550_arxiv.1706.03762',
  ])

  const failure = run('failure')
  assert.notEqual(failure.result.status, 0)
  assert.match(failure.result.stderr, /dsh_exited_before_ready/)
  assert.doesNotMatch(failure.result.stderr, /must-not-leak/)
  assertIsolatedCapture(failure.capture)

  console.log('PASS: Profile Bundle 真实启动验证器')
} finally {
  rmSync(fixture, { recursive: true, force: true })
}
