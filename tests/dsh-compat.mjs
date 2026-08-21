import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))

assert.equal(manifest.dshCompatibility?.testedHost, '0.1.0-rc.7')
assert.equal(manifest.dshCompatibility?.node, '22')
assert.equal(manifest.dshCompatibility?.python, '3.11')

const expectedDependencies = {
  '@deepseek-ai/dsh-tools': '0.1.0-rc.7',
  '@deepseek-ai/dsh-llm': '0.1.0-rc.7',
  '@deepseek-ai/dsh-scope': '0.1.0-rc.7',
  '@deepseek-ai/dsh-session': '0.1.0-rc.7',
  '@deepseek-ai/dsh-settings': '0.1.0-rc.7',
  '@deepseek-ai/dsh-timeout': '0.1.0-rc.7',
  '@deepseek-ai/cordis': '4.0.1',
  '@deepseek-ai/schemastery': '3.18.1',
  cordis: 'npm:@deepseek-ai/cordis@4.0.1',
  schemastery: 'npm:@deepseek-ai/schemastery@3.18.1',
  '@types/node': '24.13.3',
  typescript: '5.9.3',
}

for (const [name, version] of Object.entries(expectedDependencies)) {
  assert.equal(manifest.devDependencies?.[name], version, `${name} 必须锁定为 ${version}`)
}

const require = createRequire(import.meta.url)

function readInstalledPackage(name, expectedName) {
  let directory = dirname(require.resolve(name))
  while (directory !== dirname(directory)) {
    const packagePath = join(directory, 'package.json')
    if (existsSync(packagePath)) {
      const installed = JSON.parse(readFileSync(packagePath, 'utf8'))
      if (installed.name === expectedName) return installed
    }
    directory = dirname(directory)
  }
  throw new Error(`找不到已安装包 ${name}`)
}

for (const [name, expectedName, version] of [
  ['@deepseek-ai/dsh-tools', '@deepseek-ai/dsh-tools', '0.1.0-rc.7'],
  ['@deepseek-ai/dsh-llm', '@deepseek-ai/dsh-llm', '0.1.0-rc.7'],
  ['@deepseek-ai/dsh-scope', '@deepseek-ai/dsh-scope', '0.1.0-rc.7'],
  ['@deepseek-ai/dsh-session', '@deepseek-ai/dsh-session', '0.1.0-rc.7'],
  ['@deepseek-ai/dsh-settings', '@deepseek-ai/dsh-settings', '0.1.0-rc.7'],
  ['@deepseek-ai/dsh-timeout', '@deepseek-ai/dsh-timeout', '0.1.0-rc.7'],
  ['@deepseek-ai/cordis', '@deepseek-ai/cordis', '4.0.1'],
  ['@deepseek-ai/schemastery', '@deepseek-ai/schemastery', '3.18.1'],
  ['cordis', '@deepseek-ai/cordis', '4.0.1'],
  ['schemastery', '@deepseek-ai/schemastery', '3.18.1'],
]) {
  assert.equal(readInstalledPackage(name, expectedName).version, version, `${name} 安装版本必须为 ${version}`)
}

console.log('PASS: DSH 兼容契约与安装版本通过')
