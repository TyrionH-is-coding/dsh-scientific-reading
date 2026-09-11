import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { sanitizedEnvironment } from './reader-review.mjs'


const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const PROFILE = 'reader-review-acceptance'
const CONTRACT = 'reader-dsh-acceptance-v1'


class DshAcceptanceError extends Error {
  constructor(code, evidenceRoot = null) {
    super(code)
    this.code = code
    this.evidenceRoot = evidenceRoot
  }
}


export function sanitizedDshEnvironment(source = process.env) {
  const env = sanitizedEnvironment(source)
  env.DSH_TELEMETRY_DISABLED = '1'
  return env
}


export function hiddenDshSpawnOptions(options = {}) {
  return {
    windowsHide: true,
    shell: false,
    ...options,
  }
}


function isWithin(parent, candidate) {
  const relative = path.relative(path.resolve(parent), path.resolve(candidate))
  return relative === '' || (
    relative !== '..'
    && !relative.startsWith(`..${path.sep}`)
    && !path.isAbsolute(relative)
  )
}


function assertOwnedTempRoot(root) {
  const resolved = path.resolve(root)
  if (
    !isWithin(os.tmpdir(), resolved)
    || path.basename(resolved).startsWith('dsh-reader-acceptance-') === false
  ) throw new DshAcceptanceError('acceptance_temp_root_invalid')
  return resolved
}


function runtimeFromPath(file) {
  const resolved = path.resolve(file)
  if (/\.(?:mjs|cjs|js)$/i.test(resolved)) {
    return { command: process.execPath, prefix: [resolved], source: resolved }
  }
  return { command: resolved, prefix: [], source: resolved }
}


export async function resolveDshRuntime() {
  if (process.env.DSH_ACCEPTANCE_BIN) {
    try {
      await fs.access(process.env.DSH_ACCEPTANCE_BIN)
      return runtimeFromPath(process.env.DSH_ACCEPTANCE_BIN)
    } catch {
      throw new DshAcceptanceError('dsh_runtime_missing')
    }
  }
  const installed = path.join(
    os.homedir(),
    '.dsh',
    'profiles',
    'node_modules',
    '@deepseek-ai',
    'dsh',
    'lib',
    'bin.js',
  )
  try {
    await fs.access(installed)
    return runtimeFromPath(installed)
  } catch {
    throw new DshAcceptanceError('dsh_runtime_missing')
  }
}


function runForeground(command, args, { cwd = repositoryRoot, env } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, hiddenDshSpawnOptions({
      cwd,
      env: env ?? sanitizedDshEnvironment(),
      stdio: ['ignore', 'pipe', 'pipe'],
    }))
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


function pythonCommand() {
  return process.env.SCIENTIFIC_READING_PYTHON
    || process.env.PYTHON
    || (process.platform === 'win32' ? 'python.exe' : 'python3')
}


function npmRuntime() {
  const script = process.env.npm_execpath || path.join(
    path.dirname(process.execPath),
    'node_modules',
    'npm',
    'bin',
    'npm-cli.js',
  )
  return { command: process.execPath, prefix: [script] }
}


export async function buildAndPack(root, evidence) {
  const env = sanitizedDshEnvironment()
  const npm = npmRuntime()
  const build = await runForeground(
    npm.command,
    [...npm.prefix, 'run', 'build'],
    { env },
  )
  evidence.steps.push({ id: 'build', exit_code: build.code })
  if (build.code !== 0) throw new DshAcceptanceError('plugin_build_failed', root)

  const packDirectory = path.join(root, 'package')
  await fs.mkdir(packDirectory, { recursive: true })
  const packed = await runForeground(
    npm.command,
    [...npm.prefix, 'pack', '--json', '--pack-destination', packDirectory],
    { env },
  )
  evidence.steps.push({ id: 'pack', exit_code: packed.code })
  let report
  try {
    const values = JSON.parse(packed.stdout)
    if (packed.code !== 0 || !Array.isArray(values) || values.length !== 1) {
      throw new Error('one pack result required')
    }
    report = values[0]
  } catch {
    throw new DshAcceptanceError('plugin_pack_failed', root)
  }
  const tarball = path.resolve(packDirectory, String(report.filename ?? ''))
  if (!isWithin(packDirectory, tarball) || !tarball.endsWith('.tgz')) {
    throw new DshAcceptanceError('plugin_pack_invalid', root)
  }
  await fs.access(tarball)
  const files = Array.isArray(report.files)
    ? report.files.map((entry) => String(entry.path ?? ''))
    : []
  for (const required of ['cordis.patch.yml', 'lib/index.js']) {
    if (!files.includes(required)) throw new DshAcceptanceError('plugin_pack_invalid', root)
  }
  if (!files.some((file) => /^dist\/python\/[^/]+\.whl$/.test(file))) {
    throw new DshAcceptanceError('plugin_pack_invalid', root)
  }
  evidence.tarball = tarball
  evidence.tarball_sha256 = crypto.createHash('sha256')
    .update(await fs.readFile(tarball))
    .digest('hex')
  evidence.pack_files = files.length
  return tarball
}


