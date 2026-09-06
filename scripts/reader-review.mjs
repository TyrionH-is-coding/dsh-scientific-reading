import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'


const REVIEW_PORT = 8895
const REVIEW_URL = `http://127.0.0.1:${REVIEW_PORT}/review`
const FIXTURE_CASES = [
  'formula-outline',
  'superscript-text',
  'figures-captions',
]
const SCRUBBED_ENVIRONMENT = [
  'MINERU_API_TOKEN',
  'MINERU_API_KEY',
  'FEISHU_APP_ID',
  'FEISHU_APP_SECRET',
  'SR_SCANSCI_PROVIDER_WRAPPER',
  'SR_SCANSCI_PROVIDER_PYTHON',
  'SCANSCI_PDF_DATA_DIR',
]
const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')


class ReviewCliError extends Error {
  constructor(code) {
    super(code)
    this.code = code
  }
}


export function sanitizedEnvironment(source = process.env) {
  const result = { ...source }
  for (const name of SCRUBBED_ENVIRONMENT) result[name] = ''
  result.SR_SCANSCI_DISABLE_INSTITUTION = '1'
  result.PYTHONUTF8 = '1'
  result.PYTHONIOENCODING = 'utf-8'
  return result
}


export function hiddenSpawnOptions(options = {}) {
  return {
    windowsHide: true,
    shell: false,
    ...options,
  }
}


export function sourcePythonPath() {
  return [
    path.join(repositoryRoot, 'engine', 'src'),
    path.join(repositoryRoot, 'engine'),
    repositoryRoot,
  ].join(path.delimiter)
}


function parseArgs(argv) {
  const parsed = {
    reviewRoot: path.join(os.tmpdir(), 'dsh-scientific-reading-review'),
    caseName: null,
    paperId: null,
    dataRoot: null,
    newSession: false,
    stop: false,
  }
  for (let index = 0; index < argv.length; index += 1) {
    const name = argv[index]
    if (name === '--new-session') {
      parsed.newSession = true
      continue
    }
    if (name === '--stop') {
      parsed.stop = true
      continue
    }
    const value = argv[index + 1]
    if (value === undefined) throw new ReviewCliError('review_arguments_invalid')
    index += 1
    if (name === '--case') parsed.caseName = value
    else if (name === '--paper-id') parsed.paperId = value
    else if (name === '--data-root') parsed.dataRoot = value
    else if (name === '--review-root') parsed.reviewRoot = value
    else throw new ReviewCliError('review_arguments_invalid')
  }
  if (
    (parsed.caseName !== null && parsed.paperId !== null)
    || (parsed.paperId !== null && parsed.dataRoot === null)
    || (parsed.dataRoot !== null && parsed.paperId === null)
    || (
      parsed.stop
      && (
        parsed.caseName !== null
        || parsed.paperId !== null
        || parsed.dataRoot !== null
        || parsed.newSession
      )
    )
  ) throw new ReviewCliError('review_arguments_invalid')
  return parsed
}


async function readJson(file, code = 'review_session_invalid') {
  try {
    const value = JSON.parse(await fs.readFile(file, 'utf8'))
    if (value === null || typeof value !== 'object' || Array.isArray(value)) {
      throw new Error(code)
    }
    return value
  } catch (error) {
    if (error?.code === 'ENOENT') throw error
    throw new ReviewCliError(code)
  }
}


