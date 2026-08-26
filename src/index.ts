/** DSH 单仓库文献工作流插件；所有资源注册挂 ctx.effect 自动清理。 */
import type { Context } from 'cordis'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { Config, resolveDataRoot, type Config as PluginConfig } from './config.js'
import { registerTools } from './tools.js'
import { registerLibraryTools } from './library_tools.js'
import { registerRoutes } from './routes.js'
import { registerSettings } from './settings.js'

export const name = '@dsh-external/dsh-scientific-reading'
export const inject = ['tools', 'webServer']

export { Config }

export function apply(ctx: Context, config: PluginConfig): void {
  registerSettings(ctx, config)
  registerTools(ctx, config)
  registerLibraryTools(ctx, config)
  try {
    registerRoutes(ctx, config)
  } catch (e) {
    try { writeFileSync(join(resolveDataRoot(config), '.sr-apply-error.log'), String((e as Error).stack ?? e), 'utf8') } catch { /* ignore */ }
    throw e
  }
  const root = config.dataRoot || '(默认 ~/scientific-reading-data)'
  ctx.logger?.('scientific-reading 插件已加载（dataRoot: ' + root + '，legalOnly: ' + config.legalOnly + '）')
}
