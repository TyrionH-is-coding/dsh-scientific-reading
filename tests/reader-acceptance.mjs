import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath, pathToFileURL } from 'node:url'


const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const scriptPath = path.join(repositoryRoot, 'scripts', 'reader-acceptance.mjs')
const acceptance = await import(pathToFileURL(scriptPath))

const sources = acceptance.acceptanceSources({
  selected_case: 'fixture_real_paper',
  cases: {
    fixture_real_paper: {
      kind: 'paper',
      paper_id: 'fixture_real_paper',
      data_root: 'D:/temporary-data',
    },
  },
})
assert.deepEqual(sources.slice(0, 3), [
  { kind: 'fixture', caseName: 'formula-outline' },
  { kind: 'fixture', caseName: 'superscript-text' },
  { kind: 'fixture', caseName: 'figures-captions' },
])
assert.deepEqual(sources[3], {
  kind: 'paper',
  paperId: 'fixture_real_paper',
  dataRoot: 'D:/temporary-data',
})
assert.equal(acceptance.acceptanceSources(null).length, 3)

const lifecycle = []
const pausedResult = await acceptance.withOwnedReviewServerPaused(
  'D:/review-root',
  async () => {
    lifecycle.push('task')
    return 'completed'
  },
  {
    stop: async () => {
      lifecycle.push('stop')
      return 'stopped'
    },
    start: async () => lifecycle.push('start'),
  },
)
assert.equal(pausedResult, 'completed')
assert.deepEqual(lifecycle, ['stop', 'task', 'start'])

const noServerLifecycle = []
await acceptance.withOwnedReviewServerPaused(
  'D:/review-root',
  async () => noServerLifecycle.push('task'),
  {
    stop: async () => 'not_running',
    start: async () => noServerLifecycle.push('start'),
  },
)
assert.deepEqual(noServerLifecycle, ['task'])

const errorLifecycle = []
await assert.rejects(
  acceptance.withOwnedReviewServerPaused(
    'D:/review-root',
    async () => {
      errorLifecycle.push('task')
      throw new Error('expected-task-failure')
    },
    {
      stop: async () => {
        errorLifecycle.push('stop')
        return 'stopped'
      },
      start: async () => errorLifecycle.push('start'),
    },
  ),
  /expected-task-failure/,
)
assert.deepEqual(errorLifecycle, ['stop', 'task', 'start'])

const safeEnv = acceptance.sanitizedAcceptanceEnvironment({
  PATH: process.env.PATH,
  MINERU_API_TOKEN: 'mineru-secret',
  MINERU_API_KEY: 'mineru-key',
  FEISHU_APP_ID: 'feishu-id',
  FEISHU_APP_SECRET: 'feishu-secret',
  SR_SCANSCI_PROVIDER_WRAPPER: 'wrapper',
  SR_SCANSCI_PROVIDER_PYTHON: 'python-provider',
  SCANSCI_PDF_DATA_DIR: 'provider-data',
})
for (const name of [
  'MINERU_API_TOKEN',
  'MINERU_API_KEY',
  'FEISHU_APP_ID',
  'FEISHU_APP_SECRET',
  'SR_SCANSCI_PROVIDER_WRAPPER',
  'SR_SCANSCI_PROVIDER_PYTHON',
  'SCANSCI_PDF_DATA_DIR',
]) assert.equal(safeEnv[name], '')
assert.equal(safeEnv.SR_SCANSCI_DISABLE_INSTITUTION, '1')

const commands = acceptance.acceptanceCommandPlan('python-test')
assert.deepEqual(commands.map((item) => item.id), [
  'python-reader',
  'node-review-server',
  'node-review-ui',
  'node-review-cli',
  'node-acceptance-self-check',
])
const commandText = commands
  .map((item) => [item.command, ...item.args].join(' '))
  .join('\n')
for (const required of [
  'engine/tests/test_reader_preview.py',
  'engine/tests/test_reader_review_fixtures.py',
  'engine/tests/test_reader_review_render.py',
  'engine/tests/test_worker_full_read.py',
  'engine/tests/test_reader_interactions.py',
  'engine/tests/test_reader_content_folding.py',
  'engine/tests/test_reader_citations.py',
  'tests/reader-review-server.mjs',
  'tests/reader-review-ui.mjs',
  'tests/reader-review-cli.mjs',
]) assert.match(commandText, new RegExp(required.replaceAll('/', '[/\\\\]')))
assert.doesNotMatch(
  commandText,
  /(?:\bmineru\b|\bdownload\b|\bfeishu\b|\bcurl\b|invoke-webrequest|npm\s+(?:install|ci))/i,
)

const seen = []
const failed = await acceptance.runCommandPlan(
  commands.slice(0, 2),
  async (entry, env) => {
    seen.push({ entry, env })
    return { code: entry.id === 'node-review-server' ? 1 : 0 }
  },
  safeEnv,
)
assert.equal(failed.status, 'failed')
assert.equal(failed.passed, 1)
assert.equal(failed.failed, 1)
assert.equal(seen.every((item) => item.env.MINERU_API_TOKEN === ''), true)

const fixtureHtml = {
  'formula-outline': '<!doctype html><nav class="toc"><h2>3 Model Architecture</h2><h3>3.2 Attention</h3><h4>3.2.1 Scaled Dot-Product Attention</h4></nav><math><mfrac></mfrac></math>',
  'superscript-text': '<!doctype html><sup>*</sup><sub>2</sub><p>modified firmly</p>',
  'figures-captions': '<!doctype html><figure><img src="data:image/svg+xml;base64,AA=="><figcaption class="asset-caption">A deliberately long engineering caption</figcaption></figure><table><caption>Measurements</caption></table>',
}
for (const [caseName, html] of Object.entries(fixtureHtml)) {
  assert.deepEqual(acceptance.validateReaderHtml(caseName, html), [])
}
assert.ok(
  acceptance.validateReaderHtml(
    'formula-outline',
    `${fixtureHtml['formula-outline']}\\frac{Q}{K}<div id="reader-frame"></div>`,
  ).length >= 2,
)

const base = await fs.mkdtemp(path.join(os.tmpdir(), 'reader-acceptance-test-'))
try {
  const manifestPath = path.join(base, 'review-manifest.json')
  await fs.writeFile(
    manifestPath,
    JSON.stringify({
      contract_version: 'reader-review-manifest-v1',
      revision: 4,
      status: 'ready',
      cases: {},
      tests: { status: 'pending' },
      browser_qa: { status: 'passed' },
    }),
    'utf8',
  )
  await acceptance.writeAcceptanceResult(base, failed)
  const saved = JSON.parse(await fs.readFile(manifestPath, 'utf8'))
  assert.equal(saved.tests.status, 'failed')
  assert.equal(saved.tests.passed, 1)
  assert.equal(saved.tests.failed, 1)
  assert.equal(saved.browser_qa.status, 'pending')
  assert.deepEqual(saved.browser_qa.checks.map((item) => item.id), [
    'desktop',
    'tablet',
    'mobile',
  ])
} finally {
  await fs.rm(base, { recursive: true, force: true })
}

const selfCheck = await new Promise((resolve, reject) => {
  const child = spawn(process.execPath, [scriptPath, '--self-check'], {
    cwd: repositoryRoot,
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
assert.equal(selfCheck.code, 0, selfCheck.stderr)
assert.equal(JSON.parse(selfCheck.stdout.trim()).status, 'passed')

console.log('PASS: Reader 离线验收编排、失败写回与 HTML 预检合同通过')
