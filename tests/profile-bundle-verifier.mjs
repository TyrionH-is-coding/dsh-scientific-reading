import assert from 'node:assert/strict'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const root = fileURLToPath(new URL('..', import.meta.url))
const fixture = mkdtempSync(join(tmpdir(), 'sr-profile-fixture-'))
const fakeDsh = join(fixture, 'fake-dsh.mjs')
const fakeShellWrapper = join(fixture, 'fake-dsh.cmd')

writeFileSync(fakeShellWrapper, '@echo off\r\nexit /b 0\r\n', 'utf8')
writeFileSync(fakeDsh, `
import { existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, sep } from 'node:path'

const args = process.argv.slice(2)
if (args.length === 1 && args[0] === '--version') {
  console.log('0.1.0-rc.7')
  process.exit(0)
}

if (args[0] === 'plugin') {
  const expected = ['plugin', '--profile', 'scientific-reading-test', 'add']
  const expectedEnd = ['--offline', '--ignore-scripts']
  if (args.length !== 7 || !expected.every((value, index) => args[index] === value) ||
      !existsSync(args[4]) || !expectedEnd.every((value, index) => args[index + 5] === value) ||
      !process.env.DSH_HOME || !process.env.DSH_HOME.startsWith(resolve(tmpdir()) + sep)) {
    process.exit(8)
  }
  writeFileSync(process.env.FAKE_DSH_CAPTURE, JSON.stringify({
    dshHome: process.env.DSH_HOME,
    secretPresent: Boolean(process.env.FEISHU_APP_ID || process.env.FEISHU_APP_SECRET),
  }))
  process.exit(0)
}

if (args.length === 3 && args[0] === '--profile' && args[1] === 'scientific-reading-test' && args[2] === '--dump-config') {
  const row = "  - id: scientific-reading\\n    name: '@dsh-external/dsh-scientific-reading'"
  if (process.env.FAKE_DSH_MODE === 'success') console.log(row)
  if (process.env.FAKE_DSH_MODE === 'zero') console.log('[]')
  if (process.env.FAKE_DSH_MODE === 'multi') console.log(row + '\\n' + row)
  process.exit(0)
}

process.exit(9)
`, 'utf8')

function run(mode) {
  const capturePath = join(fixture, `capture-${mode}.json`)
  writeFileSync(capturePath, '{}', 'utf8')
  const result = spawnSync(process.execPath, [join(root, 'scripts', 'verify-profile-bundle.mjs'), '--dsh-bin', fakeDsh], {
    cwd: root,
    encoding: 'utf8',
    env: {
      ...process.env,
      FAKE_DSH_MODE: mode,
      FAKE_DSH_CAPTURE: capturePath,
      FEISHU_APP_ID: 'must-not-leak',
      FEISHU_APP_SECRET: 'must-not-leak',
      npm_execpath: '',
    },
  })
  return { result, capture: JSON.parse(readFileSync(capturePath, 'utf8')) }
}

function assertIsolatedCapture(capture) {
  assert.equal(capture.secretPresent, false)
  assert.equal(existsSync(capture.dshHome), false)
}

function runShellWrapper() {
  return spawnSync(process.execPath, [join(root, 'scripts', 'verify-profile-bundle.mjs'), '--dsh-bin', fakeShellWrapper], {
    cwd: root,
    encoding: 'utf8',
  })
}

try {
  const success = run('success')
  assert.equal(success.result.status, 0, success.result.stderr)
  assert.match(success.result.stdout, /profile_bundle_verified/)
  assertIsolatedCapture(success.capture)

  const zero = run('zero')
  assert.notEqual(zero.result.status, 0)
  assert.match(zero.result.stderr, /profile_bundle_row_count_0/)
  assert.doesNotMatch(zero.result.stderr, /must-not-leak/)
  assertIsolatedCapture(zero.capture)

  const multi = run('multi')
  assert.notEqual(multi.result.status, 0)
  assert.match(multi.result.stderr, /profile_bundle_row_count_2/)
  assert.doesNotMatch(multi.result.stderr, /must-not-leak/)
  assertIsolatedCapture(multi.capture)

  const shellWrapper = runShellWrapper()
  assert.notEqual(shellWrapper.status, 0)
  assert.match(shellWrapper.stderr, /dsh_bin_shell_wrapper_not_supported/)

  console.log('PASS: Profile Bundle 隔离激活验证器')
} finally {
  rmSync(fixture, { recursive: true, force: true })
}