async function resolvedPythonCommand() {
  const probe = await runForeground(
    pythonCommand(),
    ['-c', 'import sys; print(sys.executable)'],
    { env: sanitizedDshEnvironment() },
  )
  const resolved = probe.stdout.trim().split(/\r?\n/).at(-1)
  if (probe.code !== 0 || !resolved || !path.isAbsolute(resolved)) {
    throw new DshAcceptanceError('python_runtime_missing')
  }
  return path.resolve(resolved)
}


export async function prepareEngine(dataRoot, evidence) {
  const python = await resolvedPythonCommand()
  if (process.env.DSH_ACCEPTANCE_TEST_MODE === '1') {
    return {
      python,
      pythonPath: [
        path.join(repositoryRoot, 'engine', 'src'),
        path.join(repositoryRoot, 'engine'),
        repositoryRoot,
      ].join(path.delimiter),
    }
  }
  const environment = path.join(dataRoot, '.acceptance-engine')
  const wheels = (await fs.readdir(path.join(repositoryRoot, 'dist', 'python')))
    .filter((name) => name.endsWith('.whl'))
  if (wheels.length !== 1) throw new DshAcceptanceError('engine_wheel_invalid')
  const installed = await runForeground(
    python,
    [
      '-m', 'pip', 'install',
      '--disable-pip-version-check',
      '--no-index',
      '--no-deps',
      '--target', environment,
      '--force-reinstall',
      path.join(repositoryRoot, 'dist', 'python', wheels[0]),
    ],
    { env: sanitizedDshEnvironment() },
  )
  evidence.steps.push({ id: 'engine-wheel', exit_code: installed.code })
  if (installed.code !== 0) throw new DshAcceptanceError('engine_install_failed')
  const probeEnv = sanitizedDshEnvironment()
  probeEnv.PYTHONPATH = environment
  const probed = await runForeground(
    python,
    ['-c', 'import scientific_reading; print(scientific_reading.__file__)'],
    { cwd: dataRoot, env: probeEnv },
  )
  evidence.steps.push({ id: 'engine-probe', exit_code: probed.code })
  if (
    probed.code !== 0
    || !isWithin(environment, probed.stdout.trim().split(/\r?\n/).at(-1) ?? '')
  ) throw new DshAcceptanceError('engine_probe_failed')
  return { python, pythonPath: environment }
}


