import { homedir } from 'node:os'
import { join } from 'node:path'
import z from '@deepseek-ai/schemastery'

/**
 * 插件配置。Phase 0 由 cordis.yml / 默认值提供；
 * Phase 2 再接入设置页（installSettingsSection）。
 */
export interface Config {
  /** 数据根目录（仓库外）。空 = ~/scientific-reading-data */
  dataRoot: string
  /** Python 解释器（scansci-pdf 安装用） */
  python: string
  /** scansci-pdf 可执行文件：PATH 名或绝对路径 */
  scansciExe: string
  /** 旧配置兼容字段；A 不使用机构来源。 */
  school: string
  /** 旧配置兼容字段；A 始终只自动获取 OA，false 不放宽限制。 */
  legalOnly: boolean
  /** 下载输出目录。空 = <dataRoot>/downloads */
  outputDir: string
  /** 机构登录类型：cookies | webvpn | carsi | ezproxy | custom */
  loginType: string
  /** 装有 scansci-pdf 的 Python 解释器绝对路径（垫片运行用）。空 = 自动探测 uv 工具环境 */
  scansciPython: string
  /** 装有 scientific-reading 引擎的 Python 解释器绝对路径。空 = 自动探测（优先复用 scansci 同环境） */
  enginePython: string
  /** 安装到 `$DSH_HOME/.agent-presets/` 的预设目录名（文献模式） */
  presetId: string
  /** 启动时是否把打包的文献模式预设安装到用户 preset 根（幂等，不覆盖手改） */
  installPreset: boolean
}

export const Config = z.object({
  dataRoot: z.string().default(''),
  python: z.string().default('python'),
  scansciExe: z.string().default('scansci-pdf'),
  school: z.string().default(''),
  legalOnly: z.boolean().default(true),
  outputDir: z.string().default(''),
  loginType: z.string().default('carsi'),
  scansciPython: z.string().default(''),
  enginePython: z.string().default(''),
  presetId: z.string().default('scientific-reading'),
  installPreset: z.boolean().default(true),
})

export function resolveDataRoot(config: Config): string {
  if (config.dataRoot.trim()) return config.dataRoot.trim()
  return join(homedir(), 'scientific-reading-data')
}

export function resolveOutputDir(config: Config): string {
  if (config.outputDir.trim()) return config.outputDir.trim()
  return join(resolveDataRoot(config), 'downloads')
}

/** 插件自己的 OA 下载状态目录，不读取独立 ScanSci 的用户配置或登录态。 */
export function scansciDataDir(config: Config): string {
  return join(resolveDataRoot(config), 'oa-downloader')
}
