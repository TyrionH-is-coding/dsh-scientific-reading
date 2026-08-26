import type { Context } from 'cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { Config } from './config.js'
import { resolveOutputDir } from './config.js'
import {
  probeScansci,
  doctorScansci,
  installScansci,
  ensureScansciConfig,
  fetchPaper,
  loginScansci,
  setSchoolScansci,
  readScansciConfig,
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
    description: '检查或安装 scansci-pdf 下载器，并按设置写入合法来源配置（默认关 Sci-Hub）。安装后自动探活。',
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
            ? `scansci-pdf 可用（${v.exe}）。合法来源模式：${v.legal_only ? '开启（Sci-Hub 已关）' : '关闭'}；学校：${v.school || '未设置'}；输出目录：${v.output_dir}`
            : `scansci-pdf 未就绪：${v.message}。请用 force=true 重试安装，或手动执行 pip install scansci-pdf 后重新运行。`,
        )
      },
    },
    async execute(args: { force?: boolean }) {
      const engine = await ensureBundledEngine(config)
      if (!engine.ok) {
        return {
          engine_ok: false,
          exe: config.scansciExe,
          legal_only: config.legalOnly,
          school: config.school,
          output_dir: resolveOutputDir(config),
          config_path: '',
          installed: false,
          message: `内置引擎安装失败：${engine.detail.slice(-800)}`,
        }
      }
      const exe = config.scansciExe
      const ok = await probeScansci(exe)
      let installed = false
      if (!ok && args.force) {
        const r = await installScansci(config.python)
        installed = r.exitCode === 0
        if (r.exitCode !== 0) {
          return {
            engine_ok: false,
            exe,
            legal_only: config.legalOnly,
            school: config.school,
            output_dir: resolveOutputDir(config),
            config_path: '',
            installed: false,
            message: `安装失败：${r.stderr.slice(-800) || r.stdout.slice(-800)}`,
          }
        }
      }
      const state = await ensureScansciConfig(config)
      const reProbe = ok || installed
      return {
        engine_ok: engine.ok,
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
    description: '查看 scansci-pdf 下载器健康状态、合法来源开关、学校与输出目录配置。',
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
          `下载器：${v.engine_ok ? '正常' : '缺失'}（${v.exe}）\n合法来源模式：${v.legal_only ? '开启' : '关闭'}\n学校：${v.school || '未设置'}\n输出目录：${v.output_dir}\n${String(v.doctor).slice(0, 800)}`,
        )
      },
    },
    async execute() {
      const exe = config.scansciExe
      const ok = await probeScansci(exe)
      const raw = await readScansciConfig()
      const doctor = ok ? await doctorScansci(exe) : ''
      return {
        engine_ok: ok,
        exe,
        legal_only: raw.download_strategy === 'legal_only' || (raw.scihub_enabled !== true),
        school: String(raw.carsi_idp_name ?? raw.vpnsci_school ?? config.school ?? ''),
        output_dir: resolveOutputDir(config),
        doctor,
      }
    },
  })), '@dsh-external/dsh-scientific-reading: sr_scansci_status')

  // ── sr_scansci_fetch：DOI/URL → PDF ────────────────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_scansci_fetch',
    description: '下载一篇论文的 PDF：给 DOI 或 URL，自动试 arXiv/开放获取/机构访问等来源，返回 PDF 路径与元数据。默认只走合法来源。',
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
        return text(`${head}${reason}${extra}\n可先运行 sr_scansci_login 完成机构登录后重试。`)
      },
    },
    async execute(args: { identifier: string; output_dir?: string }) {
      const exe = config.scansciExe
      const ok = await probeScansci(exe)
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

  // ── sr_scansci_login：机构登录（浏览器弹出，用户亲自完成） ──────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_scansci_login',
    description: '打开真实浏览器完成机构登录（CARSI/WebVPN/Cookie）。浏览器会弹出，请在页面里选学校、输账号、过验证码/MFA——插件看不到密码。',
    parameters: {
      login_type: { type: 'string', description: 'cookies | webvpn | carsi | ezproxy | custom（缺省用配置）' },
      url: { type: 'string', description: '可选：登录目标 URL（cookie/custom 模式用）' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          started: { type: 'boolean', required: true },
          login_type: { type: 'string', required: true },
          detail: { type: 'string', required: true },
        },
      },
      render: (_args: unknown, value: unknown) => {
        const v = value as Record<string, unknown>
        return v.started
          ? text(`浏览器已启动（${v.login_type}）。请在浏览器中完成登录；完成后会话将保存在本机。`)
          : text(`登录未能启动：${v.detail}`)
      },
    },
    async execute(args: { login_type?: string; url?: string }) {
      const exe = config.scansciExe
      const loginType = args.login_type?.trim() || config.loginType || 'carsi'
      const r = await loginScansci(exe, loginType, args.url?.trim() || undefined)
      const detail = (r.stdout || r.stderr).slice(-1500)
      return { started: r.exitCode === 0, login_type: loginType, detail }
    },
  })), '@dsh-external/dsh-scientific-reading: sr_scansci_login')

  // ── sr_scansci_set_school：设置学校 ────────────────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_scansci_set_school',
    description: '设置机构（学校）名称，供 CARSI/WebVPN 机构访问使用。学校名写进 scansci-pdf 配置。',
    parameters: {
      school: { type: 'string', required: true, description: '学校名称（支持部分匹配）' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean', required: true },
          school: { type: 'string', required: true },
          detail: { type: 'string', required: true },
        },
      },
      render: (_args: unknown, value: unknown) => {
        const v = value as Record<string, unknown>
        return v.ok
          ? text(`学校已设置：${v.school}`)
          : text(`设置失败：${v.detail}`)
      },
    },
    async execute(args: { school: string }) {
      const exe = config.scansciExe
      const ok = await probeScansci(exe)
      if (!ok) {
        throw new Error('scansci-pdf 未安装：请先运行 sr_setup')
      }
      const school = args.school.trim()
      const r = await setSchoolScansci(exe, school)
      await ensureScansciConfig(config)
      return { ok: r.exitCode === 0, school, detail: (r.stdout || r.stderr).slice(-800) }
    },
  })), '@dsh-external/dsh-scientific-reading: sr_scansci_set_school')
}