export async function materializeFixture(dataRoot, nonce, evidence) {
  const code = `
import hashlib
import json
import sys
from pathlib import Path
from scientific_reading.full_read_renderer import FullReadRenderer
from scientific_reading.library_service import LibraryService
from scientific_reading.models import JobState, PaperMetadata, StageRecord
from scientific_reading.workspace import PaperWorkspace
from scripts.reader_review_fixtures import (
    FIXTURE_METHOD,
    FIXTURE_PARSER_VERSION,
    fixture_path,
    materialize_fixture_payload,
)

data_root = Path(sys.argv[1])
nonce = sys.argv[2]
payload = json.loads(fixture_path("formula-outline").read_text(encoding="utf-8"))
fixture_title = f"Fixture Acceptance {nonce}"
payload["metadata"]["title"] = fixture_title
payload["content_items"][0]["text"] = fixture_title
metadata = PaperMetadata.from_dict(payload["metadata"])
library = LibraryService(data_root)
try:
    paper_id = library.ingest(metadata)["paper_id"]
finally:
    library.close()
base = PaperWorkspace.create_for_paper_id(data_root, paper_id, metadata)
source_bytes = b"%PDF-1.4\\n% deterministic reader review fixture\\n% formula-outline\\n"
source_sha = hashlib.sha256(source_bytes).hexdigest()
generation = materialize_fixture_payload(
    payload,
    base.root / "generations" / source_sha[:16],
)
base.source_pdf.write_bytes(generation.source_pdf.read_bytes())
base.save_job(JobState(
    paper_id=paper_id,
    status="full_read_ready",
    stages={
        "paper_parse_upgrade": StageRecord(
            status="completed",
            result={
                "active_parsed_dir": "parsed/mineru",
                "active_workspace": f"generations/{source_sha[:16]}",
                "source_sha256": source_sha,
                "method": FIXTURE_METHOD,
                "mineru_version": FIXTURE_PARSER_VERSION,
            },
        )
    },
))
published = FullReadRenderer().render_completed(generation, paper_id=paper_id)
reader = Path(published["reader_html"])
reader_rel_path = reader.relative_to(base.root).as_posix()
library = LibraryService(data_root)
try:
    library.record_pdf_attachment(paper_id, source_sha, base.source_pdf.stat().st_size)
    library.publish_reader(paper_id, reader_rel_path)
    item = library.get_item(paper_id)
    artifact = library.conn.execute(
        "SELECT status FROM artifacts WHERE paper_id=? AND kind='reader'",
        (paper_id,),
    ).fetchone()
finally:
    library.close()
print(json.dumps({
    "paper_id": paper_id,
    "reader_path": str(reader),
    "reader_rel_path": reader_rel_path,
    "source_sha256": source_sha,
    "library_status": item["status"],
    "artifact_status": artifact["status"],
}))
`
  const env = sanitizedDshEnvironment()
  env.PYTHONPATH = [
    path.join(repositoryRoot, 'engine', 'src'),
    path.join(repositoryRoot, 'engine'),
    repositoryRoot,
  ].join(path.delimiter)
  const completed = await runForeground(
    pythonCommand(),
    ['-c', code, dataRoot, nonce],
    { env },
  )
  evidence.steps.push({ id: 'fixture', exit_code: completed.code })
  if (completed.code !== 0) throw new DshAcceptanceError('fixture_failed')
  let fixture
  try {
    fixture = JSON.parse(completed.stdout.trim().split(/\r?\n/).at(-1) ?? '')
  } catch {
    throw new DshAcceptanceError('fixture_failed')
  }
  if (
    !fixture?.paper_id
    || !fixture?.reader_path
    || !isWithin(dataRoot, fixture.reader_path)
  ) throw new DshAcceptanceError('fixture_failed')
  evidence.fixture = {
    paper_id: fixture.paper_id,
    reader_rel_path: fixture.reader_rel_path,
    source_sha256: fixture.source_sha256,
    library_status: fixture.library_status,
    artifact_status: fixture.artifact_status,
  }
  return { paperId: fixture.paper_id, readerPath: path.resolve(fixture.reader_path) }
}


async function atomicJson(file, value) {
  const temporary = `${file}.${crypto.randomBytes(8).toString('hex')}.tmp`
  try {
    await fs.writeFile(
      temporary,
      `${JSON.stringify(value, null, 2)}\n`,
      { encoding: 'utf8', flag: 'wx' },
    )
    await fs.rename(temporary, file)
  } finally {
    await fs.rm(temporary, { force: true })
  }
}


