import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const scriptUrl = new URL('../scripts/build-client.mjs', import.meta.url)
const pluginCheckUrl = new URL('../scripts/plugin-check.mjs', import.meta.url)
const pluginCheck = readFileSync(fileURLToPath(pluginCheckUrl), 'utf8')
assert.match(pluginCheck, /checkClient/, '插件健康门禁应接入客户端构建新鲜度检查')
const check = spawnSync(process.execPath, [fileURLToPath(scriptUrl), '--check'], {
  encoding: 'utf8',
})
assert.equal(check.status, 0, check.stderr || check.stdout)

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

  writeFileSync(outputPath, 'stale\n', 'utf8')
  assert.equal(checkClient({ sourcePath, outputPath }), false, '篡改产物应被识别为过期')

  buildClient({ sourcePath, outputPath })
  assert.equal(checkClient({ sourcePath, outputPath }), true, '重建后应恢复最新')
} finally {
  rmSync(directory, { recursive: true, force: true })
}

console.log('PASS: 客户端构建器通过')
