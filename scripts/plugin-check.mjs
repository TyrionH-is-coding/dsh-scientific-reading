// scripts/plugin-check.mjs — 插件健康门禁（borrowed-ideas §4.1：dsh-plugin-check 的轻量本地版）
// 检查：构建新鲜度 / 产物纯净 / 仓库边界 / 客户端声明一致性。node scripts/plugin-check.mjs
import { readFile, readdir, stat } from 'node:fs/promises'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { dirname } from 'node:path'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const failures = []

async function walk(dir) {
  const out = []
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === '.git') continue
    const p = join(dir, entry.name)
    if (entry.isDirectory()) out.push(...await walk(p))
    else out.push(p)
  }
  return out
}

// 1) 构建新鲜度：lib/*.js 不得晚于 src/*.ts
let srcNewest = 0
let libOldest = Infinity
for (const f of await walk(join(root, 'src'))) {
  if (f.endsWith('.ts')) { const s = await stat(f); srcNewest = Math.max(srcNewest, s.mtimeMs) }
}
for (const f of await walk(join(root, 'lib'))) {
  if (f.endsWith('.js')) { const s = await stat(f); libOldest = Math.min(libOldest, s.mtimeMs) }
}
if (srcNewest > libOldest) failures.push('构建过期：src 比 lib 新（' + relative(root, join(root, 'lib')) + ' 需重新编译）')

// 2) lib 内不得有 .ts 产物
for (const f of await walk(join(root, 'lib'))) {
  if (f.endsWith('.ts') && !f.endsWith('.d.ts')) failures.push('lib 含 .ts 产物: ' + relative(root, f))
}

// 3) 客户端声明一致性
const pkg = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'))
if (pkg.dsh?.client) {
  if (!pkg.exports?.['./client']) failures.push('dsh.client 声明但 exports 缺 ./client')
  try { await stat(join(root, 'lib', 'client.js')) } catch { failures.push('dsh.client 声明但 lib/client.js 不存在') }
}

// 4) 仓库边界：git 跟踪文件不得含论文资产/密钥/本机用户名路径
try {
  const { execSync } = await import('node:child_process')
  const tracked = execSync('git ls-files -z', { cwd: root }).toString('utf8').split('\0').filter(Boolean)
  const suspicious = ['.pdf', '.tif', '.tiff']
  for (const f of tracked) {
    const lower = f.toLowerCase()
    if (suspicious.some((s) => lower.endsWith(s))) failures.push('论文资产误入仓库: ' + f)
    if (/C:\\Users\\/i.test(f) || /Users\/[A-Za-z0-9_.-]+\//.test(f)) failures.push('带本机用户名的路径: ' + f)
    if (/secret|apikey|token/i.test(lower) && /json|ya?ml$/.test(lower)) failures.push('疑似密钥文件: ' + f)
  }
} catch { /* git 不可用时跳过 */ }

if (failures.length) {
  console.error('插件健康门禁 FAIL:')
  failures.forEach((f) => console.error('  - ' + f))
  process.exit(1)
}
console.log('PASS: 插件健康门禁通过（构建/产物/客户端声明/仓库边界）')
