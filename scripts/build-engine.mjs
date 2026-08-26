import { mkdir, readdir, rm } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const output = resolve(root, 'dist', 'python')
await rm(output, { recursive: true, force: true })
await mkdir(output, { recursive: true })

const python = process.env.PYTHON || (process.platform === 'win32' ? 'python.exe' : 'python3')
const result = spawnSync(
  python,
  ['-m', 'pip', 'wheel', resolve(root, 'engine'), '--no-deps', '--wheel-dir', output],
  { cwd: root, encoding: 'utf8', windowsHide: true, stdio: 'pipe' },
)
if (result.status !== 0) {
  process.stderr.write(result.stderr || result.stdout || 'Python wheel 构建失败\n')
  process.exit(result.status ?? 1)
}
const wheels = (await readdir(output)).filter((name) => name.endsWith('.whl'))
if (wheels.length !== 1) throw new Error('必须且只能生成一个 Python wheel')
console.log('PASS: 已生成内置 Python wheel ' + wheels[0])
