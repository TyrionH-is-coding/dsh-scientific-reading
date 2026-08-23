import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, dirname, isAbsolute, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn, spawnSync } from 'node:child_process'

const root = fileURLToPath(new URL('..', import.meta.url))
const profile = 'web'
const paperId = 'doi_10.48550_arxiv.1706.03762'
const COMMAND_TIMEOUT_MS = 60_000

function tail(value) {
  return String(value ?? '').slice(-2000)
}

function run(label, command, args, env) {
  const result = spawnSync(command, args, {
    cwd: root,
    encoding: 'utf8',
    env,
    timeout: COMMAND_TIMEOUT_MS,
  })
  if (result.error) throw new Error(`${label}_failed error=${tail(result.error.message)}`)
  if (result.status !== 0) {
    throw new Error(`${label}_failed exit=${result.status} stdout=${tail(result.stdout)} stderr=${tail(result.stderr)}`)
  }
  return result.stdout
}

function parseDshBin(args) {
  if (args.length !== 2 || args[0] !== '--dsh-bin' || !isAbsolute(args[1]) || !existsSync(args[1]) || !statSync(args[1]).isFile()) {
    throw new Error('dsh_bin_absolute_existing_file_required')
  }
  if (/\.(cmd|bat)$/i.test(args[1])) throw new Error('dsh_bin_shell_wrapper_not_supported')
  return args[1]
}

function resolveNpm() {
  const npmExecPath = process.env.npm_execpath
  if (npmExecPath && isAbsolute(npmExecPath) && existsSync(npmExecPath)) {
    return { command: process.execPath, prefix: [npmExecPath] }
  }
  const bundledNpm = join(dirname(process.execPath), 'node_modules', 'npm', 'bin', 'npm-cli.js')
  if (process.platform === 'win32' && existsSync(bundledNpm)) {
    return { command: process.execPath, prefix: [bundledNpm] }
  }
  return { command: 'npm', prefix: [] }
}

function dshCommand(dshBin) {
  return /\.(?:js|mjs|cjs)$/i.test(dshBin)
    ? { command: process.execPath, prefix: [dshBin] }
    : { command: dshBin, prefix: [] }
}

function resolveEnginePython() {
  const candidates = process.platform === 'win32'
    ? [
        process.env.SCIENTIFIC_READING_PYTHON,
        process.env.USERPROFILE ? join(process.env.USERPROFILE, 'scientific-reading-data', '.venv', 'Scripts', 'python.exe') : '',
      ]
    : [
        process.env.SCIENTIFIC_READING_PYTHON,
        process.env.HOME ? join(process.env.HOME, 'scientific-reading-data', '.venv', 'bin', 'python') : '',
      ]
  for (const candidate of candidates) {
    if (candidate && isAbsolute(candidate) && existsSync(candidate) && statSync(candidate).isFile()) return candidate
  }
  throw new Error('scientific_reading_python_required')
}

function waitForReady(child) {
  return new Promise((resolveReady, rejectReady) => {
    let stdout = ''
    let stderr = ''
    let settled = false
    const timer = setTimeout(() => {
      if (settled) return
      settled = true
      rejectReady(new Error(`dsh_ready_timeout stdout=${tail(stdout)} stderr=${tail(stderr)}`))
    }, 30_000)

    const finish = (fn, value) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      fn(value)
    }

    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString('utf8')
      const match = stdout.match(/https?:\/\/127\.0\.0\.1:\d+/)
      if (match) finish(resolveReady, match[0])
    })
    child.stderr.on('data', (chunk) => { stderr += chunk.toString('utf8') })
    child.once('error', (error) => finish(rejectReady, new Error(`dsh_start_failed error=${tail(error.message)}`)))
    child.once('exit', (code, signal) => {
      finish(rejectReady, new Error(`dsh_exited_before_ready exit=${code} signal=${signal ?? ''} stdout=${tail(stdout)} stderr=${tail(stderr)}`))
    })
  })
}

async function stopChild(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return
  await new Promise((resolveStop) => {
    let done = false
    const finish = () => {
      if (done) return
      done = true
      clearTimeout(forceTimer)
      clearTimeout(giveUpTimer)
      resolveStop()
    }
    const forceTimer = setTimeout(() => {
      if (child.exitCode === null) child.kill('SIGKILL')
    }, 3_000)
    const giveUpTimer = setTimeout(finish, 5_000)
    child.once('exit', finish)
    child.kill('SIGTERM')
  })
  if (child.exitCode === null && child.signalCode === null) throw new Error('dsh_shutdown_failed')
}

async function assertPage(baseUrl, path, marker) {
  const response = await fetch(baseUrl + path, { signal: AbortSignal.timeout(10_000) })
  const body = await response.text()
  if (response.status !== 200) throw new Error(`runtime_http_${path}_status_${response.status}`)
  if (marker && !body.includes(marker)) throw new Error(`runtime_http_${path}_marker_missing`)
}

