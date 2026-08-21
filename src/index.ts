/**
 * @dsh-external/dsh-scientific-reading — 文献工作流插件（Phase 0：下载段）。
 *
 * 当前范围（Phase 0）：
 *  - sr_setup              检查/安装 scansci-pdf + 合法来源配置
 *  - sr_scansci_status     下载器健康 + 配置总览
 *  - sr_scansci_fetch      DOI/URL → PDF 落盘 + 元数据
 *  - sr_scansci_login      机构登录（浏览器弹出，用户亲自完成）
 *  - sr_scansci_set_school 设置学校
 *
 * 后续阶段（见 docs/roadmap.md）：
 *  - Phase 1：本地文献库（SQLite）替代 Zotero + 解析/浅读闭环
 *  - Phase 2：【文献】标签页（conversation.view）模拟 Zotero 界面
 *  - Phase 3：飞书同步 / 精读 / Zotero 迁移
 *
 * 规范：所有资源注册挂 ctx.effect（热重载/卸载自动清理）。
 */
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
