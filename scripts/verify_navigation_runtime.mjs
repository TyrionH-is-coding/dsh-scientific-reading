import { createServer } from 'node:http'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, delimiter, dirname, isAbsolute, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn, spawnSync } from 'node:child_process'

const root = fileURLToPath(new URL('..', import.meta.url))
const profile = 'web'
const packageName = '@dsh-external/dsh-scientific-reading'
const rowId = 'scientific-reading'
const COMMAND_TIMEOUT_MS = 60_000
const WORKER_TERMINAL_STATES = new Set(['completed', 'failed', 'interrupted', 'waiting_user', 'waiting_agent'])
const tail = (value) => String(value ?? '').slice(-2000)

const ENGINE_FIXTURE_SCRIPT = `
import hashlib
import json
import os
from pathlib import Path

import pymupdf
from PIL import Image

from scientific_reading.classification_service import ClassificationService
from scientific_reading.library_service import LibraryService
from scientific_reading.models import PaperMetadata, StageRecord
from scientific_reading.workspace import PaperWorkspace

data_root = Path(os.environ["SR_NAVIGATION_FIXTURE_ROOT"])
library = LibraryService(data_root)
try:
    paper_ids = []
    for index in range(1, 61):
        title = "Rare Composite Bridge Search Target" if index == 37 else f"Modular Bridge Load Study {index:02d}"
        metadata = PaperMetadata(
            title=title,
            authors=["Runtime Engineer"],
            year=2026,
            journal="Offline Fixture Journal",
            abstract_en="First offline paragraph.\\n\\nSecond offline paragraph.",
            abstract_zh="第一段离线摘要。\\n\\n第二段离线摘要。",
        )
        paper_id = library.ingest(metadata)["paper_id"]
        library.update_abstract_status(paper_id, "ready")
        paper_ids.append(paper_id)

    target = paper_ids[36]
    folder = library.create_folder("Bridge")
    classification = ClassificationService(library)
    classification.apply_direct("move_folder", (target,), {"folder_id": folder["folder_id"]})
    classification.apply_direct("add_tags", (target,), {"tags": ["bridge"]})

    metadata = library.canonical_metadata(target)
    base = PaperWorkspace.create_for_paper_id(data_root, target, metadata)
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Offline navigation runtime fixture")
    pdf_bytes = document.tobytes()
    document.close()
    source_sha = hashlib.sha256(pdf_bytes).hexdigest()
    generation = PaperWorkspace.create_generation(base, source_sha, metadata)
    generation.source_pdf.write_bytes(pdf_bytes)

    active_result = {
        "source_sha256": source_sha,
        "method": "auto",
        "mineru_version": "navigation-runtime-fixture",
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
    generation.reader_html.write_text("<!doctype html><p>navigation fixture reader</p>", encoding="utf-8")
    reader_manifest = {
        "contract": "reader-manifest-v1",
        "paper_id": target,
        "source_pdf_sha256": source_sha,
        "parser_manifest_sha256": hashlib.sha256(parser_source.read_bytes()).hexdigest(),
        "translation_manifest_sha256": hashlib.sha256(translation_source.read_bytes()).hexdigest(),
        "reader_sha256": hashlib.sha256(generation.reader_html.read_bytes()).hexdigest(),
        "generated_at": "2026-08-24T00:00:00+00:00",
        "source_blocks": [{"block_id": "p0001-m0001", "page": 1, "source_type": "text", "source_index": 0}],
        "assets": [],
    }
    (generation.reading_dir / "reader-manifest.json").write_text(json.dumps(reader_manifest), encoding="utf-8")

    exports = generation.exports_dir
    figure_dir = exports / "figures"
    table_dir = exports / "tables"
    figure_dir.mkdir(parents=True, exist_ok=True)
    table_dir.mkdir(parents=True, exist_ok=True)
    figure_paths = [figure_dir / "Fig_01.png", figure_dir / "Fig_02.png"]
    table_png = table_dir / "Table_01.png"
    for index, path in enumerate([*figure_paths, table_png], start=1):
        Image.new("RGB", (2, 2), (240, 240 - index, 235)).save(path, format="PNG")
    table_csv = table_dir / "Table_01.csv"
    table_csv.write_text("metric,value\\nfixture,1\\n", encoding="utf-8")

    def row(asset_id, kind, source_index, export_path, caption):
        path = exports / export_path
        return {
            "asset_id": asset_id,
            "kind": kind,
            "page": 1,
            "source_index": source_index,
            "source_path": "source.pdf",
            "source_sha256": source_sha,
            "export_path": export_path,
            "export_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "caption": caption,
            "warnings": [],
        }

    export_rows = [
        row("figure-runtime-1", "figure", 0, "figures/Fig_01.png", "Fixture figure one"),
        row("figure-runtime-2", "figure", 1, "figures/Fig_02.png", "Fixture figure two"),
        row("table-runtime-1", "table", 2, "tables/Table_01.png", "Fixture table"),
    ]
    export_rows[2].update({
        "csv_path": "tables/Table_01.csv",
        "csv_sha256": hashlib.sha256(table_csv.read_bytes()).hexdigest(),
    })
    (exports / "manifest.json").write_text(json.dumps({
        "contract": "asset-export-v1",
        "paper_id": target,
        "source_pdf_sha256": source_sha,
        "assets": export_rows,
    }), encoding="utf-8")

    library.record_pdf_attachment(target, source_sha, len(pdf_bytes))
    library.publish_reader(target, f"generations/{source_sha[:16]}/reading/reader.html")
finally:
    library.close()
`

