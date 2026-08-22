import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, isAbsolute, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const root = fileURLToPath(new URL('..', import.meta.url))
const profile = 'sr-scientific-reading-verify'
const rowId = 'scientific-reading'
const packageName = '@dsh-external/dsh-scientific-reading'

function tail(value) {
  return String(value ?? '').slice(-2000)
}

function run(label, command, args, env) {
  const result = spawnSync(command, args, {
    cwd: root,
    encoding: 'utf8',
    env,
    shell: process.platform === 'win32' && /\.(cmd|bat)$/i.test(command),
  })
  if (result.error) throw new Error(`${label}_failed`)
  if (result.status !== 0) {
    throw new Error(`${label}_failed exit=${result.status} stdout=${tail(result.stdout)} stderr=${tail(result.stderr)}`)
  }
  return result.stdout
}

function parseDshBin(args) {
  if (args.length !== 2 || args[0] !== '--dsh-bin' || !isAbsolute(args[1]) || !existsSync(args[1]) || !statSync(args[1]).isFile()) {
    throw new Error('dsh_bin_absolute_existing_file_required')
  }
  return args[1]
}

function countProfileRows(config) {
  const blocks = []
  for (const line of config.split(/\r?\n/)) {
    if (/^\s*-\s+/.test(line)) blocks.push([])
    if (blocks.length > 0) blocks.at(-1).push(line)
  }
  return blocks.filter((block) =>
    block.some((line) => /^\s*-\s+id:\s*scientific-reading\s*$/.test(line)) &&
    block.some((line) => /^\s+name:\s*@dsh-external\/dsh-scientific-reading\s*$/.test(line)),
  ).length
}

function resolveNpm() {
  const npmExecPath = process.env.npm_execpath
  if (npmExecPath && isAbsolute(npmExecPath) && existsSync(npmExecPath)) {
    return { command: process.execPath, prefix: [npmExecPath] }
  }
  return { command: process.platform === 'win32' ? 'npm.cmd' : 'npm', prefix: [] }
}

function main() {
  const dshBin = parseDshBin(process.argv.slice(2))
  const manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))
  const testedHost = manifest.dshCompatibility?.testedHost
  if (typeof testedHost !== 'string') throw new Error('tested_host_required')

  const temporary = mkdtempSync(join(tmpdir(), 'sr-profile-bundle-'))
  try {
    const packDir = join(temporary, 'pack')
    const dshHome = join(temporary, 'dsh-home')
    mkdirSync(packDir)
    const env = { ...process.env, DSH_HOME: dshHome, DSH_TELEMETRY_DISABLED: '1' }
    delete env.FEISHU_APP_ID
    delete env.FEISHU_APP_SECRET
    const dsh = /\.(?:js|mjs|cjs)$/i.test(dshBin)
      ? { command: process.execPath, prefix: [dshBin] }
      : { command: dshBin, prefix: [] }

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
    const config = run('dsh_dump_config', dsh.command, [...dsh.prefix, '--profile', profile, '--dump-config'], env)
    const rowCount = countProfileRows(config)
    if (rowCount !== 1) throw new Error(`profile_bundle_row_count_${rowCount}`)
    console.log(JSON.stringify({ status: 'profile_bundle_verified', host_version: hostVersion, profile, row_id: rowId }))
  } finally {
    const temporaryResolved = resolve(temporary)
    const tmpResolved = resolve(tmpdir())
    if (!temporaryResolved.startsWith(`${tmpResolved}${sep}`) || !basename(temporaryResolved).startsWith('sr-profile-bundle-')) {
      throw new Error('unsafe_temporary_cleanup_target')
    }
    rmSync(temporaryResolved, { recursive: true, force: true })
  }
}

try {
  main()
} catch (error) {
  console.error(error.message)
  process.exitCode = 1
}
