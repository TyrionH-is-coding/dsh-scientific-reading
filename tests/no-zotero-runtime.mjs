import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
for (const relative of ['src/library_tools.ts', 'src/cli.ts', 'client/client.js', 'README.md']) {
  const source = readFileSync(join(root, relative), 'utf8')
  assert.doesNotMatch(source, /sr_zotero_|engineZoteroMigrate|zotero-migrate/, `${relative} 不得保留 Zotero 运行入口`)
}
assert.doesNotMatch(readFileSync(join(root, 'README.md'), 'utf8'), /Zotero/i, 'README 不得再宣传或指导旧运行链路')
const packageJson = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))
assert.doesNotMatch(packageJson.description, /Zotero/i, '插件描述不得再宣称 Zotero 能力')
console.log('PASS: 插件运行入口、UI、说明与测试合同均不再暴露 Zotero')
