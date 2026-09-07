import { execFileSync } from 'node:child_process'

const candidate = process.env.SCIENTIFIC_READING_PYTHON || process.env.PYTHON
  || (process.platform === 'win32' ? 'python.exe' : 'python3')
export const python = execFileSync(candidate, ['-c', 'import sys; print(sys.executable)'],
  { encoding: 'utf8', windowsHide: true }).trim()