export async function installPlugin(runtime, home, tarball, dataRoot, enginePython, evidence) {
  const env = sanitizedDshEnvironment()
  env.DSH_HOME = home
  const args = [
    ...runtime.prefix,
    'plugin', '--profile', PROFILE,
    'add', tarball,
    '--ignore-scripts',
    '--offline',
  ]
  const installed = await runForeground(runtime.command, args, { env })
  evidence.steps.push({ id: 'plugin-install', exit_code: installed.code })
  if (installed.code !== 0) throw new DshAcceptanceError('plugin_install_failed')

  const profileDir = path.join(home, 'profiles', PROFILE)
  const profileFile = path.join(profileDir, 'package.json')
  const profile = JSON.parse(await fs.readFile(profileFile, 'utf8'))
  const dependency = profile.dependencies?.['@dsh-external/dsh-scientific-reading']
  if (typeof dependency !== 'string' || /^link:/i.test(dependency)) {
    throw new DshAcceptanceError('plugin_install_invalid')
  }
  const pluginDir = path.join(
    profileDir,
    'node_modules',
    '@dsh-external',
    'dsh-scientific-reading',
  )
  const pluginReal = await fs.realpath(pluginDir)
  const sourceLink = isWithin(repositoryRoot, pluginReal)
  evidence.tarball_is_source_link = sourceLink
  if (sourceLink || !isWithin(profileDir, pluginReal)) {
    throw new DshAcceptanceError('plugin_install_invalid')
  }
  const pluginPackage = JSON.parse(
    await fs.readFile(path.join(pluginDir, 'package.json'), 'utf8'),
  )
  if (pluginPackage.name !== '@dsh-external/dsh-scientific-reading') {
    throw new DshAcceptanceError('plugin_install_invalid')
  }

  profile.dsh ??= {}
  profile.dsh.profile ??= {}
  const existing = Array.isArray(profile.dsh.profile.bundles)
    ? profile.dsh.profile.bundles
    : []
  profile.dsh.profile.bundles = [
    '@deepseek-ai/dsh-base',
    '@deepseek-ai/dsh-web-app',
    ...existing.filter((name) => ![
      '@deepseek-ai/dsh-base',
      '@deepseek-ai/dsh-web-app',
      '@dsh-external/dsh-scientific-reading',
    ].includes(name)),
    '@dsh-external/dsh-scientific-reading',
  ]
  await atomicJson(profileFile, profile)
  const quote = (value) => JSON.stringify(path.resolve(value))
  await fs.writeFile(
    path.join(profileDir, 'cordis.patch.yml'),
    [
      '- id: scientific-reading',
      '  config:',
      `    dataRoot: ${quote(dataRoot)}`,
      `    enginePython: ${quote(enginePython)}`,
      `    python: ${quote(enginePython)}`,
      '    legalOnly: true',
      '',
    ].join('\n'),
    'utf8',
  )
}


async function choosePort() {
  return await new Promise((resolve, reject) => {
    const server = http.createServer()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : 0
      server.close((error) => error ? reject(error) : resolve(port))
    })
  })
}


export async function request(port, pathname, timeoutMs = 600) {
  return await new Promise((resolve) => {
    const call = http.get(
      { host: '127.0.0.1', port, path: pathname, timeout: timeoutMs },
      (response) => {
        const chunks = []
        response.on('data', (chunk) => chunks.push(chunk))
        response.on('end', () => resolve({
          reachable: true,
          status: response.statusCode ?? 0,
          contentType: String(response.headers['content-type'] ?? ''),
          headers: response.headers,
          body: Buffer.concat(chunks).toString('utf8'),
        }))
      },
    )
    call.on('timeout', () => call.destroy())
    call.on('error', () => resolve({
      reachable: false,
      status: 0,
      contentType: '',
      body: '',
    }))
  })
}


export async function snapshot3080() {
  const result = await request(3080, '/sr', 300)
  return {
    reachable: result.reachable,
    status: result.status,
    body_sha256: result.reachable
      ? crypto.createHash('sha256').update(result.body).digest('hex')
      : null,
  }
}


function startHost(runtime, env, port) {
  const child = spawn(
    runtime.command,
    [
      ...runtime.prefix,
      '--profile', PROFILE,
      '--host', '127.0.0.1',
      '--port', String(port),
    ],
    hiddenDshSpawnOptions({
      cwd: repositoryRoot,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
    }),
  )
  const output = { stdout: [], stderr: [] }
  child.stdout.on('data', (chunk) => {
    if (Buffer.concat(output.stdout).length < 64 * 1024) output.stdout.push(chunk)
  })
  child.stderr.on('data', (chunk) => {
    if (Buffer.concat(output.stderr).length < 64 * 1024) output.stderr.push(chunk)
  })
  return { child, output, startedAt: new Date().toISOString() }
}


