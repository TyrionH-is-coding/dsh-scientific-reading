import type { Context } from 'cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { Config } from './config.js'
import { resolveDataRoot } from './config.js'
import {  engineJobStatus,  engineLibraryIngest,
  engineDerivedEnqueue,
  engineAbstractReadSubmit,
  engineLibraryList,
  engineFolderManage,
  engineClassification,
  engineFeishuProbe,
  engineFeishuResync,
  engineStartFullRead,
  engineContinueFullRead,
  engineExportAssets,
  engineAttachAndResumeFullReadPdf,
  engineJson,
} from './cli.js'
import { isPaperId } from './papers.js'

type Block = { type: 'text'; text: string }
const text = (t: string): Block[] => [{ type: 'text', text: t }]

export const BATCH_ACTIONS = new Set([
  'move_folder', 'add_tags', 'remove_tags',
  'queue_full_read', 'retry_failed', 'feishu_resync',
])

export async function submitBatch(config: Config, request: Record<string, unknown>) {
  const result = await engineJson(config, ['batch-submit'], request)
  return { ok: result.ok, json: result.json, stderr: result.stderr }
}

export async function listNavigation(config: Config, options: {
  page: number; pageSize: number; query?: string; folder?: string; tags: string[]; status?: string; recentDays?: number
}) {
  const args = ['library-list-v2', '--page', String(options.page), '--page-size', String(options.pageSize)]
  if (options.query) args.push('--query', options.query)
  if (options.folder) args.push('--folder-id', options.folder)
  for (const tag of options.tags) args.push('--tag', tag)
  if (options.status) args.push('--status', options.status)
  if (options.recentDays !== undefined) args.push('--recent-days', String(options.recentDays))
  const result = await engineJson(config, args)
  return { ok: result.ok, json: result.json, stderr: result.stderr }
}

export async function resolveNavigationArtifact(config: Config, paperId: string, kind: 'pdf') {
  const result = await engineJson(config, ['artifact-resolve', '--paper-id', paperId, '--kind', kind])
  return { ok: result.ok, json: result.json, stderr: result.stderr }
}

function scheduleDerived(config: Config, paperId: string, logger?: (message: string) => void): void {
  queueMicrotask(() => {
    void (async () => {
      const result = await engineDerivedEnqueue(config, paperId)
      if (!result.ok) logger?.('sr-derived pending: enqueue_failed')
    })().catch(() => logger?.('sr-derived pending: enqueue_failed'))
  })
}

