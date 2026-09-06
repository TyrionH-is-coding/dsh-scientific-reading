import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import {
  sanitizedEnvironment,
  sourcePythonPath,
  startOrReuseServer,
  stopServer,
} from './reader-review.mjs'


const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const FIXTURE_CASES = [
  'formula-outline',
  'superscript-text',
  'figures-captions',
]
const PYTHON_TESTS = [
  'engine/tests/test_reader_preview.py',
  'engine/tests/test_reader_review_fixtures.py',
  'engine/tests/test_reader_review_render.py',
  'engine/tests/test_worker_full_read.py',
  'engine/tests/test_reader_interactions.py',
  'engine/tests/test_reader_content_folding.py',
  'engine/tests/test_reader_citations.py',
]
const FORBIDDEN_COMMAND = /(?:\bmineru\b|\bdownload\b|\bfeishu\b|\bcurl\b|invoke-webrequest|npm\s+(?:install|ci))/i


class AcceptanceError extends Error {
  constructor(code) {
    super(code)
    this.code = code
  }
}


export function sanitizedAcceptanceEnvironment(source = process.env) {
  return sanitizedEnvironment(source)
}


export async function withOwnedReviewServerPaused(
  reviewRoot,
  operation,
  lifecycle = { stop: stopServer, start: startOrReuseServer },
) {
  const state = await lifecycle.stop(reviewRoot)
  try {
    return await operation()
  } finally {
    if (state === 'stopped') await lifecycle.start(reviewRoot)
  }
}


export function acceptanceSources(session) {
  const sources = FIXTURE_CASES.map((caseName) => ({
    kind: 'fixture',
    caseName,
  }))
  if (session === null || typeof session !== 'object') return sources
  const selected = session.selected_case
  const record = session.cases?.[selected]
  if (
    typeof selected === 'string'
    && record?.kind === 'paper'
    && typeof record.paper_id === 'string'
    && typeof record.data_root === 'string'
  ) {
    sources.push({
      kind: 'paper',
      paperId: record.paper_id,
      dataRoot: record.data_root,
    })
  }
  return sources
}


export function acceptanceCommandPlan(python) {
  return [
    {
      id: 'python-reader',
      command: python,
      args: ['-m', 'pytest', '-q', ...PYTHON_TESTS],
    },
    {
      id: 'node-review-server',
      command: process.execPath,
      args: ['tests/reader-review-server.mjs'],
    },
    {
      id: 'node-review-ui',
      command: process.execPath,
      args: ['tests/reader-review-ui.mjs'],
    },
    {
      id: 'node-review-cli',
      command: process.execPath,
      args: ['tests/reader-review-cli.mjs'],
    },
    {
      id: 'node-acceptance-self-check',
      command: process.execPath,
      args: ['tests/reader-acceptance.mjs', '--self-check'],
    },
  ]
}


function assertOfflineCommand(entry) {
  const command = [entry.command, ...entry.args].join(' ')
  if (FORBIDDEN_COMMAND.test(command)) {
    throw new AcceptanceError('acceptance_forbidden_command')
  }
}


