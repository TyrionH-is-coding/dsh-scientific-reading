import assert from 'node:assert/strict'
import { execFileSync, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { basename, delimiter, dirname, join, relative, resolve } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const fixture = mkdtempSync(join(tmpdir(), 'sr-bundled-engine-'))
const python = process.env.SCIENTIFIC_READING_PYTHON || process.env.PYTHON
  || (process.platform === 'win32' ? 'python.exe' : 'python3')
const target = join(fixture, 'site-packages')
const stale = join(root, 'engine', 'build', 'lib', 'scientific_reading', '_stale_build_fixture.py')
let staleCreated = false

function pythonFiles(directory, base = directory) {
  const result = new Map()
  for (const name of readdirSync(directory)) {
    const path = join(directory, name)
    if (statSync(path).isDirectory()) {
      if (name !== '__pycache__') {
        for (const [child, bytes] of pythonFiles(path, base)) result.set(child, bytes)
      }
    } else if (name.endsWith('.py')) {
      result.set(relative(base, path).replaceAll('\\', '/'), readFileSync(path))
    }
  }
  return result
}

try {
  assert.equal(existsSync(stale), false, '测试哨兵文件不得预先存在')
  mkdirSync(join(root, 'engine', 'build', 'lib', 'scientific_reading'), { recursive: true })
  writeFileSync(stale, 'raise RuntimeError("stale build file must not ship")\n', { flag: 'wx' })
  staleCreated = true
  const build = spawnSync(process.execPath, [join(root, 'scripts', 'build-engine.mjs')], {
    cwd: root, encoding: 'utf8', windowsHide: true,
    env: { ...process.env, SCIENTIFIC_READING_PYTHON: python },
  })
  assert.equal(build.status, 0, build.stderr || build.stdout)
  const wheels = readdirSync(join(root, 'dist', 'python')).filter((name) => name.endsWith('.whl'))
  assert.equal(wheels.length, 1, 'dist/python 必须只有一个引擎 wheel')
  execFileSync(python, ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps', '--target', target, join(root, 'dist', 'python', wheels[0])], { stdio: 'pipe', windowsHide: true })
  const expected = new Map([
    ...[...pythonFiles(join(root, 'engine', 'src', 'scientific_reading'))].map(([name, bytes]) => [`scientific_reading/${name}`, bytes]),
    ...[...pythonFiles(join(root, 'engine', 'reader'))].map(([name, bytes]) => [`reader/${name}`, bytes]),
  ])
  const installed = new Map([
    ...[...pythonFiles(join(target, 'scientific_reading'))].map(([name, bytes]) => [`scientific_reading/${name}`, bytes]),
    ...[...pythonFiles(join(target, 'reader'))].map(([name, bytes]) => [`reader/${name}`, bytes]),
  ])
  assert.deepEqual([...installed.keys()].sort(), [...expected.keys()].sort(), 'wheel Python 文件集合必须与当前源码完全一致')
  for (const [name, bytes] of expected) {
    assert.deepEqual(installed.get(name), bytes, `wheel 文件字节必须匹配源码：${name}`)
  }
  const help = spawnSync(python, ['-m', 'scientific_reading', '--help'], {
    encoding: 'utf8', windowsHide: true,
    env: { ...process.env, PYTHONPATH: process.env.PYTHONPATH ? target + delimiter + process.env.PYTHONPATH : target },
  })
  assert.equal(help.status, 0, help.stderr || help.stdout)
  assert.match(help.stdout, /full-read-pipeline-start/)
  assert.doesNotMatch(help.stdout, /quick-read|parse-fast|zotero/i)
  console.log('PASS: 内置 wheel 可独立安装并启动当前 CLI')
} finally {
  if (staleCreated) rmSync(stale, { force: true })
  assert.equal(dirname(resolve(fixture)), resolve(tmpdir()))
  assert.ok(basename(fixture).startsWith('sr-bundled-engine-'))
  rmSync(fixture, { recursive: true, force: true })
}