export function registerLibraryTools(ctx: Context, config: Config): void {

  const requirePaperId = (value: string): void => {
    if (!isPaperId(value)) throw new Error('paper_id_invalid')
  }
  const requireJobId = (value: string): void => {
    if (!/^job_[0-9a-f]{16}$/.test(value)) throw new Error('job_id_invalid')
  }

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_start_full_read',
    description: '启动或复用单篇持久精读父任务。',
    parameters: { paper_id: { type: 'string', required: true } },
    output: { schema: { type: 'json' }, render: (_args: unknown, value: unknown) => text('精读任务：' + JSON.stringify(value)) },
    async execute(args: { paper_id: string }) {
      requirePaperId(args.paper_id)
      const r = await engineStartFullRead(config, args.paper_id)
      if (!r.ok || !r.json) return { ok: false, detail: r.stderr || 'full_read_start_failed' } as never
      return { parent_job_id: String(r.json.parent_job_id ?? '') } as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_start_full_read')

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_continue_full_read',
    description: '仅按当前 needs_user/waiting_agent gate 合同继续精读父任务。',
    parameters: { job_id: { type: 'string', required: true }, input: { type: 'object', required: true, additionalProperties: true } },
    output: { schema: { type: 'json' }, render: (_args: unknown, value: unknown) => text('精读继续：' + JSON.stringify(value)) },
    async execute(args: { job_id: string; input: Record<string, unknown> }) {
      requireJobId(args.job_id)
      const r = await engineContinueFullRead(config, args.job_id, args.input)
      return (r.json ?? { ok: false, detail: r.stderr || 'full_read_continue_failed' }) as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_continue_full_read')

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_attach_pdf',
    description: '为当前精读 gate 挂接本地绝对路径 PDF。',
    parameters: { paper_id: { type: 'string', required: true }, job_id: { type: 'string', required: true }, pdf: { type: 'string', required: true } },
    output: { schema: { type: 'json' }, render: (_args: unknown, value: unknown) => text('PDF 挂接：' + JSON.stringify(value)) },
    async execute(args: { paper_id: string; job_id: string; pdf: string }) {
      requirePaperId(args.paper_id)
      requireJobId(args.job_id)
      if (!/^(?:[A-Za-z]:[\\/]|\/).+\.pdf$/i.test(args.pdf)) throw new Error('absolute_pdf_required')
      const r = await engineAttachAndResumeFullReadPdf(config, args.paper_id, args.job_id, args.pdf)
      return (r.json ?? { ok: false, detail: r.stderr || 'pdf_attach_failed' }) as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_attach_pdf')

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_export_assets',
    description: '导出当前精读代的正文 Figure/Table 资产包。',
    parameters: { paper_id: { type: 'string', required: true } },
    output: { schema: { type: 'json' }, render: (_args: unknown, value: unknown) => text('图表导出：' + JSON.stringify(value)) },
    async execute(args: { paper_id: string }) {
      requirePaperId(args.paper_id)
      const r = await engineExportAssets(config, args.paper_id)
      return (r.json ?? { ok: false, detail: r.stderr || 'asset_export_failed' }) as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_export_assets')

  // ── sr_ingest：本地快速入库 + 脱离派生 ────────────────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_ingest',
    description: '快速写入本地文献库 skeleton；本地结果返回后再排队题录、Abstract、XLSX 和可选飞书派生。',
    parameters: {
      metadata: { type: 'object', required: true, additionalProperties: true, description: '论文元数据 JSON' },
    },
    output: {
      schema: { type: 'json' },
      render: (_args: unknown, value: unknown) => text('入库：' + JSON.stringify(value)),
    },
    async execute(args: { metadata?: Record<string, unknown> } & Record<string, unknown>) {
      const metadata = (args.metadata && typeof args.metadata === 'object' ? args.metadata : args) as Record<string, unknown>
      const result = await engineLibraryIngest(config, metadata)
      if (!result.ok || !result.json) return { ok: false, status: 'failed', detail: result.stderr || 'library_ingest_failed' } as never
      const paperId = String(result.json.paper_id ?? '')
      if (!paperId) return { ok: true, local: result.json, derived: 'pending' } as never
      scheduleDerived(config, paperId, ctx.logger?.bind(ctx))
      return { ok: true, local: result.json, paper_id: paperId, derived: 'pending' } as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_ingest')

  // ── sr_abstract_submit：提交 agent 翻译，闭合 waiting_agent gate ───────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_abstract_submit',
    description: '提交 agent 已完成的 Abstract 翻译 JSON；不会自动生成或伪造翻译。',
    parameters: {
      job_id: { type: 'string', required: true, description: '等待 agent 的 Abstract 任务 ID' },
      abstract_translation: { type: 'object', required: true, additionalProperties: true, description: 'agent 提供的 Abstract 翻译 JSON' },
    },
    output: {
      schema: { type: 'json' },
      render: (_args: unknown, value: unknown) => text('Abstract 提交：' + JSON.stringify(value)),
    },
    async execute(args: { job_id: string; abstract_translation: Record<string, unknown> }) {
      const r = await engineAbstractReadSubmit(config, args.job_id, args.abstract_translation)
      if (!r.ok || !r.json) return { ok: false, status: 'failed', detail: r.stderr || 'abstract_submit_failed' } as never
      return r.json as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_abstract_submit')

  // ── sr_init：初始化论文工作区 ──────────────────────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_library_list',
    description: '分页列出本地文献库（支持 page/page_size/query/folder/tags/status）。文献页数据源。',
    parameters: {
      page: { type: 'integer' },
      page_size: { type: 'integer' },
      query: { type: 'string' },
      folder: { type: 'string' },
      tags: { type: 'array', items: { type: 'string' } },
      status: { type: 'string' },
    },
    output: {
      schema: { type: 'json' },
      render: (_args: unknown, value: unknown) => {
        const raw = value as { items?: unknown }
        const items = Array.isArray(value) ? (value as Array<Record<string, unknown>>) : (Array.isArray(raw?.items) ? raw.items as Array<Record<string, unknown>> : [])
        if (items.length === 0) return text('文献库为空')
        const lines = items.map((it) => '· ' + String(it.paper_id) + ' | ' + String(it.title) + ' | ' + String(it.status))
        return text(lines.join('\n'))
      },
    },
    async execute(args: { page?: number; page_size?: number; query?: string; folder?: string; tags?: string[]; status?: string } = {}) {
      const r = await engineLibraryList(config, { page: args.page, pageSize: args.page_size, query: args.query, folder: args.folder, tags: args.tags, status: args.status })
      if (!r.ok) throw new Error(r.stderr || 'library-list 失败')
      return (r.json ?? []) as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_library_list')

  // ── sr_folder_manage：主库文件夹管理 ─────────────────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_folder_manage',
    description: '列出、创建或重命名主库文件夹。',
    parameters: {
      action: { type: 'string', required: true, description: 'list | create | rename' },
      folder_id: { type: 'string' },
      name: { type: 'string' },
    },
    output: { schema: { type: 'json' }, render: (_args: unknown, value: unknown) => text(JSON.stringify(value)) },
    async execute(args: { action: string; folder_id?: string; name?: string }) {
      if (args.action === 'list') {
        const r = await engineFolderManage(config, ['folder-list'])
        if (!r.ok) return { error: r.stderr || 'folder_list_failed' }
        return r.json as never
      }
      if (args.action === 'create' && args.name) {
        const r = await engineFolderManage(config, ['folder-create', '--name', args.name])
        return (r.json ?? { error: r.stderr || 'folder_create_failed' }) as never
      }
      if (args.action === 'rename' && args.folder_id && args.name) {
        const r = await engineFolderManage(config, ['folder-rename', '--folder-id', args.folder_id, '--name', args.name])
        return (r.json ?? { error: r.stderr || 'folder_rename_failed' }) as never
      }
      return { error: 'invalid_folder_request' }
    },
  })), '@dsh-external/dsh-scientific-reading: sr_folder_manage')

  // ── sr_classification_apply/undo：批量归类 ────────────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_classification_apply',
    description: '验证并应用批量归类提案（JSON）。',
    parameters: { proposals: { type: 'json', required: true }, minimum_confidence: { type: 'number' }, allow_new_folders: { type: 'boolean' } },
    output: { schema: { type: 'json' }, render: (_args: unknown, value: unknown) => text(JSON.stringify(value)) },
    async execute(args: { proposals: unknown; minimum_confidence?: number; allow_new_folders?: boolean }) {
      const proposals = Array.isArray(args.proposals) ? args.proposals : { proposals: args.proposals }
      const r = await engineClassification(config, 'classification-apply', proposals)
      return (r.json ?? { error: r.stderr || 'classification_apply_failed' }) as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_classification_apply')

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_classification_undo',
    description: '撤销一次批量归类操作。',
    parameters: { operation_id: { type: 'string', required: true } },
    output: { schema: { type: 'json' }, render: (_args: unknown, value: unknown) => text(JSON.stringify(value)) },
    async execute(args: { operation_id: string }) {
      const r = await engineClassification(config, 'classification-undo', undefined, args.operation_id)
      return (r.json ?? { error: r.stderr || 'classification_undo_failed' }) as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_classification_undo')

  // ── sr_library_search：全文搜索 ─────────────────────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_feishu_resync',
    description: '检查飞书自动同步配置，仅 enabled 时重排待同步条目。',
    parameters: { paper_ids: { type: 'array', items: { type: 'string' } } },
    output: { schema: { type: 'json' }, render: (_args: unknown, value: unknown) => text(JSON.stringify(value)) },
    async execute(args: { paper_ids?: string[] }) {
      const probe = await engineFeishuProbe(config)
      if (!probe.ok || !(probe.json?.enabled === true || probe.json?.status === 'enabled')) return { status: 'disabled', detail: probe.stderr || 'feishu_not_enabled' }
      const r = await engineFeishuResync(config, args.paper_ids ?? [])
      return (r.json ?? { status: 'failed', error: r.stderr || 'feishu_resync_failed' }) as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_feishu_resync')

  // ── sr_job_status：查询后台任务状态 ────────────────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_job_status',
    description: '查询后台任务状态。next_action：done | poll | agent | user；agent 时 detail.reason_code 指明要 agent 做什么。',
    parameters: {
      job_id: { type: 'string', required: true, description: '任务 ID' },
    },
    output: {
      schema: { type: 'json' },
      render: (_args: unknown, value: unknown) => {
        const v = value as Record<string, unknown>
        const d = (v.detail ?? {}) as Record<string, unknown>
        const reasonCode = d.reason_code ? String(d.reason_code) : ''
        const mineruHints: Record<string, string> = {
          mineru_api_token_required: '未配置 MINERU_API_TOKEN，请设置宿主环境变量并重启 DSH',
          mineru_api_auth_failed: 'MinerU API 凭证无效或已过期',
          mineru_api_quota_exceeded: 'MinerU API 今日额度或任务数已达上限',
          mineru_api_timeout: 'MinerU 解析仍未完成，可稍后继续',
          mineru_api_unavailable: 'MinerU 服务或网络暂时不可用，可稍后重试',
        }
        const reason = reasonCode ? '（' + (mineruHints[reasonCode] || reasonCode) + '）' : ''
        return text('任务 ' + String(v.job_id) + '：' + String(v.status) + '，next_action=' + String(v.next_action) + reason)
      },
    },
    async execute(args: { job_id: string }) {
      requireJobId(args.job_id)
      const r = await engineJobStatus(config, args.job_id)
      if (!r.ok || !r.json) throw new Error(r.stderr || 'job-status 失败')
      return r.json as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_job_status')
}
