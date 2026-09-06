import type { Context } from 'cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { Config } from './config.js'
import { resolveOutputDir } from './config.js'
import {
  probeOaProvider,
  resolveScansciPython,
  installScansci,
  ensureScansciConfig,
  fetchPaper,
  ensureBundledEngine,
  type FetchOutcome,
} from './cli.js'

type Block = { type: 'text'; text: string }

const text = (t: string): Block[] => [{ type: 'text', text: t }]

/** Phase 0 工具集。所有注册挂 ctx.effect（热重载/卸载自动注销）。 */
export function registerTools(ctx: Context, config: Config): void {
  // ── sr_setup：检查/安装 scansci-pdf + 合法来源配置 ──────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_setup',
    description: '检查或安装 OA 下载器及内置引擎。A 只自动获取开放获取全文；其余论文可补入本地 PDF。',
    parameters: {
      force: { type: 'boolean', description: '为 true 时在检测到未安装的情况下执行安装' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          engine_ok: { type: 'boolean', required: true },
          exe: { type: 'string', required: true },
          legal_only: { type: 'boolean', required: true },
          school: { type: 'string', required: true },
          output_dir: { type: 'string', required: true },
          config_path: { type: 'string', required: true },
          installed: { type: 'boolean', required: true },
          message: { type: 'string', required: true },
        },
      },
      render: (_args: unknown, value: unknown) => {
        const v = value as Record<string, unknown>
        return text(
          v.engine_ok
            ? `scansci-pdf 可用（${v.exe}）。自动获取：仅 OA；输出目录：${v.output_dir}`
            : `scansci-pdf 未就绪：${v.message}。请用 force=true 重试安装，或检查网络和托管 Python 环境后重新运行。`,
        )
      },
    },
    async execute(args: { force?: boolean }) {
      const engine = await ensureBundledEngine(config)
      if (!engine.ok) {
        return {
          engine_ok: false,
          exe: config.scansciExe,
          legal_only: true,
          school: '',
          output_dir: resolveOutputDir(config),
          config_path: '',
          installed: false,
          message: `内置引擎安装失败：${engine.detail.slice(-800)}`,
        }
      }
      const exe = await resolveScansciPython(config) || config.scansciExe
      const ok = await probeOaProvider(config)
      let installed = false
      if (!ok && args.force) {
        const r = await installScansci(engine.python)
        installed = r.exitCode === 0
        if (r.exitCode !== 0) {
          return {
            engine_ok: false,
            exe,
            legal_only: true,
            school: '',
            output_dir: resolveOutputDir(config),
            config_path: '',
            installed: false,
            message: `安装失败：${r.stderr.slice(-800) || r.stdout.slice(-800)}`,
          }
        }
      }
      const state = await ensureScansciConfig(config)
      const reProbe = await probeOaProvider(config)
      return {
        engine_ok: engine.ok && reProbe,
        exe,
        legal_only: state.legalOnly,
        school: state.school,
        output_dir: state.outputDir,
        config_path: state.path,
        installed,
        message: reProbe
          ? (installed ? '安装成功并已探活' : '已就绪') + (state.changed ? '；合法来源配置已写入' : '；配置无需变更')
          : '未安装（可用 force=true 自动安装）',
      }
    },
  })), '@dsh-external/dsh-scientific-reading: sr_setup')

  // ── sr_scansci_status：下载器健康 + 配置总览 ────────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_scansci_status',
    description: '查看 OA 下载器是否已安装与输出目录；安装状态不代表已取得某篇 PDF。',
    parameters: {},
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          engine_ok: { type: 'boolean', required: true },
          exe: { type: 'string', required: true },
          legal_only: { type: 'boolean', required: true },
          school: { type: 'string', required: true },
          output_dir: { type: 'string', required: true },
          doctor: { type: 'string', required: true },
        },
      },
      render: (_args: unknown, value: unknown) => {
        const v = value as Record<string, unknown>
        return text(
          `下载器：${v.engine_ok ? '正常' : '缺失'}（${v.exe}）\n自动获取：仅 OA\n输出目录：${v.output_dir}\n${String(v.doctor).slice(0, 800)}`,
        )
      },
    },
    async execute() {
      const exe = await resolveScansciPython(config) || config.scansciExe
      const ok = await probeOaProvider(config)
      return {
        engine_ok: ok,
        exe,
        legal_only: true,
        school: '',
        output_dir: resolveOutputDir(config),
        doctor: ok ? 'OA 下载器已安装；尚未验证具体论文获取。' : 'OA 下载器未安装。',
      }
    },
  })), '@dsh-external/dsh-scientific-reading: sr_scansci_status')

  // ── sr_scansci_fetch：DOI/URL → PDF ────────────────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_scansci_fetch',
    description: '从 arXiv、Europe PMC OA 或已配置邮箱的 Unpaywall 获取 PDF，给 DOI、arXiv 编号或含 DOI 的论文 URL。未取得时请补入本地 PDF。',
    parameters: {
      identifier: { type: 'string', required: true, description: 'DOI（如 10.48550/arXiv.1706.03762）或论文 URL' },
      output_dir: { type: 'string', description: '可选：输出目录（缺省用配置）' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          status: { type: 'string', required: true },
          quality: { type: 'string', required: true },
          reason: { type: 'string' },
          pdf_path: { type: 'string' },
          title: { type: 'string' },
          authors: { type: 'array', items: { type: 'string' } },
          year: { type: 'integer' },
          source: { type: 'string' },
          next_action_message: { type: 'string' },
        },
      },
      render: (_args: unknown, value: unknown) => {
        const v = value as Record<string, unknown>
        const head = `下载状态：${v.status}（${v.quality}）`
        if (v.status === 'success' && v.pdf_path) {
          return text(`${head}\n标题：${v.title || '未知'}\n作者：${Array.isArray(v.authors) ? (v.authors as string[]).join(', ') : ''}\n年份：${v.year ?? '未知'}　来源：${v.source || '未知'}\nPDF：${v.pdf_path}`)
        }
        const extra = v.next_action_message ? `\n下一步：${v.next_action_message}` : ''
        const reason = v.reason ? `\n原因：${v.reason}` : ''
        return text(`${head}${reason}${extra}\n请补入本地 PDF 后继续；A 只自动获取 OA。`)
      },
    },
    async execute(args: { identifier: string; output_dir?: string }) {
      const exe = await resolveScansciPython(config) || config.scansciExe
      const ok = await probeOaProvider(config)
      if (!ok) {
        throw new Error('scansci-pdf 未安装：请先运行 sr_setup（可用 force=true 自动安装）')
      }
      const outputDir = args.output_dir?.trim() || resolveOutputDir(config)
      const outcome: FetchOutcome = await fetchPaper(exe, args.identifier.trim(), outputDir, config)
      const p = outcome.paper
      return {
        status: outcome.status,
        quality: outcome.quality,
        reason: outcome.reason ?? undefined,
        pdf_path: p?.pdf_path ?? '',
        title: p?.title ?? '',
        authors: p?.authors ?? [],
        year: p?.year ?? undefined,
        source: p?.source ?? '',
        next_action_message: outcome.next_action?.message ?? undefined,
      }
    },
  })), '@dsh-external/dsh-scientific-reading: sr_scansci_fetch')

}
