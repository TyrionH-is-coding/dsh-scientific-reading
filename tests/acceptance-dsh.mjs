import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath, pathToFileURL } from 'node:url'


const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const acceptancePath = path.join(repositoryRoot, 'scripts', 'acceptance-dsh.mjs')
const acceptance = await import(pathToFileURL(acceptancePath))

const sanitized = acceptance.sanitizedDshEnvironment({
  PATH: process.env.PATH,
  MINERU_API_TOKEN: 'secret-mineru',
  MINERU_API_KEY: 'secret-key',
  FEISHU_APP_ID: 'secret-id',
  FEISHU_APP_SECRET: 'secret-feishu',
  SR_SCANSCI_PROVIDER_WRAPPER: 'secret-wrapper',
  SR_SCANSCI_PROVIDER_PYTHON: 'secret-python',
  SCANSCI_PDF_DATA_DIR: 'secret-data',
})
for (const name of [
  'MINERU_API_TOKEN',
  'MINERU_API_KEY',
  'FEISHU_APP_ID',
  'FEISHU_APP_SECRET',
  'SR_SCANSCI_PROVIDER_WRAPPER',
  'SR_SCANSCI_PROVIDER_PYTHON',
  'SCANSCI_PDF_DATA_DIR',
]) assert.equal(sanitized[name], '')
assert.equal(sanitized.SR_SCANSCI_DISABLE_INSTITUTION, '1')
assert.equal(sanitized.DSH_TELEMETRY_DISABLED, '1')

const hidden = acceptance.hiddenDshSpawnOptions({ cwd: repositoryRoot })
assert.equal(hidden.windowsHide, true)
assert.equal(hidden.shell, false)
assert.equal(hidden.cwd, repositoryRoot)

const retryEvidence = { startup_attempts: [] }
const chosenPorts = [55101, 55102]
const stoppedHosts = []
const retryResult = await acceptance.startReaderWithRetry({
  runtime: { source: 'fake-dsh', command: 'fake-dsh', prefix: [] },
  env: {},
  paperId: 'fixture-paper',
  nonce: 'fixture-nonce',
  evidence: retryEvidence,
  choose: async () => chosenPorts.shift(),
  start: (_runtime, _env, port) => ({
    child: { pid: port, exitCode: port === 55101 ? 1 : null },
    output: {
      stdout: [Buffer.from(port === 55101 ? '' : 'ready')],
      stderr: [Buffer.from(port === 55101 ? 'EADDRINUSE' : '')],
    },
    startedAt: '2026-09-02T00:00:00.000Z',
  }),
  wait: async (_host, port) => {
    if (port === 55101) {
      const error = new Error('dsh_start_failed')
      error.code = 'dsh_start_failed'
      throw error
    }
    return { status: 200, body: 'fixture-nonce' }
  },
  stop: async (host) => stoppedHosts.push(host.child.pid),
})
assert.equal(retryResult.port, 55102)
assert.equal(retryResult.reader.status, 200)
assert.deepEqual(stoppedHosts, [55101])
assert.deepEqual(
  retryEvidence.startup_attempts.map((item) => item.status),
  ['failed', 'ready'],
)
assert.equal(retryEvidence.startup_attempts[0].stderr, 'EADDRINUSE')

if (process.argv.includes('--self-check')) {
  console.log('PASS: 隔离 DSH 验收静态安全合同通过')
} else {
  await runFullContract()
}