function parseArgs(args) {
  const values = new Map()
  for (let index = 0; index < args.length; index += 2) {
    const flag = args[index]
    const value = args[index + 1]
    if (!['--dsh-bin', '--engine-python'].includes(flag) || typeof value !== 'string' || values.has(flag)) throw new Error('navigation_runtime_arguments_invalid')
    values.set(flag, value)
  }
  const dshBin = values.get('--dsh-bin')
  const enginePython = values.get('--engine-python') ?? process.env.SCIENTIFIC_READING_PYTHON
  for (const [label, value] of [['dsh_bin', dshBin], ['engine_python', enginePython]]) {
    if (!value || !isAbsolute(value) || !existsSync(value) || !statSync(value).isFile()) throw new Error(`${label}_absolute_existing_file_required`)
    if (/\.(cmd|bat)$/i.test(value)) throw new Error(`${label}_shell_wrapper_not_supported`)
  }
  return { dshBin, enginePython }
}

function dshCommand(path) { return /\.(?:js|mjs|cjs)$/i.test(path) ? { command: process.execPath, prefix: [path] } : { command: path, prefix: [] } }
function npmCommand() {
  if (process.env.npm_execpath && isAbsolute(process.env.npm_execpath) && existsSync(process.env.npm_execpath)) return { command: process.execPath, prefix: [process.env.npm_execpath] }
  const bundled = join(dirname(process.execPath), 'node_modules', 'npm', 'bin', 'npm-cli.js')
  return process.platform === 'win32' && existsSync(bundled) ? { command: process.execPath, prefix: [bundled] } : { command: 'npm', prefix: [] }
}
function resolveEngineSource() {
  const candidates = [
    process.env.SCIENTIFIC_READING_ENGINE_SRC,
    resolve(root, '..', '..', '..', 'Scientific-Reading-for-Newbies', '.worktrees', 'two-stage-workflow', 'src'),
    resolve(root, '..', '..', '..', 'Scientific-Reading-for-Newbies', 'src'),
    resolve(root, '..', 'Scientific-Reading-for-Newbies', 'src'),
  ]
  for (const candidate of candidates) {
    if (candidate && isAbsolute(candidate) && existsSync(join(candidate, 'scientific_reading', '__main__.py'))) return resolve(candidate)
  }
  throw new Error('scientific_reading_engine_src_required')
}
function run(label, command, args, env) {
  const result = spawnSync(command, args, { cwd: root, env, encoding: 'utf8', timeout: COMMAND_TIMEOUT_MS, windowsHide: true })
  if (result.error || result.status !== 0) throw new Error(`${label}_failed stdout=${tail(result.stdout)} stderr=${tail(result.stderr || result.error?.message)}`)
  return result.stdout
}
function parsePackageRows(label, output) {
  let rows
  try { rows = JSON.parse(output.trim()) } catch { throw new Error(`${label}_json_required`) }
  if (!Array.isArray(rows) || rows.length !== 1) throw new Error(`${label}_single_package_required`)
  return rows
}
function assertDryRunPackage(rows) {
  const files = Array.isArray(rows[0]?.files) ? rows[0].files.map((row) => row?.path) : []
  for (const required of ['package.json', 'lib/index.js', 'lib/client.js']) {
    if (!files.includes(required)) throw new Error(`npm_pack_dry_run_missing_${required.replaceAll('/', '_')}`)
  }
}
function countProfileRows(config) {
  const scalar = (value) => `(?:${value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}|'${value}'|"${value}")`
  const idLine = new RegExp(`^\\s*-\\s+id:\\s*${scalar(rowId)}\\s*$`)
  const nameLine = new RegExp(`^\\s+name:\\s*${scalar(packageName)}\\s*$`)
  const blocks = []
  for (const line of config.split(/\r?\n/)) {
    if (/^\s*-\s+/.test(line)) blocks.push([])
    if (blocks.length) blocks.at(-1).push(line)
  }
  return blocks.filter((block) => block.some((line) => idLine.test(line)) && block.some((line) => nameLine.test(line))).length
}
function waitReady(child) {
  return new Promise((resolveReady, reject) => {
    let stdout = '', stderr = '', settled = false
    const finish = (fn, value) => { if (!settled) { settled = true; clearTimeout(timer); fn(value) } }
    const timer = setTimeout(() => finish(reject, new Error(`dsh_ready_timeout stdout=${tail(stdout)} stderr=${tail(stderr)}`)), 30_000)
    child.stdout.on('data', (chunk) => { stdout += chunk; const match = stdout.match(/http:\/\/127\.0\.0\.1:(\d+)/); if (match) finish(resolveReady, { baseUrl: match[0], port: Number(match[1]) }) })
    child.stderr.on('data', (chunk) => { stderr += chunk })
    child.once('exit', (code) => finish(reject, new Error(`dsh_exited_before_ready exit=${code} stderr=${tail(stderr)}`)))
    child.once('error', (error) => finish(reject, error))
  })
}
async function stop(child) {
  if (!child || child.exitCode !== null) return
  await new Promise((resolveStop) => {
    let settled = false
    const finish = () => { if (!settled) { settled = true; clearTimeout(force); clearTimeout(giveUp); resolveStop() } }
    const force = setTimeout(() => child.kill('SIGKILL'), 3000)
    const giveUp = setTimeout(finish, 5000)
    child.once('exit', finish)
    child.kill('SIGTERM')
  })
  if (child.exitCode === null && child.signalCode === null) throw new Error('dsh_shutdown_failed')
}
async function request(baseUrl, path, options = {}) {
  const response = await fetch(baseUrl + path, { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, signal: AbortSignal.timeout(10_000) })
  const bytes = Buffer.from(await response.arrayBuffer())
  if (response.status !== 200) throw new Error(`runtime_http_failed path=${path} status=${response.status}`)
  const type = response.headers.get('content-type') ?? ''
  return { response, bytes, text: bytes.toString('utf8'), json: type.includes('json') ? JSON.parse(bytes.toString('utf8')) : null }
}
async function assertPortReleased(port) {
  await new Promise((resolveListen, reject) => { const server = createServer(); server.once('error', () => reject(new Error('port_not_released'))); server.listen(port, '127.0.0.1', () => server.close(resolveListen)) })
}
function pidAlive(pid) {
  try { process.kill(pid, 0); return true } catch { return false }
}
function processStartIdentity(pid) {
  if (!Number.isInteger(pid) || pid <= 0 || !pidAlive(pid)) return null
  if (process.platform === 'win32') {
    const command = `$p=Get-Process -Id ${pid} -ErrorAction Stop; 'windows:{0:x16}' -f $p.StartTime.ToUniversalTime().ToFileTimeUtc()`
    const result = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', command], { encoding: 'utf8', timeout: 5000, windowsHide: true })
    return result.status === 0 ? result.stdout.trim() || null : null
  }
  if (process.platform === 'linux') {
    try {
      const stat = readFileSync(`/proc/${pid}/stat`, 'ascii')
      return `linux:${stat.slice(stat.lastIndexOf(')') + 2).split(/\s+/)[19]}`
    } catch { return null }
  }
  return null
}
const delay = (milliseconds) => new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds))
function workerRecords(dataRoot) {
  const jobs = join(dataRoot, 'jobs')
  if (!existsSync(jobs)) return []
  return readdirSync(jobs, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && /^job_[0-9a-f]{16}$/.test(entry.name))
    .map((entry) => {
      const jobRoot = join(jobs, entry.name)
      const readJson = (name) => { try { return JSON.parse(readFileSync(join(jobRoot, name), 'utf8')) } catch { return null } }
      return { jobRoot, status: readJson('status.json'), launch: readJson('launch.json') }
    })
}
async function cleanupWorkers(dataRoot) {
  for (const initial of workerRecords(dataRoot)) {
    const pid = initial.launch?.pid
    if (!Number.isInteger(pid) || pid <= 0 || !pidAlive(pid)) continue
    const deadline = Date.now() + 1500
    let state = initial.status?.state
    while (!WORKER_TERMINAL_STATES.has(state) && pidAlive(pid) && Date.now() < deadline) {
      await delay(50)
      try { state = JSON.parse(readFileSync(join(initial.jobRoot, 'status.json'), 'utf8')).state } catch { state = null }
    }
    if (!pidAlive(pid)) continue
    if (WORKER_TERMINAL_STATES.has(state)) {
      const exitDeadline = Date.now() + 500
      while (pidAlive(pid) && Date.now() < exitDeadline) await delay(50)
      if (!pidAlive(pid)) continue
    }
    const recordedIdentity = initial.launch?.process_start_identity
    const currentIdentity = processStartIdentity(pid)
    if (typeof recordedIdentity !== 'string' || !recordedIdentity || recordedIdentity !== currentIdentity) throw new Error('worker_process_identity_unverified')
    try { process.kill(pid, 'SIGTERM') } catch { /* process already ended */ }
    const stopDeadline = Date.now() + 3000
    while (pidAlive(pid) && Date.now() < stopDeadline) await delay(50)
    if (pidAlive(pid)) { try { process.kill(pid, 'SIGKILL') } catch { /* process already ended */ } }
    if (pidAlive(pid)) throw new Error('worker_process_leaked')
  }
}