export async function stopOwned(host) {
  const { child } = host
  if (child.exitCode !== null) return
  child.kill('SIGTERM')
  const exited = await Promise.race([
    new Promise((resolve) => child.once('exit', () => resolve(true))),
    new Promise((resolve) => setTimeout(() => resolve(false), 5000)),
  ])
  if (!exited && child.exitCode === null) child.kill('SIGKILL')
}


async function waitForReader(host, port, paperId, nonce) {
  const pathname = `/sr/reader/${encodeURIComponent(paperId)}`
  const deadline = Date.now() + 30000
  while (Date.now() < deadline) {
    const response = await request(port, pathname, 5000)
    if (response.status === 200 && response.body.includes(nonce)) return response
    if (host.child.exitCode !== null) {
      throw new DshAcceptanceError('dsh_start_failed')
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new DshAcceptanceError('dsh_route_timeout')
}


function startupAttempt(host, port, status, errorCode = null) {
  return {
    pid: host.child.pid,
    port,
    status,
    error_code: errorCode,
    exit_code: host.child.exitCode,
    stdout: Buffer.concat(host.output.stdout).toString('utf8'),
    stderr: Buffer.concat(host.output.stderr).toString('utf8'),
  }
}


export async function startReaderWithRetry({
  runtime,
  env,
  paperId,
  nonce,
  evidence,
  choose = choosePort,
  start = startHost,
  wait = waitForReader,
  stop = stopOwned,
}) {
  evidence.startup_attempts ??= []
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const port = await choose()
    if (port === 3080 || port < 1) {
      throw new DshAcceptanceError('acceptance_port_invalid')
    }
    const host = start(runtime, env, port)
    evidence.port = port
    evidence.process = {
      pid: host.child.pid,
      started_at: host.startedAt,
      command: runtime.source,
      profile: PROFILE,
      port,
    }
    try {
      const reader = await wait(host, port, paperId, nonce)
      evidence.startup_attempts.push(startupAttempt(host, port, 'ready'))
      return { host, port, reader }
    } catch (error) {
      const code = error?.code ?? 'dsh_start_failed'
      evidence.startup_attempts.push(startupAttempt(host, port, 'failed', code))
      await stop(host)
      if (code !== 'dsh_start_failed' || attempt === 1) throw error
    }
  }
  throw new DshAcceptanceError('dsh_start_failed')
}


async function writeEvidence(root, evidence) {
  await atomicJson(path.join(root, 'evidence.json'), evidence)
}


async function runAcceptance() {
  const runtime = await resolveDshRuntime()
  const root = assertOwnedTempRoot(
    await fs.mkdtemp(path.join(os.tmpdir(), 'dsh-reader-acceptance-')),
  )
  const home = path.join(root, 'dsh-home')
  const dataRoot = path.join(root, 'data')
  await fs.mkdir(home, { recursive: true })
  await fs.mkdir(dataRoot, { recursive: true })
  const nonce = crypto.randomBytes(18).toString('hex')
  const evidence = {
    contract_version: CONTRACT,
    status: 'running',
    profile: PROFILE,
    runtime: runtime.source,
    root,
    tarball: null,
    tarball_sha256: null,
    tarball_is_source_link: null,
    pack_files: 0,
    port: null,
    process: null,
    startup_attempts: [],
    route: null,
    persistent_3080_before: await snapshot3080(),
    persistent_3080_after: null,
    steps: [],
  }
  let host = null
  try {
    const tarball = await buildAndPack(root, evidence)
    const engine = await prepareEngine(dataRoot, evidence)
    const fixture = await materializeFixture(dataRoot, nonce, evidence)
    await installPlugin(
      runtime,
      home,
      tarball,
      dataRoot,
      engine.python,
      evidence,
    )
    const env = sanitizedDshEnvironment()
    Object.assign(env, {
      DSH_HOME: home,
      SR_ACCEPTANCE_DATA_ROOT: dataRoot,
      SR_ACCEPTANCE_PAPER_ID: fixture.paperId,
      SR_ACCEPTANCE_NONCE: nonce,
      SR_ACCEPTANCE_READER_PATH: fixture.readerPath,
      PYTHONPATH: engine.pythonPath,
    })
    const started = await startReaderWithRetry({
      runtime,
      env,
      paperId: fixture.paperId,
      nonce,
      evidence,
    })
    host = started.host
    const { port, reader } = started
    const invalid = await request(port, '/sr/reader/%2e%2e%2fsecret')
    const nested = await request(port, `/sr/reader/${fixture.paperId}/extra`)
    const readerRevision = /data-reader-revision=["'][0-9a-f]{64}["']/i.test(reader.body)
    const toolbarAbsent = !/id=["'](?:case-select|reader-frame|build-status|failure-banner)["']/i.test(reader.body)
    const remoteAbsent = !/<(?:script|img|link)\b[^>]*(?:src|href)=["']https?:/i.test(reader.body)
    if (
      !/^text\/html/i.test(reader.contentType)
      || !readerRevision
      || !toolbarAbsent
      || !remoteAbsent
      || invalid.status < 400
      || nested.status < 400
    ) throw new DshAcceptanceError('dsh_route_contract_failed')
    evidence.route = {
      paper_id: fixture.paperId,
      status: reader.status,
      invalid_status: Math.min(invalid.status, nested.status),
      reader_revision: readerRevision,
      review_toolbar_absent: toolbarAbsent,
      remote_resources_absent: remoteAbsent,
      body_sha256: crypto.createHash('sha256').update(reader.body).digest('hex'),
    }
    await stopOwned(host)
    host = null
    const restartEvidence = {}
    const restarted = await startReaderWithRetry({
      runtime,
      env,
      paperId: fixture.paperId,
      nonce,
      evidence: restartEvidence,
    })
    host = restarted.host
    const restartedSha = crypto.createHash('sha256').update(restarted.reader.body).digest('hex')
    if (restartedSha !== evidence.route.body_sha256) {
      throw new DshAcceptanceError('dsh_restart_reader_changed')
    }
    evidence.restart = {
      status: restarted.reader.status,
      reader_unchanged: true,
      process: restartEvidence.process,
      startup_attempts: restartEvidence.startup_attempts,
    }
    await stopOwned(host)
    host = null
    evidence.persistent_3080_after = await snapshot3080()
    if (
      JSON.stringify(evidence.persistent_3080_before)
      !== JSON.stringify(evidence.persistent_3080_after)
    ) throw new DshAcceptanceError('persistent_3080_changed')
    evidence.status = 'passed'
    await writeEvidence(root, evidence)
    const keep = process.env.DSH_ACCEPTANCE_KEEP_SUCCESS === '1'
    const summary = {
      ok: true,
      profile: PROFILE,
      port,
      route_status: reader.status,
      invalid_status: evidence.route.invalid_status,
      reader_revision: readerRevision,
      review_toolbar_absent: toolbarAbsent,
      remote_resources_absent: remoteAbsent,
      restart_reader_unchanged: evidence.restart.reader_unchanged,
      cleaned: !keep,
      evidence_root: keep ? root : null,
    }
    if (!keep) {
      assertOwnedTempRoot(root)
      await fs.rm(root, { recursive: true, force: true })
    }
    return summary
  } catch (error) {
    if (host !== null) await stopOwned(host).catch(() => {})
    evidence.status = 'failed'
    evidence.error_code = error instanceof DshAcceptanceError
      ? error.code
      : 'dsh_acceptance_failed'
    evidence.persistent_3080_after = await snapshot3080()
    await writeEvidence(root, evidence).catch(() => {})
    throw new DshAcceptanceError(evidence.error_code, root)
  }
}


const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : ''
if (invokedPath === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 2) {
    process.stderr.write(`${JSON.stringify({
      ok: false,
      error_code: 'acceptance_arguments_invalid',
    })}\n`)
    process.exitCode = 1
  } else {
    runAcceptance().then((summary) => {
      process.stdout.write(`${JSON.stringify(summary)}\n`)
    }).catch((error) => {
      process.stderr.write(`${JSON.stringify({
        ok: false,
        error_code: error instanceof DshAcceptanceError
          ? error.code
          : 'dsh_acceptance_failed',
        evidence_root: error instanceof DshAcceptanceError
          ? error.evidenceRoot
          : null,
      })}\n`)
      process.exitCode = 1
    })
  }
}
