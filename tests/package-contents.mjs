import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))

function listTarballs() {
  return readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith('.tgz'))
    .map((entry) => entry.name)
    .sort()
}

const tarballsBefore = listTarballs()
const packed = spawnSync('npm', ['pack', '--dry-run', '--json', '--ignore-scripts'], {
  cwd: root,
  encoding: 'utf8',
  shell: true,
})
const tarballsAfter = listTarballs()

assert.deepEqual(tarballsAfter, tarballsBefore, 'npm pack --dry-run 不得创建 tarball')
assert.equal(packed.status, 0, packed.stderr || packed.stdout)

const reports = JSON.parse(packed.stdout)
assert.equal(reports.length, 1, 'npm pack --dry-run 必须只返回一个报告')
assert.ok(Array.isArray(reports[0]?.files), 'npm pack 报告缺少 files 清单')

const files = reports[0].files.map((file) => file.path)
const fileSet = new Set(files)
const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))
const requiredFiles = [
  'README.md',
  'package.json',
  'cordis.patch.yml',
  'lib/index.js',
  'lib/client.js',
  'lib/types/index.d.ts',
  'scripts/scansci_wrap.py',
  'LICENSE',
  'THIRD_PARTY_NOTICES.md',
  'MIGRATION.md',
]

const exportPaths = Object.values(pkg.exports).flatMap((entry) => (
  typeof entry === 'string' ? [entry] : [entry.default, entry.types]
))
const manifestPaths = [pkg.main, pkg.types, ...exportPaths]
  .filter((path) => typeof path === 'string' && path.length > 0)
  .map((path) => path.replace(/^\.\//, ''))

const violations = []
for (const file of requiredFiles) {
  if (!fileSet.has(file)) violations.push(`缺少必需文件: ${file}`)
}
for (const file of manifestPaths) {
  if (!fileSet.has(file)) violations.push(`package.json 路径未打包: ${file}`)
}
for (const file of files) {
  if (/^(?:tests|docs|src|client)\//.test(file)) violations.push(`禁止打包目录: ${file}`)
  if (file.startsWith('scripts/') && file !== 'scripts/scansci_wrap.py') {
    violations.push(`禁止打包开发脚本: ${file}`)
  }
  if (/\.(?:pdf|tif|tiff)$/i.test(file)) violations.push(`禁止打包文档或图像: ${file}`)
}
const wheels = files.filter((file) => /^dist\/python\/dsh_scientific_reading_engine-.+\.whl$/.test(file))
if (wheels.length !== 1) violations.push(`内置 Python wheel 数量必须为 1，实际为 ${wheels.length}`)

assert.deepEqual(violations, [], violations.join('\n'))

console.log(`PASS: npm dry-run 包清单通过（${files.length} 个文件）`)
