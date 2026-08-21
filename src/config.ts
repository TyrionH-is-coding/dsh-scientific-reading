import { homedir } from 'node:os'
import { join } from 'node:path'
import z from 'schemastery'

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
  /** 学校名（CARSI/WebVPN 显示用，可选） */
  school: string
  /** 只走合法来源（关 Sci-Hub/LibGen）。默认 true */
  legalOnly: boolean
  /** 下载输出目录。空 = <dataRoot>/downloads */
  outputDir: string
  /** 机构登录类型：cookies | webvpn | carsi | ezproxy | custom */
  loginType: string
  /** 装有 scansci-pdf 的 Python 解释器绝对路径（垫片运行用）。空 = 自动探测 uv 工具环境 */
  scansciPython: string
  /** 装有 scientific-reading 引擎的 Python 解释器绝对路径。空 = 自动探测（优先复用 scansci 同环境） */
  enginePython: string
  /** 飞书多维表格配置 JSON 路径（feishu-config-v1，含 app_token/table_id/field_map） */
  feishuConfig: string
  /** 飞书 App ID（子进程 env FEISHU_APP_ID，写多维表格鉴权用） */
  feishuAppId: string
  /** 飞书 App Secret（子进程 env FEISHU_APP_SECRET，写多维表格鉴权用） */
  feishuAppSecret: string
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
  feishuConfig: z.string().default(''),
  feishuAppId: z.string().default(''),
  feishuAppSecret: z.string().default(''),
})

export function resolveDataRoot(config: Config): string {
  if (config.dataRoot.trim()) return config.dataRoot.trim()
  return join(homedir(), 'scientific-reading-data')
}

export function resolveOutputDir(config: Config): string {
  if (config.outputDir.trim()) return config.outputDir.trim()
  return join(resolveDataRoot(config), 'downloads')
}

/** scansci-pdf 用户级数据目录（含 config.json），尊重官方 env 覆盖 */
export function scansciDataDir(): string {
  return process.env.SCANSCI_PDF_DATA_DIR
    ? process.env.SCANSCI_PDF_DATA_DIR
    : join(homedir(), '.scansci-pdf')
}