async function main() {
  const { dshBin, enginePython } = parseArgs(process.argv.slice(2))
  const fakeEngine = process.env.SR_NAVIGATION_RUNTIME_FAKE_ENGINE === '1'
  const engineSource = fakeEngine ? null : resolveEngineSource()
  const temporary = mkdtempSync(join(tmpdir(), 'sr-navigation-runtime-'))
  const dshHome = join(temporary, 'dsh-home')
  const userProfile = join(temporary, 'user-profile')
  const dataRoot = join(userProfile, 'scientific-reading-data')
  const packDir = join(temporary, 'pack')
  const env = {
    ...process.env,
    DSH_HOME: dshHome,
    USERPROFILE: userProfile,
    HOME: userProfile,
    SCIENTIFIC_READING_PYTHON: enginePython,
    DSH_TELEMETRY_DISABLED: '1',
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
    ...(engineSource ? {
      PYTHONPATH: process.env.PYTHONPATH ? `${engineSource}${delimiter}${process.env.PYTHONPATH}` : engineSource,
      SR_NAVIGATION_FIXTURE_ROOT: dataRoot,
    } : {}),
  }
  delete env.FEISHU_APP_ID
  delete env.FEISHU_APP_SECRET
  let child = null, port = null, result = null
  try {
    const dsh = dshCommand(dshBin), npm = npmCommand()
    mkdirSync(packDir)
    if (!fakeEngine) {
      const imported = resolve(run('engine_import_probe', enginePython, ['-c', 'import scientific_reading; print(scientific_reading.__file__)'], env).trim())
      if (!imported.startsWith(engineSource + sep)) throw new Error('engine_import_source_mismatch')
      run('engine_navigation_fixture', enginePython, ['-c', ENGINE_FIXTURE_SCRIPT], env)
      if (!existsSync(join(dataRoot, 'library.sqlite'))) throw new Error('library_sqlite_required')
    }

    const hostVersion = run('dsh_version', dsh.command, [...dsh.prefix, '--version'], env).trim()
    const testedHost = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).dshCompatibility?.testedHost
    if (hostVersion !== testedHost) throw new Error('dsh_version_mismatch')
    const dryRows = parsePackageRows('npm_pack_dry_run', run('npm_pack_dry_run', npm.command, [...npm.prefix, 'pack', '--dry-run', '--json', '--ignore-scripts'], env))
    assertDryRunPackage(dryRows)
    const packed = parsePackageRows('npm_pack', run('npm_pack', npm.command, [...npm.prefix, 'pack', '--json', '--ignore-scripts', '--pack-destination', packDir], env))
    const tarball = join(packDir, packed[0]?.filename || '')
    if (!existsSync(tarball)) throw new Error('npm_pack_tarball_required')
    run('dsh_plugin_add', dsh.command, [...dsh.prefix, 'plugin', '--profile', profile, 'add', tarball, '--offline', '--ignore-scripts'], env)
    const config = run('dsh_dump_config', dsh.command, [...dsh.prefix, '--profile', profile, '--dump-config'], env)
    if (countProfileRows(config) !== 1) throw new Error('profile_bundle_activation_failed')

    child = spawn(dsh.command, [...dsh.prefix, '--profile', profile, '--host', '127.0.0.1', '--port', '0'], { cwd: root, env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true })
    const ready = await waitReady(child); port = ready.port
    const client = await request(ready.baseUrl, '/plugins/@dsh-external/dsh-scientific-reading/client.js')
    if (!client.text.includes('__ModuleLoader__')) throw new Error('client_tarball_marker_missing')

    const page1 = await request(ready.baseUrl, '/sr/api/library?page=1&page_size=50')
    const page2 = await request(ready.baseUrl, '/sr/api/library?page=2&page_size=50')
    if (page1.json.items.length !== 50 || page2.json.items.length !== 10 || page1.json.total !== 60) throw new Error('pagination_contract_failed')
    const ids = [...page1.json.items, ...page2.json.items].map((item) => item.paper_id)
    const search = await request(ready.baseUrl, '/sr/api/library?page=1&page_size=50&q=Rare%20Composite')
    if (search.json.total !== 1) throw new Error('search_contract_failed')
    const target = search.json.items[0]?.paper_id
    const unclassified = await request(ready.baseUrl, '/sr/api/library?page=1&page_size=50&folder=__unclassified__')
    if (unclassified.json.total !== 59) throw new Error('unclassified_contract_failed')
    const folders = await request(ready.baseUrl, '/sr/api/folders')
    if (!Array.isArray(folders.json)) throw new Error('folders_top_level_array_required')
    const bridge = folders.json.find((row) => row.name === 'Bridge')
    if (!bridge?.folder_id) throw new Error('folder_contract_failed')
    const folderItems = await request(ready.baseUrl, `/sr/api/library?page=1&page_size=50&folder=${encodeURIComponent(bridge.folder_id)}`)
    if (folderItems.json.total !== 1 || folderItems.json.items[0]?.paper_id !== target) throw new Error('classification_contract_failed')

    const detail = await request(ready.baseUrl, `/sr/api/paper/${target}`)
    if (!detail.text.includes('Rare Composite Bridge Search Target')) throw new Error('detail_contract_failed')
    const abstract = await request(ready.baseUrl, `/sr/api/paper/${target}/abstract`)
    if (abstract.json.status !== 'ready' || !abstract.json.abstract_en || !abstract.json.abstract_zh) throw new Error('abstract_contract_failed')

    const batch = await request(ready.baseUrl, '/sr/api/batch', { method: 'POST', body: JSON.stringify({ action: 'add_tags', selection: ids.slice(0, 3), payload: { tags: ['verified-batch'] } }) })
    const parentJobId = batch.json.parent_job_id
    if (!/^job_[0-9a-f]{16}$/.test(parentJobId) || batch.json.status !== 'completed') throw new Error('batch_parent_contract_failed')
    const persistedBatch = JSON.parse(readFileSync(join(dataRoot, 'jobs', 'batches', `${parentJobId}.json`), 'utf8'))
    if (persistedBatch.status !== 'completed' || persistedBatch.children?.length !== 3 || persistedBatch.children.some((row) => row.status !== 'created')) throw new Error('batch_children_readback_failed')

    const reader = await request(ready.baseUrl, `/sr/reader/${target}`)
    if (!reader.text.includes('navigation fixture reader')) throw new Error('reader_bytes_failed')
    const pdf = await request(ready.baseUrl, `/sr/api/paper/${target}/pdf`)
    if (!pdf.bytes.subarray(0, 5).equals(Buffer.from('%PDF-'))) throw new Error('pdf_bytes_failed')
    const assets = await request(ready.baseUrl, `/sr/api/paper/${target}/assets`)
    if (assets.json.figures !== 2 || assets.json.tables !== 1 || !isAbsolute(assets.json.exports_path)) throw new Error('assets_contract_failed')
    const figure = await request(ready.baseUrl, `/sr/api/paper/${target}/assets/figures/Fig_01.png`)
    if (!figure.bytes.subarray(1, 4).equals(Buffer.from('PNG'))) throw new Error('figure_bytes_failed')
    const table = await request(ready.baseUrl, `/sr/api/paper/${target}/assets/tables/Table_01.csv`)
    if (!table.text.includes('fixture,1')) throw new Error('table_bytes_failed')

    result = { status: 'navigation_runtime_verified', host_version: hostVersion, profile, imported: ids.length, temporary }
  } finally {
    let cleanupError = null
    try {
      await stop(child)
      if (port !== null) await assertPortReleased(port)
      await cleanupWorkers(dataRoot)
    } catch (error) { cleanupError = error }
    finally {
      const resolved = resolve(temporary), tmp = resolve(tmpdir())
      if (!resolved.startsWith(tmp + sep) || !basename(resolved).startsWith('sr-navigation-runtime-')) throw new Error('unsafe_temporary_cleanup_target')
      rmSync(resolved, { recursive: true, force: true })
    }
    if (cleanupError) throw cleanupError
  }
  console.log(JSON.stringify(result))
}

try { await main() } catch (error) { console.error(error.message); process.exitCode = 1 }
