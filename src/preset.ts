/**
 * 文献模式 preset：安装到 `$DSH_HOME/.agent-presets/`，并把 sr_* 工具挂到该预设的 standing scope。
 * 对照 omdsh-dev/dsh-data-agent 的「数据模式」做法，避免在 preset YAML 里动态导入本包。
 */
import { access, cp, mkdir, readFile, writeFile, rename } from 'node:fs/promises'
import { homedir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Context } from 'cordis'
import type { Config as PluginConfig } from './config.js'
import { registerLibraryTools } from './library_tools.js'
import { registerReviewTools } from './review_tools.js'
import { registerTools } from './tools.js'
import { registerPaperTools } from './paper_sessions.js'
import { registerRadarTools } from './radar.js'
import { registerModelPolicyTools } from './model_policy.js'

export const DEFAULT_PRESET_ID = 'scientific-reading'
export const PRESET_DISPLAY_NAME = '文献模式'

export interface AgentPresetsLike {
  standingKeyFor(id: string): Promise<unknown>
  standing?: Map<string, Promise<StandingScopeRecord>>
}

export interface StandingScopeRecord {
  key: unknown
  scope: { ctx: object }
}

export interface PresetHostContext extends Context {
  agentPresets?: AgentPresetsLike
}

/** 只通过 get() 读服务，避免未 inject 时 ctx.agentPresets 直接把整个 DSH 拉倒。 */
function readAgentPresets(ctx: PresetHostContext): AgentPresetsLike | undefined {
  try {
    const found = ctx.get('agentPresets') as AgentPresetsLike | undefined
    if (found && typeof found.standingKeyFor === 'function') return found
  } catch {
    // cordis：未 inject 时 get/proxy 都会抛
  }
  return undefined
}

/**
 * 与 `@deepseek-ai/dsh-paths` 一致：非空 `$DSH_HOME`，否则 `~/.dsh`。
 */
export function resolveDshHome(env: Record<string, string | undefined> = process.env): string {
  const fromEnv = env.DSH_HOME
  const selected = fromEnv !== undefined && fromEnv.trim().length > 0 ? fromEnv : join(homedir(), '.dsh')
  return resolve(selected.startsWith('~/') ? join(homedir(), selected.slice(2)) : selected)
}

export function packagedPresetDir(): string {
  return fileURLToPath(new URL('../preset/scientific-reading/', import.meta.url))
}

export function resolvePresetId(config: Pick<PluginConfig, 'presetId'>): string {
  const id = config.presetId?.trim()
  return id || DEFAULT_PRESET_ID
}

/**
 * 把打包的 `preset/scientific-reading/` 安装到 `$DSH_HOME/.agent-presets/<id>/`。
 * 已存在的目录保留用户配置；仅迁移 DSH 0.1.5 的 persona 字段名，并保存旧文件。
 */
export async function installPreset(ctx: Context, presetId: string): Promise<boolean> {
  const targetDir = join(resolveDshHome(), '.agent-presets', presetId)
  const sourceDir = packagedPresetDir()
  const exists = await access(targetDir).then(() => true, error => { if (error.code === 'ENOENT') return false; throw error })
  if (exists) {
    const composition = join(targetDir, 'agent.cordis.yml')
    const before = await readFile(composition, 'utf8')
    const after = before.replace(/(^- id: persona\r?\n[ \t]+name: ['"]?@deepseek-ai\/dsh-persona['"]?\r?\n[ \t]+config:\r?\n)([ \t]+)text:/m, '$1$2prefix:')
    if (after !== before) {
      await writeFile(composition + '.before-dsh-0.1.5-' + Date.now(), before, {encoding:'utf8', flag:'wx'})
      await writeFile(composition + '.upgrading', after, 'utf8')
      await rename(composition + '.upgrading', composition)
    }
    ctx.logger?.(`scientific-reading: preset "${presetId}" 已存在于 ${targetDir}，跳过安装`)
    return true
  }
  try {
    await mkdir(targetDir, { recursive: true })
    await cp(sourceDir, targetDir, { recursive: true })
    ctx.logger?.(`scientific-reading: 已安装 ${PRESET_DISPLAY_NAME} preset "${presetId}" 到 ${targetDir}`)
    return true
  } catch (error) {
    ctx.logger?.(`scientific-reading: 安装 preset "${presetId}" 到 ${targetDir} 失败（${error instanceof Error ? error.message : String(error)}）；可手动复制 preset/scientific-reading/`)
    return false
  }
}

export async function readPackagedPresetComposition(): Promise<string> {
  return readFile(join(packagedPresetDir(), 'agent.cordis.yml'), 'utf8')
}

/** 从 AgentPresets 已创建的 standing mount 读取宿主单例的 scope tag。 */
export async function standingScopeTag(
  ctx: PresetHostContext,
  presetId: string,
  key: unknown,
): Promise<symbol> {
  const pending = readAgentPresets(ctx)?.standing?.get(presetId)
  if (pending === undefined) {
    throw new Error(`scientific-reading: preset "${presetId}" 在 standingKeyFor() 之后没有 standing scope`)
  }
  const standing = await pending
  if (standing.key !== key) {
    throw new Error(`scientific-reading: preset "${presetId}" 的 standing scope 在预加载期间发生变化`)
  }
  const tag = Object.getOwnPropertySymbols(standing.scope.ctx)
    .find((candidate) => Reflect.get(standing.scope.ctx, candidate) === key)
  if (tag === undefined) {
    throw new Error(`scientific-reading: preset "${presetId}" 的 standing context 没有 scope tag`)
  }
  return tag
}

/** 把 sr_* 工具注册到文献模式 standing key 上；其他模式看不到这些工具。 */
export async function mountPresetCapabilities(
  ctx: PresetHostContext,
  key: unknown,
  scopeTag: symbol,
  config: PluginConfig,
): Promise<void> {
  const scoped = ctx.extend({ [scopeTag]: key })
  registerTools(scoped, config)
  registerLibraryTools(scoped, config)
  registerReviewTools(scoped, config)
  registerPaperTools(scoped, config)
  registerRadarTools(scoped, config)
  registerModelPolicyTools(scoped, config)
}

export async function mountLiteratureTools(ctx: PresetHostContext, config: PluginConfig): Promise<boolean> {
  const presets = readAgentPresets(ctx)
  if (!presets) {
    ctx.logger?.('scientific-reading: 宿主没有 agentPresets，文献工具未启用（请在对话栏选择文献模式）')
    return false
  }
  const presetId = resolvePresetId(config)
  try {
    const standingKey = await presets.standingKeyFor(presetId)
    const scopeTag = await standingScopeTag(ctx, presetId, standingKey)
    await mountPresetCapabilities(ctx, standingKey, scopeTag, config)
    ctx.logger?.(`scientific-reading: 文献工具已挂到 ${PRESET_DISPLAY_NAME}（${presetId}）`)
    return true
  } catch (error) {
    ctx.logger?.(`scientific-reading: 未能把文献工具挂到 ${PRESET_DISPLAY_NAME}（${error instanceof Error ? error.message : String(error)}）`)
    return false
  }
}
