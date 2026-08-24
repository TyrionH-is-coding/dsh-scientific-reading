import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const python = process.env.SCIENTIFIC_READING_PYTHON || 'python'
const probe = String.raw`
import ctypes, importlib.util, json, pathlib, types
root = pathlib.Path.cwd()
observed = {"console_window": ctypes.windll.kernel32.GetConsoleWindow() if hasattr(ctypes, "windll") else 0}
for name in ("verify_full_read_pipeline", "verify_restart_recovery"):
    path = root / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.os = types.SimpleNamespace(name="nt")
    module.subprocess.CREATE_NO_WINDOW = 0x08000000
    def capture(*args, _name=name, **kwargs):
        observed[_name] = kwargs
        return None
    module.subprocess.run = capture
    helper = module._run_hidden if name == "verify_full_read_pipeline" else module.run_hidden
    helper(["probe"])
print(json.dumps(observed))
`

const observed = JSON.parse(execFileSync(python, ['-c', probe], {
  cwd: root,
  encoding: 'utf8',
  windowsHide: true,
}))
assert.equal(observed.verify_full_read_pipeline.creationflags, 0x08000000)
assert.equal(observed.verify_restart_recovery.creationflags, 0x08000000)
if (process.platform === 'win32') assert.equal(observed.console_window, 0)

const integration = readFileSync(join(root, 'tests', 'full-read-integration.mjs'), 'utf8')
assert.equal((integration.match(/windowsHide:\s*true/g) || []).length, 2)

for (const script of ['verify_full_read_pipeline.py', 'verify_restart_recovery.py']) {
  const source = readFileSync(join(root, 'scripts', script), 'utf8')
  assert.equal((source.match(/subprocess\.run\(/g) || []).length, 1)
}

console.log('PASS: Task 7 子进程边界在 Windows 隐藏控制台')
