/**
 * 设置注册（T2.4）：设置页插件配置卡片。
 *
 * 机制：installSettingsSection 注册 `scientific-reading` namespace（Config schema，
 * composition entry 作 base 层）。设置文档/页面变更时，onChange 把最新 resolved
 * 值原地 Object.assign 回初始 config 对象——tools/routes 的闭包持有同一引用，
 * 无需改任何模块签名即可读到新配置（零侵入联动）。
 */
import type { Context } from 'cordis'
import { installSettingsSection, settingsNamespace } from '@deepseek-ai/dsh-settings'
import { Config, type Config as PluginConfig } from './config.js'

/** 设置 namespace：kebab-case，与插件短名一致。 */
export const SETTINGS_NS = 'scientific-reading'

/**
 * 注册设置 section 并把配置变更联动到 `config` 对象。
 * @param ctx - 插件上下文（apply 的 ctx）。
 * @param config - composition entry config（apply 的 config；会被原地同步）。
 */
export function registerSettings(ctx: Context, config: PluginConfig): void {
  // installSettingsSection 内部用 ctx.inject（cordis 插件上下文 API）——
  // harness 冒烟的 fakeCtx 没有该方法时直接跳过（无 settings 服务，属预期）。
  if (typeof (ctx as { inject?: unknown }).inject !== 'function') return
  let current: () => PluginConfig = () => config
  installSettingsSection(ctx, settingsNamespace(SETTINGS_NS), Config, config, {
    setSource: (source) => {
      current = source
    },
    onChange: () => {
      try {
        const next = current()
        if (next && typeof next === 'object') Object.assign(config, next)
        ctx.logger?.('scientific-reading 设置已更新（dataRoot: ' + (config.dataRoot || '(默认)') + '，legalOnly: ' + String(config.legalOnly) + '）')
      } catch (e) {
        ctx.logger?.('scientific-reading 设置同步失败: ' + (e instanceof Error ? e.message : String(e)))
      }
    },
  })
}
