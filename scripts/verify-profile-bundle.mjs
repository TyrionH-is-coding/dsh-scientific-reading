import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, dirname, isAbsolute, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const root = fileURLToPath(new URL('..', import.meta.url))
const profile = 'scientific-reading-test'
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

function countProfileRows(config) {
  const scalar = (value) => {
    const escaped = value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return `(?:${escaped}|'${escaped}'|"${escaped}")`
  }
  const idLine = new RegExp(`^\\s*-\\s+id:\\s*${scalar(rowId)}\\s*$`)
  const nameLine = new RegExp(`^\\s+name:\\s*${scalar(packageName)}\\s*$`)
  const blocks = []
  for (const line of config.split(/\r?\n/)) {
    if (/^\s*-\s+/.test(line)) blocks.push([])
    if (blocks.length > 0) blocks.at(-1).push(line)
  }
  return blocks.filter((block) =>
    block.some((line) => idLine.test(line)) &&
    block.some((line) => nameLine.test(line)),
  ).length
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
