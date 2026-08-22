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

const patch = readFileSync(patchPath, 'utf8').replace(/\r\n?/g, '\n')
assert.equal(
  patch.match(/^\s*-\s+id\s*:/gm)?.length ?? 0,
  1,
  'cordis.patch.yml 必须且只能包含一个 - id:',
)
assert.match(patch, /^\s*-\s+id:\s*scientific-reading\s*$/m)
assert.match(
  patch,
  /^\s*name:\s*['"]@dsh-external\/dsh-scientific-reading['"]\s*$/m,
)
assert.doesNotMatch(patch, /[A-Za-z]:[\\/]/, 'patch 不得包含盘符绝对路径')
assert.doesNotMatch(patch, /\/Users\//, 'patch 不得包含 /Users/ 路径')
assert.doesNotMatch(patch, /\\Users\\/, 'patch 不得包含 \\Users\\ 路径')
assert.ok(
  !patch.includes('../') && !patch.includes('..\\'),
  'patch 不得包含父目录遍历路径',
)

console.log('PASS: Profile Bundle manifest 与 patch 契约通过')