function defaultRunner(entry, env) {
  return new Promise((resolve, reject) => {
    const child = spawn(entry.command, entry.args, {
      cwd: repositoryRoot,
      env,
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


function outcome(details) {
  const passed = details.filter((item) => item.status === 'passed').length
  const failed = details.length - passed
  return {
    status: failed === 0 ? 'passed' : 'failed',
    passed,
    failed,
    summary: `${passed} passed, ${failed} failed`,
    details,
  }
}


export async function runCommandPlan(
  commands,
  runner = defaultRunner,
  env = sanitizedAcceptanceEnvironment(),
) {
  const details = []
  for (const entry of commands) {
    assertOfflineCommand(entry)
    let completed
    try {
      completed = await runner(entry, env)
    } catch (error) {
      completed = { code: null, stderr: error?.message ?? String(error) }
    }
    details.push({
      id: entry.id,
      status: completed.code === 0 ? 'passed' : 'failed',
      exit_code: completed.code,
      error: completed.code === 0
        ? null
        : String(completed.stderr ?? '').trim().slice(-2000),
    })
  }
  return outcome(details)
}


export function validateReaderHtml(caseName, html) {
  const errors = []
  if (typeof html !== 'string' || !/<\!doctype html/i.test(html)) {
    errors.push('html_document_missing')
    return errors
  }
  if (/<(?:script|img|link)\b[^>]*(?:src|href)=["']https?:/i.test(html)) {
    errors.push('remote_resource_forbidden')
  }
  if (/\\(?:frac|sqrt|begin|end|mathrm|text)\b/.test(html)) {
    errors.push('raw_latex_placeholder')
  }
  if (/id=["'](?:case-select|reader-frame|build-status|failure-banner)["']/i.test(html)) {
    errors.push('review_toolbar_leaked')
  }
  if (
    /min-width\s*:\s*(?:[4-9]\d{2}|[1-9]\d{3,})px/i.test(html)
    || /[;{]\s*width\s*:\s*(?:1[1-9]\d\d|[2-9]\d{3,})px/i.test(html)
  ) errors.push('static_width_overflow')

  if (caseName === 'formula-outline') {
    for (const expected of [
      '3 Model Architecture',
      '3.2 Attention',
      '3.2.1 Scaled Dot-Product Attention',
    ]) {
      if (!html.includes(expected)) errors.push(`outline_missing:${expected}`)
    }
    if (!/<math\b/i.test(html)) errors.push('mathml_missing')
  }
  if (caseName === 'superscript-text') {
    if (!html.includes('<sup>*</sup>')) errors.push('explicit_sup_missing')
    if (!html.includes('<sub>2</sub>')) errors.push('explicit_sub_missing')
    if (/modi<sup>fi<\/sup>ed|<sup>fi<\/sup>rmly/i.test(html)) {
      errors.push('invalid_word_superscript')
    }
  }
  if (caseName === 'figures-captions') {
    if (!/<figure\b/i.test(html)) errors.push('figure_missing')
    if (!/class=["'][^"']*asset-caption/i.test(html)) {
      errors.push('caption_binding_missing')
    }
    if (!/data:image\//i.test(html)) errors.push('embedded_figure_missing')
    if (!/<table\b/i.test(html)) errors.push('table_missing')
  }
  return errors
}


function browserQaPending() {
  return {
    status: 'pending',
    checks: [
      { id: 'desktop', label: '桌面布局', status: 'pending' },
      { id: 'tablet', label: '平板布局', status: 'pending' },
      { id: 'mobile', label: '手机布局', status: 'pending' },
    ],
  }
}


async function readJson(file, missing = null) {
  try {
    const parsed = JSON.parse(await fs.readFile(file, 'utf8'))
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('json object required')
    }
    return parsed
  } catch (error) {
    if (error?.code === 'ENOENT' && missing !== null) return missing
    throw new AcceptanceError('acceptance_state_invalid')
  }
}


export async function writeAcceptanceResult(reviewRoot, result) {
  const root = path.resolve(reviewRoot)
  const manifestPath = path.join(root, 'review-manifest.json')
  const manifest = await readJson(manifestPath)
  if (manifest.contract_version !== 'reader-review-manifest-v1') {
    throw new AcceptanceError('acceptance_state_invalid')
  }
  manifest.tests = result
  manifest.browser_qa = browserQaPending()
  const temporary = path.join(
    root,
    `.review-manifest.${crypto.randomBytes(8).toString('hex')}.tmp`,
  )
  try {
    await fs.writeFile(
      temporary,
      `${JSON.stringify(manifest, null, 2)}\n`,
      { encoding: 'utf8', flag: 'wx' },
    )
    await fs.rename(temporary, manifestPath)
  } finally {
    await fs.rm(temporary, { force: true })
  }
}


function pythonCommand() {
  return process.env.SCIENTIFIC_READING_PYTHON
    || process.env.PYTHON
    || (process.platform === 'win32' ? 'python.exe' : 'python3')
}


async function renderSource(source, reviewRoot, newSession, env) {
  const args = [
    path.join(repositoryRoot, 'scripts', 'reader_review_render.py'),
    '--review-root', reviewRoot,
    '--repository-root', repositoryRoot,
  ]
  if (source.kind === 'fixture') args.push('--case', source.caseName)
  else args.push('--paper-id', source.paperId, '--data-root', source.dataRoot)
  if (newSession) args.push('--new-session')
  const completed = await defaultRunner(
    { id: 'candidate-render', command: pythonCommand(), args },
    env,
  )
  if (completed.code !== 0) {
    throw new AcceptanceError('acceptance_render_failed')
  }
}


async function htmlChecks(reviewRoot, sources) {
  const details = []
  for (const source of sources) {
    const caseName = source.kind === 'fixture' ? source.caseName : source.paperId
    let errors
    try {
      const html = await fs.readFile(
        path.join(reviewRoot, 'candidate', caseName, 'reader.html'),
        'utf8',
      )
      errors = validateReaderHtml(caseName, html)
    } catch {
      errors = ['candidate_missing']
    }
    details.push({
      id: `html:${caseName}`,
      status: errors.length === 0 ? 'passed' : 'failed',
      exit_code: errors.length === 0 ? 0 : 1,
      error: errors.length === 0 ? null : errors.join(', '),
    })
  }
  return details
}


function parseArgs(argv) {
  const options = {
    reviewRoot: path.join(os.tmpdir(), 'dsh-scientific-reading-review'),
    selfCheck: false,
  }
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === '--self-check') {
      options.selfCheck = true
      continue
    }
    if (argv[index] !== '--review-root' || argv[index + 1] === undefined) {
      throw new AcceptanceError('acceptance_arguments_invalid')
    }
    options.reviewRoot = argv[index + 1]
    index += 1
  }
  if (options.selfCheck && argv.length !== 1) {
    throw new AcceptanceError('acceptance_arguments_invalid')
  }
  return options
}


async function runAcceptance(reviewRoot) {
  const root = path.resolve(reviewRoot)
  const session = await readJson(path.join(root, 'session.json'), {})
  const hasSession = session.contract_version === 'reader-review-session-v1'
  const sources = acceptanceSources(hasSession ? session : null)
  const env = sanitizedAcceptanceEnvironment()
  env.PYTHONPATH = sourcePythonPath()

  let renderFailure = null
  for (let index = 0; index < sources.length; index += 1) {
    try {
      await renderSource(sources[index], root, !hasSession && index === 0, env)
    } catch (error) {
      renderFailure = {
        id: `render:${sources[index].caseName ?? sources[index].paperId}`,
        status: 'failed',
        exit_code: 1,
        error: error.code ?? 'acceptance_render_failed',
      }
      break
    }
  }

  let result
  if (renderFailure !== null) {
    result = outcome([renderFailure])
    await writeAcceptanceResult(root, result)
  } else {
    result = await withOwnedReviewServerPaused(root, async () => {
      const commands = acceptanceCommandPlan(pythonCommand())
      const commandResult = await runCommandPlan(commands, defaultRunner, env)
      const completed = outcome([
        ...commandResult.details,
        ...await htmlChecks(root, sources),
      ])
      await writeAcceptanceResult(root, completed)
      return completed
    })
  }
  return { result, sources }
}


async function main() {
  const options = parseArgs(process.argv.slice(2))
  if (options.selfCheck) {
    for (const entry of acceptanceCommandPlan('python-test')) {
      assertOfflineCommand(entry)
    }
    process.stdout.write(`${JSON.stringify({ ok: true, status: 'passed' })}\n`)
    return
  }
  const completed = await runAcceptance(options.reviewRoot)
  process.stdout.write(`${JSON.stringify({
    ok: completed.result.status === 'passed',
    status: completed.result.status,
    passed: completed.result.passed,
    failed: completed.result.failed,
    cases: completed.sources.map((source) => (
      source.caseName ?? source.paperId
    )),
    browser_qa: 'pending',
  })}\n`)
  if (completed.result.status !== 'passed') process.exitCode = 1
}


const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : ''
if (invokedPath === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    process.stderr.write(`${JSON.stringify({
      ok: false,
      error_code: error instanceof AcceptanceError
        ? error.code
        : 'reader_acceptance_failed',
    })}\n`)
    process.exitCode = 1
  })
}