async function main() {
  const dshBin = parseDshBin(process.argv.slice(2))
  const manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))
  const testedHost = manifest.dshCompatibility?.testedHost
  if (typeof testedHost !== 'string') throw new Error('tested_host_required')
  const skipEngineFixture = process.env.SR_PROFILE_RUNTIME_FAKE_ENGINE === '1'
  const enginePython = skipEngineFixture ? null : resolveEnginePython()

  const temporary = mkdtempSync(join(tmpdir(), 'sr-profile-runtime-'))
  let child = null
  try {
    const packDir = join(temporary, 'pack')
    const dshHome = join(temporary, 'dsh-home')
    const userProfile = join(temporary, 'user-profile')
    const dataRoot = join(userProfile, 'scientific-reading-data')
    const paperRoot = join(dataRoot, 'papers', paperId)
    const readingDir = join(paperRoot, 'reading')
    const fullOutputDir = join(readingDir, 'full', 'output')
    mkdirSync(packDir)
    mkdirSync(fullOutputDir, { recursive: true })
    const metadataPath = join(paperRoot, 'metadata.json')
    writeFileSync(metadataPath, JSON.stringify({
      title: 'Attention Is All You Need',
      authors: ['Ashish Vaswani', 'Noam Shazeer'],
      doi: '10.48550/arxiv.1706.03762',
      pmid: null,
      year: 2017,
      journal: 'arXiv',
      zotero_key: null,
    }, null, 2), 'utf8')
    writeFileSync(join(readingDir, 'quick_read.md'), '# fixture quick read', 'utf8')
    writeFileSync(join(fullOutputDir, 'reader_full.html'), '<!doctype html><p>fixture full reader</p>', 'utf8')

    const env = {
      ...process.env,
      DSH_HOME: dshHome,
      DSH_TELEMETRY_DISABLED: '1',
      USERPROFILE: userProfile,
      HOME: userProfile,
      ...(enginePython ? { SCIENTIFIC_READING_PYTHON: enginePython } : {}),
      PYTHONUTF8: '1',
      PYTHONIOENCODING: 'utf-8',
    }
    delete env.FEISHU_APP_ID
    delete env.FEISHU_APP_SECRET

    if (enginePython) {
      run('engine_library_ensure', enginePython, [
        '-m', 'scientific_reading', '--data-root', dataRoot,
        'library-ensure', '--metadata', metadataPath,
      ], env)
    }

    const dsh = dshCommand(dshBin)
    const hostVersion = run('dsh_version', dsh.command, [...dsh.prefix, '--version'], env).trim()
    if (hostVersion !== testedHost) throw new Error('dsh_version_mismatch')

    const npm = resolveNpm()
    const packed = run('npm_pack', npm.command, [
      ...npm.prefix,
      'pack', '--json', '--ignore-scripts', '--pack-destination', packDir,
    ], env).trim()
    let packageRows
    try {
      packageRows = JSON.parse(packed)
    } catch {
      throw new Error('npm_pack_json_required')
    }
    if (!Array.isArray(packageRows) || packageRows.length !== 1 || typeof packageRows[0]?.filename !== 'string') {
      throw new Error('npm_pack_json_required')
    }
    const tarball = join(packDir, packageRows[0].filename)
    if (!existsSync(tarball)) throw new Error('npm_pack_tarball_required')

    run('dsh_plugin_add', dsh.command, [
      ...dsh.prefix, 'plugin', '--profile', profile, 'add', tarball, '--offline', '--ignore-scripts',
    ], env)

    child = spawn(dsh.command, [
      ...dsh.prefix, '--profile', profile, '--host', '127.0.0.1', '--port', '0',
    ], {
      cwd: root,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    })
    const baseUrl = await waitForReady(child)
    await assertPage(baseUrl, '/', '')
    await assertPage(baseUrl, '/plugins/@dsh-external/dsh-scientific-reading/client.js', '__ModuleLoader__')
    await assertPage(baseUrl, '/sr/api/papers', paperId)
    await assertPage(baseUrl, `/sr/api/paper/${paperId}`, 'Attention Is All You Need')
    await assertPage(baseUrl, `/sr/reading/${paperId}`, 'fixture quick read')
    await assertPage(baseUrl, `/sr/reader/${paperId}`, 'fixture full reader')

    console.log(JSON.stringify({ status: 'profile_runtime_verified', host_version: hostVersion, profile }))
  } finally {
    await stopChild(child)
    const temporaryResolved = resolve(temporary)
    const tmpResolved = resolve(tmpdir())
    if (!temporaryResolved.startsWith(`${tmpResolved}${sep}`) || !basename(temporaryResolved).startsWith('sr-profile-runtime-')) {
      throw new Error('unsafe_temporary_cleanup_target')
    }
    rmSync(temporaryResolved, { recursive: true, force: true })
  }
}

try {
  await main()
} catch (error) {
  console.error(error.message)
  process.exitCode = 1
}
