import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, delimiter, dirname, isAbsolute, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn, spawnSync } from 'node:child_process'

const root = fileURLToPath(new URL('..', import.meta.url))
const profile = 'web'
const paperId = 'doi_10.48550_arxiv.1706.03762'
const COMMAND_TIMEOUT_MS = 60_000
const ENGINE_FIXTURE_SCRIPT = `
import hashlib
import json
import os
from pathlib import Path

from scientific_reading.library_service import LibraryService
from scientific_reading.models import PaperMetadata, StageRecord
from scientific_reading.workspace import PaperWorkspace

data_root = Path(os.environ["SR_FIXTURE_DATA_ROOT"])
metadata = PaperMetadata(
    title="Attention Is All You Need",
    authors=["Ashish Vaswani", "Noam Shazeer"],
    doi="10.48550/arxiv.1706.03762",
    year=2017,
    journal="arXiv",
)
library = LibraryService(data_root)
try:
    paper_id = library.ingest(metadata)["paper_id"]
    if paper_id != "doi_10.48550_arxiv.1706.03762":
        raise RuntimeError("fixture_paper_id_mismatch")
    base = PaperWorkspace.create_for_paper_id(data_root, paper_id, metadata)
    pdf_bytes = b"%PDF-1.4\\n% profile runtime fixture\\n%%EOF\\n"
    source_sha = hashlib.sha256(pdf_bytes).hexdigest()
    generation = PaperWorkspace.create_generation(base, source_sha, metadata)
    generation.source_pdf.write_bytes(pdf_bytes)

    active_result = {
        "source_sha256": source_sha,
        "method": "auto",
        "mineru_version": "profile-runtime-fixture",
        "active_parsed_dir": "parsed/mineru",
        "active_workspace": f"generations/{source_sha[:16]}",
    }
    base_state = base.load_job()
    base_state.stages["paper_parse_upgrade"] = StageRecord(status="completed", result=active_result)
    base.save_job(base_state)
    generation_state = generation.load_job()
    generation_state.stages["paper_parse_upgrade"] = StageRecord(
        status="completed",
        result={key: value for key, value in active_result.items() if key != "active_workspace"},
    )
    generation.save_job(generation_state)

    parser_source = generation.parsed_dir / "mineru" / "source_map.json"
    parser_source.parent.mkdir(parents=True, exist_ok=True)
    parser_source.write_text(json.dumps({"contract": "fixture-source-map-v1"}), encoding="utf-8")
    translation_source = generation.reading_dir / "full" / "translations.json"
    translation_source.parent.mkdir(parents=True, exist_ok=True)
    translation_source.write_text(json.dumps({"contract": "fixture-translations-v1"}), encoding="utf-8")
    generation.reader_html.write_text("<!doctype html><p>fixture full reader</p>", encoding="utf-8")
    manifest = {
        "contract": "reader-manifest-v1",
        "paper_id": paper_id,
        "source_pdf_sha256": source_sha,
        "parser_manifest_sha256": hashlib.sha256(parser_source.read_bytes()).hexdigest(),
        "translation_manifest_sha256": hashlib.sha256(translation_source.read_bytes()).hexdigest(),
        "reader_sha256": hashlib.sha256(generation.reader_html.read_bytes()).hexdigest(),
        "generated_at": "2026-08-24T00:00:00+00:00",
        "source_blocks": [{"block_id": "p0001-m0001", "page": 1, "source_type": "text", "source_index": 0}],
        "assets": [],
    }
    reader_manifest = generation.reading_dir / "reader-manifest.json"
    reader_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    (base.reading_dir / "quick_read.md").write_text("# fixture quick read", encoding="utf-8")
    library.record_pdf_attachment(paper_id, source_sha, len(pdf_bytes))
    library.publish_reader(paper_id, f"generations/{source_sha[:16]}/reading/reader.html")
finally:
    library.close()
`

function tail(value) {
  return String(value ?? '').slice(-2000)
}

function run(label, command, args, env) {
  const result = spawnSync(command, args, {
    cwd: root,
    encoding: 'utf8',
    env,
    timeout: COMMAND_TIMEOUT_MS,
    windowsHide: true,
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

function resolveEngineSource() {
  const candidates = [
    process.env.SCIENTIFIC_READING_ENGINE_SRC,
    resolve(root, '..', '..', '..', 'Scientific-Reading-for-Newbies', '.worktrees', 'two-stage-workflow', 'src'),
    resolve(root, '..', '..', '..', 'Scientific-Reading-for-Newbies', 'src'),
    resolve(root, '..', 'Scientific-Reading-for-Newbies', 'src'),
  ]
  for (const candidate of candidates) {
    if (candidate && isAbsolute(candidate) && existsSync(join(candidate, 'scientific_reading', '__main__.py'))) return candidate
  }
  throw new Error('scientific_reading_engine_src_required')
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
  const engineSource = skipEngineFixture ? null : resolveEngineSource()

  const temporary = mkdtempSync(join(tmpdir(), 'sr-profile-runtime-'))
  let child = null
  try {
    const packDir = join(temporary, 'pack')
    const dshHome = join(temporary, 'dsh-home')
    const userProfile = join(temporary, 'user-profile')
    const dataRoot = join(userProfile, 'scientific-reading-data')
    mkdirSync(packDir)

    const env = {
      ...process.env,
      DSH_HOME: dshHome,
      DSH_TELEMETRY_DISABLED: '1',
      USERPROFILE: userProfile,
      HOME: userProfile,
      ...(enginePython ? { SCIENTIFIC_READING_PYTHON: enginePython } : {}),
      ...(engineSource ? {
        PYTHONPATH: process.env.PYTHONPATH ? `${engineSource}${delimiter}${process.env.PYTHONPATH}` : engineSource,
        SR_FIXTURE_DATA_ROOT: dataRoot,
      } : {}),
      PYTHONUTF8: '1',
      PYTHONIOENCODING: 'utf-8',
    }
    delete env.FEISHU_APP_ID
    delete env.FEISHU_APP_SECRET

    if (enginePython) {
      run('engine_generation_reader_fixture', enginePython, ['-c', ENGINE_FIXTURE_SCRIPT], env)
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
