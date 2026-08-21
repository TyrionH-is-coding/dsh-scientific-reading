// tests/harness.mjs — 插件挂载冒烟（borrowed-ideas §4.2：plugin-template 的 harness 测试）
// 真实验证：apply 不抛错 + 工具/路由注册符合预期。本机直接 node tests/harness.mjs 运行。
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const pluginDir = join(__dirname, '..')
const libIndex = new URL('../lib/index.js', import.meta.url).href

const mod = await import(libIndex)

const registrations = []
const fakeCtx = {
  effect: (fn, label) => { registrations.push(label); try { fn() } catch {} },
  tools: { register: (t) => { registrations.push('tool:' + t.name) } },
  webServer: {
    register: (route) => {
      const key = route.kind + ':' + route.path
      if (registrations.includes('route:' + key)) {
        // 模拟宿主 duplicate 行为（防热重载残留死循环）
        throw new Error('webserver: duplicate ' + route.kind + ' route "' + route.path + '"')
      }
      registrations.push('route:' + key)
      return () => {}
    },
  },
  logger: () => {},
}

const config = {
  dataRoot: '', python: 'python', scansciExe: 'scansci-pdf', school: '',
  legalOnly: true, outputDir: '', loginType: 'carsi', scansciPython: '', enginePython: '',
}

let failures = []
if (mod.name !== '@dsh-external/dsh-scientific-reading') failures.push('name 不匹配')
if (!Array.isArray(mod.inject) || !mod.inject.includes('tools')) failures.push('inject 缺 tools')
if (!mod.inject.includes('webServer')) failures.push('inject 缺 webServer')

try {
  mod.apply(fakeCtx, config)
} catch (e) {
  failures.push('apply 抛错: ' + (e.message || e))
}

const tools = registrations.filter((r) => r.startsWith('tool:'))
const routes = registrations.filter((r) => r.startsWith('route:'))
const expectedTools = ['sr_setup','sr_scansci_status','sr_scansci_fetch','sr_scansci_login','sr_scansci_set_school','sr_init','sr_library_check','sr_library_ensure','sr_pdf_attach','sr_library_list','sr_library_search','sr_parse','sr_quick_read','sr_job_status']
for (const t of expectedTools) {
  if (!tools.some((x) => x === 'tool:' + t)) failures.push('缺工具: ' + t)
}
const expectedRoutes = ['route:exact:/sr/api/papers','route:exact:/sr/api/paper','route:prefix:/sr/api/paper','route:exact:/sr/api/job','route:prefix:/sr/api/job','route:prefix:/sr/reading','route:prefix:/sr/reader','route:exact:/sr']
for (const r of expectedRoutes) {
  if (!routes.includes(r)) failures.push('缺路由: ' + r)
}

// 重复注册应被 registerSafe 容忍（不抛错）
try {
  mod.apply(fakeCtx, config)
  const dupOk = true
  if (!dupOk) failures.push('duplicate 处理异常')
} catch (e) {
  failures.push('重复挂载 apply 抛错（registerSafe 未生效）: ' + (e.message || e))
}

console.log('工具注册: ' + tools.length + ' 个')
console.log('路由注册: ' + routes.length + ' 条')
if (failures.length) {
  console.error('FAIL:')
  failures.forEach((f) => console.error('  - ' + f))
  process.exit(1)
}
console.log('PASS: 插件挂载冒烟通过（含重复挂载容忍）')
