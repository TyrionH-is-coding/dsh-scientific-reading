import { spawnSync } from 'node:child_process'
import { delimiter, resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const python = process.env.SCIENTIFIC_READING_PYTHON || process.env.PYTHON
  || (process.platform === 'win32' ? 'python.exe' : 'python3')
const pythonPath = [resolve(root, 'engine', 'src'), resolve(root, 'engine'), process.env.PYTHONPATH]
  .filter(Boolean).join(delimiter)
const result = spawnSync(python, process.argv.slice(2), {
  cwd: root,
  env: { ...process.env, PYTHONPATH: pythonPath, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
  stdio: 'inherit',
  windowsHide: true,
})
if (result.error) console.error(result.error.message)
process.exit(result.status ?? 1)
