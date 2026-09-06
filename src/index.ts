/** DSH 单仓库文献工作流插件；所有资源注册挂 ctx.effect 自动清理。 */
import type { Context } from 'cordis'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { Config, resolveDataRoot, type Config as PluginConfig } from './config.js'
import {
  installPreset,
  mountLiteratureTools,
  resolvePresetId,
  type PresetHostContext,
} from './preset.js'
import { registerRoutes } from './routes.js'
import { registerSettings } from './settings.js'
import { registerStatusRoutes } from './status_routes.js'
import { registerReviewSessionRoutes } from './review_sessions.js'

export const name = '@dsh-external/dsh-scientific-reading'
export const inject = ['tools', 'webServer', 'agentPresets', 'agents', 'subagents']

export { Config }
export { withEngineScope, type EngineScope } from './engine_scope.js'
export { engineJson, engineStartFullRead, engineContinueFullRead, engineAttachAndResumeFullReadPdf } from './cli.js'
export {
  DEFAULT_PRESET_ID,
  PRESET_DISPLAY_NAME,
  installPreset,
  mountLiteratureTools,
  resolveDshHome,
} from './preset.js'

export async function apply(ctx: Context, config: PluginConfig): Promise<void> {
  registerSettings(ctx, config)
  try {
    registerRoutes(ctx, config)
    registerStatusRoutes(ctx, config)
    registerReviewSessionRoutes(ctx, config)
  } catch (e) {
    try { writeFileSync(join(resolveDataRoot(config), '.sr-apply-error.log'), String((e as Error).stack ?? e), 'utf8') } catch { /* ignore */ }
    throw e
  }
  const host = ctx as PresetHostContext
  try {
    if (config.installPreset !== false) {
      await installPreset(host, resolvePresetId(config))
    }
    await mountLiteratureTools(host, config)
  } catch (e) {
    ctx.logger?.('scientific-reading: 文献模式装配失败，宿主继续启动（' + (e instanceof Error ? e.message : String(e)) + '）')
  }
  const root = config.dataRoot || '(默认 ~/scientific-reading-data)'
  ctx.logger?.('scientific-reading 插件已加载（dataRoot: ' + root + '，OA-only；工具仅文献模式启用）')
}
