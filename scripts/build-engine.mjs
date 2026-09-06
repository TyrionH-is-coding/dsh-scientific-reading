import { cp, copyFile, mkdir, mkdtemp, readdir, rm } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { basename, dirname, join, resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const output = resolve(root, 'dist', 'python')
if (dirname(output) !== resolve(root, 'dist') || basename(output) !== 'python') {
  throw new Error('Python wheel 输出目录越界')
}
await rm(output, { recursive: true, force: true })
await mkdir(output, { recursive: true })

const python = process.env.SCIENTIFIC_READING_PYTHON || process.env.PYTHON
  || (process.platform === 'win32' ? 'python.exe' : 'python3')
const staging = await mkdtemp(join(tmpdir(), 'sr-engine-wheel-'))
const project = join(staging, 'engine')
let result
try {
  await mkdir(join(project, 'src'), { recursive: true })
  await Promise.all([
    copyFile(resolve(root, 'engine', 'pyproject.toml'), join(project, 'pyproject.toml')),
    copyFile(resolve(root, 'engine', 'README.md'), join(project, 'README.md')),
    cp(resolve(root, 'engine', 'src', 'scientific_reading'), join(project, 'src', 'scientific_reading'), {
      recursive: true,
      filter: (path) => basename(path) !== '__pycache__' && !path.endsWith('.pyc') && !path.endsWith('.pyo'),
    }),
    cp(resolve(root, 'engine', 'reader'), join(project, 'reader'), {
      recursive: true,
      filter: (path) => basename(path) !== '__pycache__' && !path.endsWith('.pyc') && !path.endsWith('.pyo'),
    }),
  ])
  result = spawnSync(
    python,
    ['-m', 'pip', 'wheel', project, '--no-cache-dir', '--no-deps', '--wheel-dir', output],
    { cwd: staging, encoding: 'utf8', windowsHide: true, stdio: 'pipe' },
  )
} finally {
  if (dirname(resolve(staging)) !== resolve(tmpdir()) || !basename(staging).startsWith('sr-engine-wheel-')) {
    throw new Error('Python wheel 暂存目录越界')
  }
  await rm(staging, { recursive: true, force: true })
}
if (result.status !== 0) {
  process.stderr.write(result.stderr || result.stdout || 'Python wheel 构建失败\n')
  process.exit(result.status ?? 1)
}
const wheels = (await readdir(output)).filter((name) => name.endsWith('.whl'))
if (wheels.length !== 1) throw new Error('必须且只能生成一个 Python wheel')
console.log('PASS: 已生成内置 Python wheel ' + wheels[0])
