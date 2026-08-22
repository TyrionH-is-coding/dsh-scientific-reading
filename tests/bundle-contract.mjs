import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const packageJson = JSON.parse(
  readFileSync(resolve(rootDir, 'package.json'), 'utf8'),
)

assert.equal(
  packageJson.dsh?.bundle?.patch,
  './cordis.patch.yml',
  'package.json 缺少 dsh.bundle.patch 声明',
)
assert.equal(
  packageJson.exports?.['./cordis.patch.yml'],
  './cordis.patch.yml',
  'package.json 缺少 cordis.patch.yml export',
)
assert.ok(
  packageJson.files?.includes('cordis.patch.yml'),
  'package.json files 未包含 cordis.patch.yml',
)

const patchPath = resolve(rootDir, 'cordis.patch.yml')
assert.ok(existsSync(patchPath), 'cordis.patch.yml 不存在')

function assertPortableBundlePatch(value) {
  const normalized = value.replace(/\r\n?/g, '\n')
  const structureLines = normalized
    .split('\n')
    .filter((line) => line.trim() && !line.trimStart().startsWith('#'))

  assert.deepEqual(
    structureLines,
    [
      '- insert:',
      '    - id: scientific-reading',
      "      name: '@dsh-external/dsh-scientific-reading'",
    ],
    'cordis.patch.yml 必须精确匹配可移植的单项 insert 结构',
  )
}

const patch = readFileSync(patchPath, 'utf8')
assertPortableBundlePatch(patch)

const decoyNamePatch = `- insert:
    - id: scientific-reading
      name: /etc/passwd
- decoy:
    name: '@dsh-external/dsh-scientific-reading'
`
assert.throws(
  () => assertPortableBundlePatch(decoyNamePatch),
  '不得让另一 YAML 分支的伪造 name 掩盖实际 name',
)

function patchWithExtraPath(value) {
  return `- insert:
    - id: scientific-reading
      name: '@dsh-external/dsh-scientific-reading'
      path: ${value}
`
}

assert.throws(
  () => assertPortableBundlePatch(patchWithExtraPath('/etc/passwd')),
  '不得接受 POSIX 根路径',
)
assert.throws(
  () =>
    assertPortableBundlePatch(
      patchWithExtraPath(String.raw`\\server\share\cordis.patch.yml`),
    ),
  '不得接受 UNC 路径',
)
assert.throws(
  () =>
    assertPortableBundlePatch(
      patchWithExtraPath(String.raw`C:\Users\reader\cordis.patch.yml`),
    ),
  '不得接受盘符绝对路径',
)
assert.throws(
  () => assertPortableBundlePatch(patchWithExtraPath('../cordis.patch.yml')),
  '不得接受 ../ 路径',
)
assert.throws(
  () =>
    assertPortableBundlePatch(
      patchWithExtraPath(String.raw`..\cordis.patch.yml`),
    ),
  '不得接受 ..\\ 路径',
)

console.log('PASS: Profile Bundle manifest 与 patch 契约通过')
