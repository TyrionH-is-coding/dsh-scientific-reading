import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const script = join(root, 'scripts', 'verify_restart_recovery.py')
const source = readFileSync(script, 'utf8')
const cleanupSource = source.slice(source.indexOf('def terminate_test_worker'), source.indexOf('def verify'))
assert.doesNotMatch(cleanupSource, /os\.kill\(pid,\s*0\)/, 'worker 清理不得直接用 os.kill(pid, 0) 探活')

const python = process.env.PYTHON || 'python'
const code = [
  'import importlib.util, json, os, subprocess, sys',
  `path = ${JSON.stringify(script)}`,
  'spec = importlib.util.spec_from_file_location("restart_probe", path)',
  'module = importlib.util.module_from_spec(spec)',
  'spec.loader.exec_module(module)',
  'child = subprocess.Popen([sys.executable, "-c", "pass"])',
  'dead_pid = child.pid',
  'child.wait(timeout=5)',
  'print(json.dumps({"self_alive": module.process_is_alive(os.getpid()), "dead_alive": module.process_is_alive(dead_pid)}))',
].join('; ')
const result = JSON.parse(execFileSync(python, ['-c', code], { encoding: 'utf8' }).trim())
assert.equal(result.self_alive, true)
assert.equal(result.dead_alive, false)
console.log('PASS: restart recovery 使用跨平台只读 PID 探测')