async function runFullContract() {
const base = await fs.mkdtemp(path.join(os.tmpdir(), 'dsh-acceptance-contract-'))
const fakePath = path.join(base, 'fake-dsh.mjs')
const logPath = path.join(base, 'fake-dsh.jsonl')
await fs.writeFile(fakePath, `
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'

const argv = process.argv.slice(2)
const envNames = [
  'DSH_HOME',
  'MINERU_API_TOKEN',
  'MINERU_API_KEY',
  'FEISHU_APP_ID',
  'FEISHU_APP_SECRET',
  'SR_SCANSCI_PROVIDER_WRAPPER',
  'SR_SCANSCI_PROVIDER_PYTHON',
  'SCANSCI_PDF_DATA_DIR',
  'SR_ACCEPTANCE_DATA_ROOT',
  'SR_ACCEPTANCE_PAPER_ID',
  'SR_ACCEPTANCE_NONCE',
]
const record = {
  argv,
  env: Object.fromEntries(envNames.map((name) => [name, process.env[name] ?? null])),
  pid: process.pid,
}
fs.appendFileSync(process.env.DSH_ACCEPTANCE_LOG, JSON.stringify(record) + '\\n')

if (argv[0] === 'plugin') {
  const profile = argv[argv.indexOf('--profile') + 1]
  const tarball = argv[argv.indexOf('add') + 1]
  const profileDir = path.join(process.env.DSH_HOME, 'profiles', profile)
  const pluginDir = path.join(
    profileDir,
    'node_modules',
    '@dsh-external',
    'dsh-scientific-reading',
  )
  fs.mkdirSync(pluginDir, { recursive: true })
  fs.writeFileSync(
    path.join(pluginDir, 'package.json'),
    JSON.stringify({ name: '@dsh-external/dsh-scientific-reading', version: '0.0.1' }),
  )
  fs.writeFileSync(
    path.join(profileDir, 'package.json'),
    JSON.stringify({
      name: 'fake-profile',
      private: true,
      dsh: { profile: { bundles: ['@dsh-external/dsh-scientific-reading'] } },
      dependencies: { '@dsh-external/dsh-scientific-reading': 'file:' + tarball },
    }),
  )
  process.exit(0)
}

if (process.env.FAKE_DSH_FAIL_START === '1') process.exit(23)
const port = Number(argv[argv.indexOf('--port') + 1])
const paperId = process.env.SR_ACCEPTANCE_PAPER_ID
const reader = fs.readFileSync(process.env.SR_ACCEPTANCE_READER_PATH)
const server = http.createServer((request, response) => {
  if (request.url === '/sr/reader/' + encodeURIComponent(paperId)) {
    response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
    response.end(reader)
    return
  }
  response.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' })
  response.end('not found')
})
server.listen(port, '127.0.0.1')
const stop = () => server.close(() => process.exit(0))
process.on('SIGTERM', stop)
process.on('SIGINT', stop)
`, 'utf8')


function runAcceptance(extraEnv = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [acceptancePath], {
      cwd: repositoryRoot,
      env: {
        ...process.env,
        DSH_ACCEPTANCE_BIN: fakePath,
        DSH_ACCEPTANCE_LOG: logPath,
        DSH_ACCEPTANCE_KEEP_SUCCESS: '1',
        DSH_ACCEPTANCE_TEST_MODE: '1',
        MINERU_API_TOKEN: 'must-not-be-used',
        FEISHU_APP_SECRET: 'must-not-be-used',
        ...extraEnv,
      },
      windowsHide: true,
      shell: false,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    const stdout = []
    const stderr = []
    child.stdout.on('data', (chunk) => stdout.push(chunk))
    child.stderr.on('data', (chunk) => stderr.push(chunk))
    child.once('error', reject)
    child.once('exit', (code) => resolve({
      code,
      stdout: Buffer.concat(stdout).toString('utf8'),
      stderr: Buffer.concat(stderr).toString('utf8'),
    }))
  })
}


