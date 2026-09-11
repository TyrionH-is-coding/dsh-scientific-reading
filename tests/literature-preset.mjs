import assert from 'node:assert/strict'
import { mkdtemp, readFile, writeFile, readdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const rootDir = fileURLToPath(new URL('..', import.meta.url))
const packagedPresetYml = await readFile(join(rootDir, 'preset', 'scientific-reading', 'preset.yml'), 'utf8')
const packagedComposition = await readFile(join(rootDir, 'preset', 'scientific-reading', 'agent.cordis.yml'), 'utf8')
const pkg = JSON.parse(await readFile(join(rootDir, 'package.json'), 'utf8'))
const patch = await readFile(join(rootDir, 'cordis.patch.yml'), 'utf8')
const indexSource = await readFile(join(rootDir, 'src', 'index.ts'), 'utf8')

assert.match(packagedPresetYml, /^name:\s*文献模式\s*$/m, 'preset.yml 必须把下拉菜单名称写成文献模式')
assert.match(packagedPresetYml, /入库、浅读、合法取得 PDF/, 'preset.yml 必须有文献工作流说明')
assert.match(packagedComposition, /id:\s*persona/, '文献模式必须自带 persona')
assert.match(packagedComposition, /dsh-tool-str-replace-editor/, '文献模式必须带文件编辑器')
assert.equal(
  /name:\s*['"]@dsh-external\/dsh-scientific-reading['"]/.test(packagedComposition),
  false,
  'preset YAML 不得动态导入本包',
)
assert.match(pkg.files.join('\n'), /^preset$/m, 'package.json files 必须包含 preset 目录')
assert.match(patch, /id: scientific-reading/, 'host patch 仍需插入插件行以便安装预设')
assert.match(indexSource, /mountLiteratureTools/, '宿主 apply 必须把工具挂到文献模式 standing key')
assert.doesNotMatch(indexSource, /registerTools\(ctx,\s*config\)/, '宿主 apply 不得再把 sr_* 工具挂到全局 context')
assert.doesNotMatch(indexSource, /registerLibraryTools\(ctx,\s*config\)/, '宿主 apply 不得再把文献库工具挂到全局 context')

const previousHome = process.env.DSH_HOME
const tempHome = await mkdtemp(join(tmpdir(), 'sr-literature-preset-'))
process.env.DSH_HOME = tempHome

try {
  const {
    DEFAULT_PRESET_ID,
    apply,
    installPreset,
    resolveDshHome,
  } = await import(new URL('../lib/index.js', import.meta.url).href)

  assert.equal(DEFAULT_PRESET_ID, 'scientific-reading')
  assert.equal(resolveDshHome(), tempHome)

  const config = {
    dataRoot: '', python: 'python', scansciExe: 'scansci-pdf', school: '',
    legalOnly: true, outputDir: '', loginType: 'carsi', scansciPython: '', enginePython: '',
    presetId: 'scientific-reading', installPreset: false,
  }

  const hostRegistrations = []
  const hostCtx = {
    on() {},
    effect(fn, label) { hostRegistrations.push(label); try { fn() } catch {} },
    tools: { register(tool) { hostRegistrations.push('tool:' + tool.name) } },
    webServer: { register(route) { hostRegistrations.push(route.kind + ':' + route.path); return () => {} } },
    logger() {},
    get() { return undefined },
  }

  await apply(hostCtx, config)
  const hostTools = hostRegistrations.filter((item) => String(item).startsWith('tool:'))
  assert.equal(hostTools.length, 0, '没有 agentPresets 时，宿主 context 不得注册文献工具')
  assert.ok(hostRegistrations.some((item) => String(item).includes('/sr/api/library')), '文献页路由仍由宿主注册')

  const installed = await installPreset({ logger() {} }, 'scientific-reading')
  assert.equal(installed, true)
  const installedYml = await readFile(join(tempHome, '.agent-presets', 'scientific-reading', 'preset.yml'), 'utf8')
  assert.match(installedYml, /^name:\s*文献模式\s*$/m)

  const presetDir = join(tempHome, '.agent-presets', 'scientific-reading')
  const compositionPath = join(presetDir, 'agent.cordis.yml')
  const customized = packagedComposition.replace('prefix:', 'text:').replace('你是', '用户自定义：你是')
  await writeFile(compositionPath, customized, 'utf8')
  await installPreset({ logger() {} }, 'scientific-reading')
  assert.equal(await readFile(compositionPath, 'utf8'), customized.replace('text:', 'prefix:'))
  const backups = (await readdir(presetDir)).filter(name => name.includes('.before-dsh-0.1.5-'))
  assert.equal(backups.length, 1)
  assert.equal(await readFile(join(presetDir, backups[0]), 'utf8'), customized)
  await installPreset({ logger() {} }, 'scientific-reading')
  assert.equal((await readdir(presetDir)).filter(name => name.includes('.before-dsh-0.1.5-')).length, 1)

  const SCOPE = Symbol('dsh.scope')
  const standingKey = { id: 'scientific-reading-standing' }
  const standingCtx = { [SCOPE]: standingKey }
  const scopedRegistrations = []
  const presetCtx = {
    on() {},
    effect(fn, label) { scopedRegistrations.push(label); try { fn() } catch {} },
    tools: { register(tool) { scopedRegistrations.push('tool:' + tool.name) } },
    webServer: { register(route) { scopedRegistrations.push(route.kind + ':' + route.path); return () => {} } },
    logger() {},
    get(name) { return name === 'agentPresets' ? this.agentPresets : undefined },
    extend(props) { return Object.assign(Object.create(this), props) },
    agentPresets: {
      standingKeyFor: async () => standingKey,
      standing: new Map([['scientific-reading', Promise.resolve({ key: standingKey, scope: { ctx: standingCtx } })]]),
    },
  }

  await apply(presetCtx, config)
  const expectedTools = [
    'sr_setup', 'sr_scansci_status', 'sr_scansci_fetch',
    'sr_download_papers', 'sr_start_full_read', 'sr_continue_full_read', 'sr_attach_pdf', 'sr_export_assets',
    'sr_ingest', 'sr_abstract_submit', 'sr_library_list', 'sr_folder_manage', 'sr_classification_apply',
    'sr_classification_undo', 'sr_job_status', 'sr_paper_context', 'sr_read_job_input', 'sr_research_submit', 'sr_radar',
  ]
  for (const name of expectedTools) {
    assert.ok(scopedRegistrations.includes('tool:' + name), `文献模式必须注册 ${name}`)
  }
} finally {
  if (previousHome === undefined) delete process.env.DSH_HOME
  else process.env.DSH_HOME = previousHome
  await rm(tempHome, { recursive: true, force: true })
}

console.log('PASS: 文献模式仅在选定 preset 时启用，其余模式默认关闭工具')
