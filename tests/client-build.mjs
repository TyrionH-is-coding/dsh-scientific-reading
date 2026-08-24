import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const scriptUrl = new URL('../scripts/build-client.mjs', import.meta.url)
const pluginCheckUrl = new URL('../scripts/plugin-check.mjs', import.meta.url)
const pluginCheck = readFileSync(fileURLToPath(pluginCheckUrl), 'utf8')
const check = spawnSync(process.execPath, [fileURLToPath(scriptUrl), '--check'], {
  encoding: 'utf8',
})
assert.equal(check.status, 0, check.stderr || check.stdout)

function createPluginFixture() {
  const root = mkdtempSync(join(tmpdir(), 'dsh-plugin-check-'))
  const scripts = join(root, 'scripts')
  mkdirSync(join(root, 'src'))
  mkdirSync(join(root, 'client'))
  mkdirSync(join(root, 'lib'))
  mkdirSync(scripts)
  writeFileSync(join(root, 'package.json'), JSON.stringify({
    dsh: { client: 'lib/client.js' },
    exports: { './client': './lib/client.js' },
  }), 'utf8')
  writeFileSync(join(root, 'client', 'client.js'), 'module.exports = {}\n', 'utf8')
  writeFileSync(join(root, 'lib', 'client.js'), 'module.exports = {}\n', 'utf8')
  writeFileSync(join(scripts, 'build-client.mjs'), readFileSync(fileURLToPath(scriptUrl), 'utf8'), 'utf8')
  writeFileSync(join(scripts, 'plugin-check.mjs'), pluginCheck, 'utf8')
  return root
}

function runPluginCheck(root) {
  return spawnSync(process.execPath, [join(root, 'scripts', 'plugin-check.mjs')], { encoding: 'utf8' })
}

const pluginFixture = createPluginFixture()
try {
  const fresh = runPluginCheck(pluginFixture)
  assert.equal(fresh.status, 0, fresh.stderr || fresh.stdout)

  writeFileSync(join(pluginFixture, 'lib', 'client.js'), 'stale\n', 'utf8')
  const stale = runPluginCheck(pluginFixture)
  assert.equal(stale.status, 1, stale.stderr || stale.stdout)
  assert.match(stale.stderr, /构建产物缺失或过期/, '过期产物应被 plugin-check 拒绝')

  rmSync(join(pluginFixture, 'lib', 'client.js'))
  const missing = runPluginCheck(pluginFixture)
  assert.equal(missing.status, 1, missing.stderr || missing.stdout)
  assert.match(missing.stderr, /缺失/, '缺失产物应被 plugin-check 拒绝')

  writeFileSync(join(pluginFixture, 'scripts', 'build-client.mjs'), 'export function checkClient() { throw null }\n', 'utf8')
  const brokenCheck = runPluginCheck(pluginFixture)
  assert.equal(brokenCheck.status, 1, brokenCheck.stderr || brokenCheck.stdout)
  assert.match(brokenCheck.stderr, /构建新鲜度检查失败: null/, '异常应输出受控的新鲜度检查错误')
} finally {
  rmSync(pluginFixture, { recursive: true, force: true })
}

const { buildClient, checkClient, normalizeClientSource } = await import(scriptUrl.href)
const directory = mkdtempSync(join(tmpdir(), 'dsh-client-build-'))
const sourcePath = join(directory, 'client.js')
const outputPath = join(directory, 'generated-client.js')

try {
  const source = 'first\r\nsecond\rthird\n'
  const normalized = 'first\nsecond\nthird\n'
  writeFileSync(sourcePath, source, 'utf8')

  assert.equal(normalizeClientSource(source), normalized, 'CRLF 与 CR 应规范为 LF')
  assert.equal(checkClient({ sourcePath, outputPath }), false, '缺失产物应被识别为过期')
  buildClient({ sourcePath, outputPath })
  assert.equal(readFileSync(outputPath, 'utf8'), normalized, '首次构建应写入规范化内容')
  assert.equal(checkClient({ sourcePath, outputPath }), true, '首次构建后应保持最新')

  writeFileSync(outputPath, normalized.replace(/\n/g, '\r\n'), 'utf8')
  assert.equal(checkClient({ sourcePath, outputPath }), true, 'Windows checkout 的 CRLF 不应误报产物过期')

  writeFileSync(outputPath, 'stale\n', 'utf8')
  assert.equal(checkClient({ sourcePath, outputPath }), false, '篡改产物应被识别为过期')

  buildClient({ sourcePath, outputPath })
  assert.equal(checkClient({ sourcePath, outputPath }), true, '重建后应恢复最新')
} finally {
  rmSync(directory, { recursive: true, force: true })
}

console.log('PASS: 客户端构建器通过')