const ownedRoots = []
try {
  const success = await runAcceptance()
  assert.equal(success.code, 0, success.stderr)
  const summary = JSON.parse(success.stdout.trim().split(/\r?\n/).at(-1))
  assert.equal(summary.ok, true)
  assert.equal(summary.profile, 'reader-review-acceptance')
  assert.notEqual(summary.port, 3080)
  assert.equal(summary.route_status, 200)
  assert.equal(summary.invalid_status >= 400, true)
  assert.equal(summary.reader_revision, true)
  assert.equal(summary.review_toolbar_absent, true)
  assert.equal(summary.remote_resources_absent, true)
  assert.equal(summary.restart_reader_unchanged, true)
  assert.equal(summary.cleaned, false)
  ownedRoots.push(summary.evidence_root)

  const evidence = JSON.parse(
    await fs.readFile(path.join(summary.evidence_root, 'evidence.json'), 'utf8'),
  )
  assert.equal(evidence.contract_version, 'reader-dsh-acceptance-v1')
  assert.equal(evidence.tarball.endsWith('.tgz'), true)
  assert.equal(evidence.tarball_is_source_link, false)
  assert.equal(evidence.profile, 'reader-review-acceptance')
  assert.equal(evidence.port, summary.port)
  assert.match(evidence.route.paper_id, /^title_[0-9a-f]{12}$/)
  assert.equal(evidence.fixture?.paper_id, evidence.route.paper_id)
  assert.match(evidence.fixture?.source_sha256 ?? '', /^[0-9a-f]{64}$/)
  assert.equal(
    evidence.fixture?.reader_rel_path,
    `generations/${evidence.fixture?.source_sha256.slice(0, 16)}/reading/reader.html`,
  )
  assert.equal(evidence.fixture?.library_status, 'full_read_ready')
  assert.equal(evidence.fixture?.artifact_status, 'ready')

  const records = (await fs.readFile(logPath, 'utf8'))
    .trim()
    .split(/\r?\n/)
    .map((line) => JSON.parse(line))
  assert.equal(records.length, 3)
  const install = records[0]
  assert.deepEqual(install.argv.slice(0, 4), [
    'plugin',
    '--profile',
    'reader-review-acceptance',
    'add',
  ])
  assert.equal(install.argv[4].endsWith('.tgz'), true)
  assert.equal(install.argv.includes('--ignore-scripts'), true)
  assert.equal(install.argv.includes('--offline'), true)
  const started = records[1]
  assert.deepEqual(started.argv.slice(0, 2), [
    '--profile',
    'reader-review-acceptance',
  ])
  assert.equal(started.argv.includes('--host'), true)
  assert.equal(started.argv.includes('--port'), true)
  assert.equal(Number(started.argv[started.argv.indexOf('--port') + 1]), summary.port)
  assert.notEqual(records[2].pid, started.pid)
  assert.equal(records[2].env.DSH_HOME, started.env.DSH_HOME)
  assert.equal(evidence.restart.status, 200)
  assert.equal(evidence.restart.reader_unchanged, true)
  assert.equal(path.resolve(started.env.DSH_HOME).startsWith(path.resolve(os.tmpdir())), true)
  for (const record of records) {
    for (const name of [
      'MINERU_API_TOKEN',
      'MINERU_API_KEY',
      'FEISHU_APP_ID',
      'FEISHU_APP_SECRET',
      'SR_SCANSCI_PROVIDER_WRAPPER',
      'SR_SCANSCI_PROVIDER_PYTHON',
      'SCANSCI_PDF_DATA_DIR',
    ]) assert.equal(record.env[name], '')
  }

  await fs.writeFile(logPath, '', 'utf8')
  const failed = await runAcceptance({ FAKE_DSH_FAIL_START: '1' })
  assert.notEqual(failed.code, 0)
  const failure = JSON.parse(failed.stderr.trim().split(/\r?\n/).at(-1))
  assert.equal(failure.ok, false)
  assert.equal(failure.error_code, 'dsh_start_failed')
  assert.equal(typeof failure.evidence_root, 'string')
  ownedRoots.push(failure.evidence_root)
  await fs.access(path.join(failure.evidence_root, 'evidence.json'))

  console.log('PASS: 隔离 DSH tarball、临时 Profile、路由与进程所有权合同通过')
} finally {
  for (const root of ownedRoots) {
    const resolved = path.resolve(root)
    if (resolved.startsWith(path.resolve(os.tmpdir()))) {
      await fs.rm(resolved, { recursive: true, force: true })
    }
  }
  await fs.rm(base, { recursive: true, force: true })
}
}
