// tests/harness.mjs — 插件挂载冒烟（borrowed-ideas §4.2：plugin-template 的 harness 测试）
// 真实验证：apply 不抛错 + 工具/路由注册符合预期。本机直接 node tests/harness.mjs 运行。
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const pluginDir = join(__dirname, '..')
const libIndex = new URL('../lib/index.js', import.meta.url).href

delete process.env.FEISHU_APP_ID
delete process.env.FEISHU_APP_SECRET

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
  feishuConfig: '',
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
const expectedTools = ['sr_setup','sr_scansci_status','sr_scansci_fetch','sr_scansci_login','sr_scansci_set_school','sr_start_full_read','sr_continue_full_read','sr_attach_pdf','sr_export_assets','sr_ingest','sr_abstract_submit','sr_library_list','sr_folder_manage','sr_classification_apply','sr_classification_undo','sr_feishu_resync','sr_job_status']
for (const t of expectedTools) {
  if (!tools.some((x) => x === 'tool:' + t)) failures.push('缺工具: ' + t)
}
const expectedRoutes = ['route:exact:/sr/api/library','route:exact:/sr/api/folders','route:exact:/sr/api/batch','route:prefix:/sr/api/abstract','route:prefix:/sr/api/paper','route:exact:/sr/api/job','route:prefix:/sr/api/job','route:prefix:/sr/reader','route:exact:/sr']
for (const r of expectedRoutes) {
  if (!routes.includes(r)) failures.push('缺路由: ' + r)
}
if (tools.length !== expectedTools.length) failures.push(`工具数量不匹配: ${tools.length}`)

const routeSource = readFileSync(join(pluginDir, 'src', 'routes.ts'), 'utf8')
const toolSource = readFileSync(join(pluginDir, 'src', 'library_tools.ts'), 'utf8')
if (routeSource.includes("writeFile(join(root, 'metadata.json')")) failures.push('POST 主库路由不得覆盖 canonical metadata.json')
if (toolSource.includes("writeFile(metaPath, JSON.stringify(metadata")) failures.push('sr_ingest 不得覆盖 canonical metadata.json')

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
