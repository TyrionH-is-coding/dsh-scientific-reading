import { createServer } from 'node:http'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, dirname, isAbsolute, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn, spawnSync } from 'node:child_process'

const root = fileURLToPath(new URL('..', import.meta.url))
const COMMAND_TIMEOUT_MS = 60_000
const tail = (value) => String(value ?? '').slice(-2000)

function parseDshBin(args) {
  if (args.length !== 2 || args[0] !== '--dsh-bin' || !isAbsolute(args[1]) || !existsSync(args[1]) || !statSync(args[1]).isFile()) throw new Error('dsh_bin_absolute_existing_file_required')
  if (/\.(cmd|bat)$/i.test(args[1])) throw new Error('dsh_bin_shell_wrapper_not_supported')
  return args[1]
}

function dshCommand(path) { return /\.(?:js|mjs|cjs)$/i.test(path) ? { command: process.execPath, prefix: [path] } : { command: path, prefix: [] } }
function npmCommand() {
  if (process.env.npm_execpath && isAbsolute(process.env.npm_execpath) && existsSync(process.env.npm_execpath)) return { command: process.execPath, prefix: [process.env.npm_execpath] }
  const bundled = join(dirname(process.execPath), 'node_modules', 'npm', 'bin', 'npm-cli.js')
  return process.platform === 'win32' && existsSync(bundled) ? { command: process.execPath, prefix: [bundled] } : { command: 'npm', prefix: [] }
}
function run(label, command, args, env) {
  const result = spawnSync(command, args, { cwd: root, env, encoding: 'utf8', timeout: COMMAND_TIMEOUT_MS, windowsHide: true })
  if (result.error || result.status !== 0) throw new Error(`${label}_failed stdout=${tail(result.stdout)} stderr=${tail(result.stderr || result.error?.message)}`)
  return result.stdout
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
async function jsonRequest(baseUrl, path, options = {}) {
  const response = await fetch(baseUrl + path, { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, signal: AbortSignal.timeout(10_000) })
  const text = await response.text()
  if (response.status !== 200) throw new Error(`runtime_http_failed path=${path} status=${response.status}`)
  return { response, text, json: response.headers.get('content-type')?.includes('json') ? JSON.parse(text) : null }
}
async function assertPortReleased(port) {
  await new Promise((resolveListen, reject) => { const server = createServer(); server.once('error', () => reject(new Error('port_not_released'))); server.listen(port, '127.0.0.1', () => server.close(resolveListen)) })
}
function assertNoLiveWorkers(path) {
  if (!existsSync(path)) return
  const stack = [path]
  while (stack.length) {
    const current = stack.pop()
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const target = join(current, entry.name)
      if (entry.isDirectory()) stack.push(target)
      if (entry.isFile() && /worker\.pid$/i.test(entry.name)) {
        const pid = Number(readFileSync(target, 'utf8').trim())
        if (Number.isInteger(pid) && pid > 0) { try { process.kill(pid, 0); throw new Error('worker_process_leaked') } catch (error) { if (error.message === 'worker_process_leaked') throw error } }
      }
    }
  }
}