async function runChild(command, args, options) {
  return await new Promise((resolve, reject) => {
    const child = spawn(
      command,
      args,
      hiddenSpawnOptions({
        ...options,
        stdio: ['ignore', 'pipe', 'pipe'],
      }),
    )
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


function lastJsonLine(value) {
  const line = value.split(/\r?\n/).filter((item) => item.trim()).at(-1)
  if (!line) return null
  try {
    return JSON.parse(line)
  } catch {
    return null
  }
}


async function renderCandidate(options) {
  const python = process.env.SCIENTIFIC_READING_PYTHON
    || process.env.PYTHON
    || (process.platform === 'win32' ? 'python.exe' : 'python3')
  const args = [
    path.join(repositoryRoot, 'scripts', 'reader_review_render.py'),
    '--review-root', options.reviewRoot,
    '--repository-root', repositoryRoot,
  ]
  if (options.caseName !== null) args.push('--case', options.caseName)
  else if (options.paperId !== null) {
    args.push('--paper-id', options.paperId, '--data-root', options.dataRoot)
  } else args.push('--current-session')
  if (options.newSession) args.push('--new-session')
  const env = sanitizedEnvironment()
  env.PYTHONPATH = sourcePythonPath()
  const completed = await runChild(python, args, {
    cwd: repositoryRoot,
    env,
  })
  const payload = lastJsonLine(completed.stdout)
  if (completed.code !== 0 || payload?.status !== 'ready') {
    const error = lastJsonLine(completed.stderr)
    throw new ReviewCliError(
      error?.error_code || payload?.error_code || 'candidate_render_failed',
    )
  }
  return payload
}


async function requestHealth(port = REVIEW_PORT, timeoutMs = 400) {
  return await new Promise((resolve) => {
    const request = http.get(
      {
        host: '127.0.0.1',
        port,
        path: '/health',
        timeout: timeoutMs,
      },
      (response) => {
        const chunks = []
        response.on('data', (chunk) => chunks.push(chunk))
        response.on('end', () => {
          const body = Buffer.concat(chunks).toString('utf8')
          let metadata = null
          try { metadata = JSON.parse(body) } catch {}
          resolve({ reachable: true, status: response.statusCode, metadata })
        })
      },
    )
    request.on('timeout', () => request.destroy())
    request.on('error', () => resolve({ reachable: false, status: null, metadata: null }))
  })
}


function sameServer(left, right) {
  return Boolean(
    left
    && right
    && left.contract_version === 'reader-review-server-v1'
    && right.contract_version === left.contract_version
    && right.pid === left.pid
    && right.port === left.port
    && right.repository_root === left.repository_root
    && right.session_id === left.session_id
    && right.token === left.token
  )
}


async function removeMetadataIfOwned(serverFile, expected) {
  try {
    const current = await readJson(serverFile, 'review_server_metadata_invalid')
    if (current.pid === expected.pid && current.token === expected.token) {
      await fs.rm(serverFile, { force: true })
    }
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error
  }
}


async function existingServer(reviewRoot, session) {
  const serverFile = path.join(reviewRoot, 'server.json')
  let metadata
  try {
    metadata = await readJson(serverFile, 'review_server_metadata_invalid')
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error
    const occupied = await requestHealth()
    if (occupied.reachable) throw new ReviewCliError('review_port_in_use')
    return null
  }
  const health = await requestHealth(metadata.port)
  if (health.reachable) {
    if (
      !sameServer(metadata, health.metadata)
      || metadata.port !== REVIEW_PORT
      || metadata.repository_root !== repositoryRoot
      || metadata.session_id !== session.session_id
    ) throw new ReviewCliError('review_server_identity_mismatch')
    return metadata
  }
  await removeMetadataIfOwned(serverFile, metadata)
  const occupied = await requestHealth()
  if (occupied.reachable) throw new ReviewCliError('review_port_in_use')
  return null
}


export async function startOrReuseServer(reviewRoot) {
  const session = await readJson(
    path.join(reviewRoot, 'session.json'),
    'review_session_invalid',
  )
  if (
    session.contract_version !== 'reader-review-session-v1'
    || !/^[0-9a-f]{32}$/.test(session.session_id ?? '')
  ) throw new ReviewCliError('review_session_invalid')
  const existing = await existingServer(reviewRoot, session)
  if (existing !== null) return { state: 'reused', metadata: existing }

  const token = crypto.randomBytes(24).toString('hex')
  const child = spawn(
    process.execPath,
    [
      path.join(repositoryRoot, 'scripts', 'reader-review-server.mjs'),
      '--review-root', reviewRoot,
      '--repository-root', repositoryRoot,
      '--port', String(REVIEW_PORT),
      '--session-id', session.session_id,
      '--token', token,
    ],
    hiddenSpawnOptions({
      cwd: repositoryRoot,
      env: sanitizedEnvironment(),
      detached: true,
      stdio: 'ignore',
    }),
  )
  const deadline = Date.now() + 5000
  let metadata = null
  while (Date.now() < deadline) {
    const health = await requestHealth(REVIEW_PORT, 250)
    if (
      health.reachable
      && health.metadata?.pid === child.pid
      && health.metadata?.token === token
      && health.metadata?.session_id === session.session_id
      && health.metadata?.repository_root === repositoryRoot
    ) {
      metadata = health.metadata
      break
    }
    if (child.exitCode !== null) break
    await new Promise((resolve) => setTimeout(resolve, 75))
  }
  if (metadata === null) {
    if (child.exitCode === null) child.kill('SIGTERM')
    throw new ReviewCliError('review_server_start_failed')
  }
  child.unref()
  return { state: 'started', metadata }
}


export async function stopServer(reviewRoot) {
  const serverFile = path.join(reviewRoot, 'server.json')
  let metadata
  try {
    metadata = await readJson(serverFile, 'review_server_metadata_invalid')
  } catch (error) {
    if (error?.code === 'ENOENT') return 'not_running'
    throw error
  }
  const health = await requestHealth(metadata.port)
  if (!health.reachable) {
    await removeMetadataIfOwned(serverFile, metadata)
    return 'stale_cleaned'
  }
  if (!sameServer(metadata, health.metadata)) {
    throw new ReviewCliError('review_server_identity_mismatch')
  }
  try {
    process.kill(metadata.pid, 'SIGTERM')
  } catch (error) {
    if (error?.code !== 'ESRCH') throw new ReviewCliError('review_server_stop_failed')
  }
  const deadline = Date.now() + 3000
  while (Date.now() < deadline) {
    if (!(await requestHealth(metadata.port, 150)).reachable) break
    await new Promise((resolve) => setTimeout(resolve, 75))
  }
  if ((await requestHealth(metadata.port, 150)).reachable) {
    try { process.kill(metadata.pid, 'SIGKILL') } catch (error) {
      if (error?.code !== 'ESRCH') throw new ReviewCliError('review_server_stop_failed')
    }
  }
  await removeMetadataIfOwned(serverFile, metadata)
  return 'stopped'
}


async function main() {
  const options = parseArgs(process.argv.slice(2))
  options.reviewRoot = path.resolve(options.reviewRoot)
  if (options.stop) {
    const state = await stopServer(options.reviewRoot)
    process.stdout.write(`${JSON.stringify({ ok: true, server: state })}\n`)
    return
  }
  const manifest = await renderCandidate(options)
  const server = await startOrReuseServer(options.reviewRoot)
  process.stdout.write(`${JSON.stringify({
    ok: true,
    url: REVIEW_URL,
    revision: manifest.revision,
    case: manifest.selected_case,
    server: server.state,
  })}\n`)
}


const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : ''
if (invokedPath === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    const errorCode = error instanceof ReviewCliError
      ? error.code
      : 'reader_review_failed'
    const payload = { ok: false, error_code: errorCode }
    if (errorCode === 'review_source_required') {
      payload.available_cases = FIXTURE_CASES
    }
    process.stderr.write(`${JSON.stringify(payload)}\n`)
    process.exitCode = 1
  })
}
