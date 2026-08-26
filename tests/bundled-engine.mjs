import assert from 'node:assert/strict'
import { execFileSync, spawnSync } from 'node:child_process'
import { mkdtempSync, readdirSync, rmSync } from 'node:fs'
import { delimiter, join } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const wheels = readdirSync(join(root, 'dist', 'python')).filter((name) => name.endsWith('.whl'))
assert.equal(wheels.length, 1, 'dist/python 必须只有一个引擎 wheel')

const fixture = mkdtempSync(join(tmpdir(), 'sr-bundled-engine-'))
const python = process.platform === 'win32'
  ? execFileSync('where.exe', ['python'], { encoding: 'utf8' }).split(/\r?\n/).find((line) => line.trim().toLowerCase().endsWith('.exe')).trim()
  : 'python3'
const target = join(fixture, 'site-packages')

try {
  execFileSync(python, ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps', '--target', target, join(root, 'dist', 'python', wheels[0])], { stdio: 'pipe', windowsHide: true })
  const help = spawnSync(python, ['-m', 'scientific_reading', '--help'], {
    encoding: 'utf8', windowsHide: true,
    env: { ...process.env, PYTHONPATH: process.env.PYTHONPATH ? target + delimiter + process.env.PYTHONPATH : target },
  })
  assert.equal(help.status, 0, help.stderr || help.stdout)
  assert.match(help.stdout, /full-read-pipeline-start/)
  assert.doesNotMatch(help.stdout, /quick-read|parse-fast|zotero/i)
  console.log('PASS: 内置 wheel 可独立安装并启动当前 CLI')
} finally {
  rmSync(fixture, { recursive: true, force: true })
}