async function main() {
  const dshBin = parseDshBin(process.argv.slice(2))
  const temporary = mkdtempSync(join(tmpdir(), 'sr-navigation-runtime-'))
  const dshHome = join(temporary, 'dsh-home'), userProfile = join(temporary, 'user-profile'), dataRoot = join(temporary, 'data'), packDir = join(temporary, 'pack')
  const env = { ...process.env, DSH_HOME: dshHome, USERPROFILE: userProfile, HOME: userProfile, SR_DATA_ROOT: dataRoot, SR_EXTERNAL_PROVIDER: 'fake', DSH_TELEMETRY_DISABLED: '1' }
  delete env.FEISHU_APP_ID; delete env.FEISHU_APP_SECRET
  let child = null, port = null, result = null
  try {
    const dsh = dshCommand(dshBin), npm = npmCommand()
    mkdirSync(packDir)
    const hostVersion = run('dsh_version', dsh.command, [...dsh.prefix, '--version'], env).trim()
    const testedHost = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).dshCompatibility?.testedHost
    if (hostVersion !== testedHost) throw new Error('dsh_version_mismatch')
    run('npm_pack_dry_run', npm.command, [...npm.prefix, 'pack', '--dry-run', '--json', '--ignore-scripts'], env)
    const packed = JSON.parse(run('npm_pack', npm.command, [...npm.prefix, 'pack', '--json', '--ignore-scripts', '--pack-destination', packDir], env))
    const tarball = join(packDir, packed[0]?.filename || '')
    if (!existsSync(tarball)) throw new Error('npm_pack_tarball_required')
    run('dsh_plugin_add', dsh.command, [...dsh.prefix, 'plugin', '--profile', 'scientific-reading-navigation-test', 'add', tarball, '--offline', '--ignore-scripts'], env)
    child = spawn(dsh.command, [...dsh.prefix, '--profile', 'scientific-reading-navigation-test', '--host', '127.0.0.1', '--port', '0'], { cwd: root, env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true })
    const ready = await waitReady(child); port = ready.port
    const ids = []
    for (let index = 1; index <= 60; index += 1) {
      const title = index === 37 ? 'Rare Composite Bridge Search Target' : `Modular Bridge Load Study ${String(index).padStart(2, '0')}`
      const inserted = await jsonRequest(ready.baseUrl, '/sr/api/library', { method: 'POST', body: JSON.stringify({ title, authors: ['Engineer'], year: 2026, doi: `10.5555/bridge.${index}` }) })
      ids.push(inserted.json.paper_id)
    }
    const page1 = await jsonRequest(ready.baseUrl, '/sr/api/library?page=1&page_size=50')
    const page2 = await jsonRequest(ready.baseUrl, '/sr/api/library?page=2&page_size=50')
    if (page1.json.items.length !== 50 || page2.json.items.length !== 10 || page1.json.total !== 60) throw new Error('pagination_contract_failed')
    if ((await jsonRequest(ready.baseUrl, '/sr/api/library?page=1&page_size=50&q=Rare%20Composite')).json.total !== 1) throw new Error('search_contract_failed')
    if ((await jsonRequest(ready.baseUrl, '/sr/api/library?page=1&page_size=50&folder=__unclassified__')).json.total !== 60) throw new Error('unclassified_contract_failed')
    if (!(await jsonRequest(ready.baseUrl, '/sr/api/folders')).json.some((row) => row.folder_id === 'folder_bridge')) throw new Error('folder_contract_failed')
    const first = ids[0]
    await jsonRequest(ready.baseUrl, `/sr/api/paper/${first}`)
    const abstract = await jsonRequest(ready.baseUrl, `/sr/api/paper/${first}/abstract`); if (abstract.json.status !== 'ready') throw new Error('abstract_contract_failed')
    const batch = await jsonRequest(ready.baseUrl, '/sr/api/batch', { method: 'POST', body: JSON.stringify({ action: 'queue_full_read', selection: ids.slice(0, 3), payload: {} }) }); if (!batch.json.batch_id) throw new Error('batch_parent_contract_failed')
    await jsonRequest(ready.baseUrl, `/sr/reader/${first}`)
    await jsonRequest(ready.baseUrl, `/sr/api/paper/${first}/pdf`)
    const assets = await jsonRequest(ready.baseUrl, `/sr/api/paper/${first}/assets`); if (assets.json.figures !== 2 || assets.json.tables !== 1) throw new Error('assets_contract_failed')
    result = { status: 'navigation_runtime_verified', host_version: hostVersion, imported: ids.length, temporary }
  } finally {
    let cleanupError = null
    try {
      await stop(child)
      if (port !== null) await assertPortReleased(port)
      assertNoLiveWorkers(temporary)
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
