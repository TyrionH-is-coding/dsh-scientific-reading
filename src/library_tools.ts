import type { Context } from 'cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { mkdir, writeFile, rename } from 'node:fs/promises'
import { join } from 'node:path'
import { createHash } from 'node:crypto'
import type { Config } from './config.js'
import { resolveDataRoot } from './config.js'
import { paperMetadataPath } from './papers.js'
import {
  engineEnsureItem,
  engineCheckItem,
  engineAttachPdf,
  engineSearch,
  engineInit,
  engineParse,
  engineQuickRead,
  engineJobStatus,
  engineFullRead,
  engineFeishuPreview,
  engineFeishuSync,
  engineZoteroMigrate,
  engineLibraryIngest,
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

function resolveMeta(config: Config, paperId: string): string {
  return paperMetadataPath(resolveDataRoot(config), paperId)
}

function scheduleDerived(config: Config, paperId: string, logger?: (message: string) => void): void {
  queueMicrotask(() => {
    void (async () => {
      const result = await engineDerivedEnqueue(config, paperId)
      if (!result.ok) logger?.('sr-derived pending: enqueue_failed')
    })().catch(() => logger?.('sr-derived pending: enqueue_failed'))
  })
}

/**
 * Phase 1 工具集：本地文献库（替代 Zotero）闭环。
 * sr_init → sr_library_check → sr_library_ensure(confirm) → sr_pdf_attach
 * → sr_parse → sr_quick_read → sr_job_status
 */
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
    name: 'sr_init',
    description: '[legacy/internal] 新建一篇论文的工作区（旧分步流程）。',
    parameters: {
      title: { type: 'string', required: true, description: '论文题名' },
      authors: { type: 'array', items: { type: 'string' }, description: '作者列表（可选）' },
      doi: { type: 'string', description: 'DOI（可选）' },
      pmid: { type: 'string', description: 'PMID（可选）' },
      year: { type: 'integer', description: '年份（可选）' },
      journal: { type: 'string', description: '期刊（可选）' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean', required: true },
          paper_id: { type: 'string' },
          detail: { type: 'string', required: true },
        },
      },
      render: (_args: unknown, value: unknown) => {
        const v = value as Record<string, unknown>
        return v.ok ? text('工作区已建：' + String(v.paper_id)) : text('失败：' + String(v.detail))
      },
    },
    async execute(args: { title: string; authors?: string[]; doi?: string; pmid?: string; year?: number; journal?: string }) {
      const dataRoot = resolveDataRoot(config)
      const pendingDir = join(dataRoot, '.pending')
      await mkdir(pendingDir, { recursive: true })
      const meta: Record<string, unknown> = {
        title: args.title.trim(),
        authors: args.authors ?? [],
        doi: args.doi?.trim() || null,
        pmid: args.pmid?.trim() || null,
        year: args.year ?? null,
        journal: args.journal?.trim() || null,
        zotero_key: null,
      }
      const digest = createHash('sha256').update(JSON.stringify(meta)).digest('hex').slice(0, 12)
      const staging = join(pendingDir, 'meta_' + digest + '.json')
      const tmp = staging + '.tmp'
      await writeFile(tmp, JSON.stringify(meta, null, 2) + '\n', 'utf8')
      await rename(tmp, staging)
      const result = await engineInit(config, staging)
      if (!result.ok || !result.json) {
        return { ok: false, paper_id: '', detail: result.stderr || 'init 失败' }
      }
      return { ok: true, paper_id: String(result.json.paper_id ?? ''), detail: String(result.json.path ?? '') }
    },
  })), '@dsh-external/dsh-scientific-reading: sr_init')

  // ── sr_library_check：只读查重 ──────────────────────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_library_check',
    description: '[legacy/internal] 本地文献库只读查重。',
    parameters: {
      paper_id: { type: 'string', required: true, description: '论文 ID（sr_init 返回）' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean', required: true },
          dedupe: { type: 'string', required: true },
          library_key: { type: 'string' },
          candidate_keys: { type: 'array', items: { type: 'string' } },
          detail: { type: 'string', required: true },
        },
      },
      render: (_args: unknown, value: unknown) => {
        const v = value as Record<string, unknown>
        const dedupe = String(v.dedupe)
        const map: Record<string, string> = {
          exact: '已存在于文献库（key=' + String(v.library_key ?? '') + '）',
          none: '未收录，可新建',
          ambiguous: '与其他条目冲突：' + JSON.stringify(v.candidate_keys ?? []),
        }
        return text('查重结果：' + (map[dedupe] ?? dedupe))
      },
    },
    async execute(args: { paper_id: string }) {
      const r = await engineCheckItem(config, resolveMeta(config, args.paper_id))
      if (!r.ok || !r.json) {
        return { ok: false, dedupe: 'error', library_key: '', candidate_keys: [], detail: r.stderr || '查重失败' }
      }
      const d = (r.json.detail ?? {}) as Record<string, unknown>
      return {
        ok: true,
        dedupe: String(d.dedupe ?? r.json.dedupe ?? 'none'),
        library_key: String(d.library_key ?? ''),
        candidate_keys: Array.isArray(d.candidate_keys) ? (d.candidate_keys as string[]) : [],
        detail: '',
      }
    },
  })), '@dsh-external/dsh-scientific-reading: sr_library_check')

  // ── sr_library_ensure：写入文献库（需 confirm）──────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_library_ensure',
    description: '[legacy/internal] 分步写入本地文献库；新流程请用 sr_ingest。',
    parameters: {
      paper_id: { type: 'string', required: true, description: '论文 ID' },
      confirm: { type: 'boolean', required: true, description: '是否已获得用户对“新建条目”的确认' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean', required: true },
          status: { type: 'string', required: true },
          dedupe: { type: 'string', required: true },
          gate: { type: 'string' },
          reason_code: { type: 'string' },
          library_key: { type: 'string' },
          candidate_keys: { type: 'array', items: { type: 'string' } },
          detail: { type: 'string', required: true },
        },
      },
      render: (_args: unknown, value: unknown) => {
        const v = value as Record<string, unknown>
        if (v.gate === 'user') return text('需要用户确认后才能新建条目：' + String(v.reason_code))
        if (v.gate === 'agent') return text('文献库存在歧义冲突：' + JSON.stringify(v.candidate_keys ?? []) + '，请让用户选择')
        return text('入库完成：' + String(v.dedupe) + '（key=' + String(v.library_key ?? '') + '）')
      },
    },
    async execute(args: { paper_id: string; confirm: boolean }) {
      const metaPath = resolveMeta(config, args.paper_id)
      if (!args.confirm) {
        const check = await engineCheckItem(config, metaPath)
        const dedupe = String(check.json?.dedupe ?? 'error')
        if (dedupe === 'exact') {
          return { ok: true, status: 'library_ready', dedupe, gate: '', reason_code: '', library_key: String(check.json?.library_key ?? ''), candidate_keys: [], detail: '' }
        }
        if (dedupe === 'ambiguous') {
          return { ok: false, status: 'ambiguous_reference', dedupe, gate: 'agent', reason_code: 'ambiguous_reference', library_key: '', candidate_keys: Array.isArray(check.json?.candidate_keys) ? (check.json.candidate_keys as string[]) : [], detail: '' }
        }
        return { ok: false, status: 'write_confirmation_required', dedupe, gate: 'user', reason_code: 'write_confirmation_required', library_key: '', candidate_keys: [], detail: '新建条目需要用户确认；请先询问用户，再带 confirm=true 重试' }
      }
      const r = await engineEnsureItem(config, metaPath)
      if (!r.ok || !r.json) {
        return { ok: false, status: 'failed', dedupe: 'error', gate: '', reason_code: '', library_key: '', candidate_keys: [], detail: r.stderr || '入库失败' }
      }
      if (String(r.json.dedupe) === 'ambiguous') {
        return { ok: false, status: 'ambiguous_reference', dedupe: 'ambiguous', gate: 'agent', reason_code: 'ambiguous_reference', library_key: '', candidate_keys: Array.isArray(r.json.candidate_keys) ? (r.json.candidate_keys as string[]) : [], detail: '' }
      }
      const d2 = (r.json.detail ?? {}) as Record<string, unknown>
      return { ok: true, status: String(r.json.status ?? 'library_ready'), dedupe: String(d2.dedupe ?? ''), gate: '', reason_code: '', library_key: String(d2.library_key ?? ''), candidate_keys: [], detail: '' }
    },
  })), '@dsh-external/dsh-scientific-reading: sr_library_ensure')

  // ── sr_pdf_attach：本地 PDF 登记到文献库附件 ────────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_pdf_attach',
    description: '[legacy/internal] 把本地 PDF 登记到文献库附件。',
    parameters: {
      paper_id: { type: 'string', required: true, description: '论文 ID' },
      pdf: { type: 'string', required: true, description: '本地 PDF 绝对路径' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean', required: true },
          status: { type: 'string', required: true },
          sha256: { type: 'string' },
          source_path: { type: 'string' },
          detail: { type: 'string', required: true },
        },
      },
      render: (_args: unknown, value: unknown) => {
        const v = value as Record<string, unknown>
        return v.ok
          ? text('PDF 已登记（sha256=' + String(v.sha256).slice(0, 12) + '…）：' + String(v.source_path))
          : text('失败：' + String(v.detail))
      },
    },
    async execute(args: { paper_id: string; pdf: string }) {
      const r = await engineAttachPdf(config, resolveMeta(config, args.paper_id), args.pdf)
      if (!r.ok || !r.json) {
        return { ok: false, status: 'failed', sha256: '', source_path: '', detail: r.stderr || '挂接失败' }
      }
      return {
        ok: true,
        status: String(r.json.status ?? 'pdf_ready'),
        sha256: String((r.json.detail as Record<string, unknown> | null)?.sha256 ?? ''),
        source_path: String((r.json.detail as Record<string, unknown> | null)?.source_path ?? ''),
        detail: '',
      }
    },
  })), '@dsh-external/dsh-scientific-reading: sr_pdf_attach')

  // ── sr_library_list：列出文献库 ─────────────────────────────────────
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
    name: 'sr_library_search',
    description: '[legacy/internal] 全文搜索本地文献库。',
    parameters: {
      query: { type: 'string', required: true, description: '搜索词' },
    },
    output: {
      schema: { type: 'json' },
      render: (_args: unknown, value: unknown) => {
        const items = Array.isArray(value) ? (value as Array<Record<string, unknown>>) : []
        if (items.length === 0) return text('无匹配')
        const lines = items.map((it) => '· ' + String(it.title) + '（' + String(it.paper_id) + '）')
        return text('匹配 ' + items.length + ' 条：\n' + lines.join('\n'))
      },
    },
    async execute(args: { query: string }) {
      const r = await engineSearch(config, args.query.trim())
      if (!r.ok) throw new Error(r.stderr || 'library-search 失败')
      return (r.json ?? []) as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_library_search')

  // ── sr_parse：后台快速解析 ─────────────────────────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_parse',
    description: '[legacy/internal] 把已挂 PDF 的论文排入后台解析。',
    parameters: {
      paper_id: { type: 'string', required: true, description: '论文 ID' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean', required: true },
          job_id: { type: 'string' },
          detail: { type: 'string', required: true },
        },
      },
      render: (_args: unknown, value: unknown) => {
        const v = value as Record<string, unknown>
        return v.ok ? text('解析任务已排队：' + String(v.job_id)) : text('失败：' + String(v.detail))
      },
    },
    async execute(args: { paper_id: string }) {
      const r = await engineParse(config, resolveMeta(config, args.paper_id))
      if (!r.ok || !r.json) {
        return { ok: false, job_id: '', detail: r.stderr || '排队失败' }
      }
      return { ok: true, job_id: String(r.json.job_id ?? ''), detail: String(r.json.status ?? '') }
    },
  })), '@dsh-external/dsh-scientific-reading: sr_parse')

  // ── sr_quick_read：后台准备默认中文浅读 ─────────────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_quick_read',
    description: '[legacy/internal] 把已解析的论文排入后台浅读任务。',
    parameters: {
      paper_id: { type: 'string', required: true, description: '论文 ID' },
      project_context: { type: 'string', description: '可选的用户课题背景短文本' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean', required: true },
          job_id: { type: 'string' },
          detail: { type: 'string', required: true },
        },
      },
      render: (_args: unknown, value: unknown) => {
        const v = value as Record<string, unknown>
        return v.ok ? text('浅读任务已排队：' + String(v.job_id)) : text('失败：' + String(v.detail))
      },
    },
    async execute(args: { paper_id: string; project_context?: string }) {
      const r = await engineQuickRead(config, resolveMeta(config, args.paper_id), args.project_context)
      if (!r.ok || !r.json) {
        return { ok: false, job_id: '', detail: r.stderr || '排队失败' }
      }
      return { ok: true, job_id: String(r.json.job_id ?? ''), detail: String(r.json.status ?? '') }
    },
  })), '@dsh-external/dsh-scientific-reading: sr_quick_read')

  // ── sr_full_read：后台准备按需全文精读 ─────────────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_full_read',
    description: '[legacy/internal] 把已解析的论文排入后台全文精读任务。',
    parameters: {
      paper_id: { type: 'string', required: true, description: '论文 ID' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean', required: true },
          job_id: { type: 'string' },
          detail: { type: 'string', required: true },
        },
      },
      render: (_args: unknown, value: unknown) => {
        const v = value as Record<string, unknown>
        return v.ok ? text('精读任务已排队：' + String(v.job_id)) : text('失败：' + String(v.detail))
      },
    },
    async execute(args: { paper_id: string }) {
      const r = await engineFullRead(config, resolveMeta(config, args.paper_id))
      if (!r.ok || !r.json) {
        return { ok: false, job_id: '', detail: r.stderr || '排队失败' }
      }
      return { ok: true, job_id: String(r.json.job_id ?? ''), detail: String(r.json.status ?? '') }
    },
  })), '@dsh-external/dsh-scientific-reading: sr_full_read')

  // ── sr_feishu_preview：零网络生成飞书同步预览 ───────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_feishu_preview',
    description: '[legacy/internal] 零网络生成飞书多维表格同步预览；不进入快速入库流程。',
    parameters: {
      paper_id: { type: 'string', required: true, description: '论文 ID' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean', required: true },
          status: { type: 'string' },
          path: { type: 'string' },
          payload_sha256: { type: 'string' },
          dedupe_keys: { type: 'array' },
          detail: { type: 'string' },
        },
      },
      render: (_args: unknown, value: unknown) => {
        const v = value as Record<string, unknown>
        return v.ok ? text('飞书预览就绪：' + String(v.path)) : text('失败：' + String(v.detail))
      },
    },
    async execute(args: { paper_id: string }) {
      const r = await engineFeishuPreview(config, resolveMeta(config, args.paper_id))
      if (!r.ok || !r.json || r.json.error) {
        return { ok: false, status: '', path: '', payload_sha256: '', dedupe_keys: [], detail: (r.json?.error as string) || r.stderr || '预览失败' }
      }
      return {
        ok: true,
        status: String(r.json.status ?? ''),
        path: String(r.json.path ?? ''),
        payload_sha256: String(r.json.payload_sha256 ?? ''),
        dedupe_keys: Array.isArray(r.json.dedupe_keys) ? r.json.dedupe_keys : [],
        detail: 'preview_ready',
      }
    },
  })), '@dsh-external/dsh-scientific-reading: sr_feishu_preview')

  // ── sr_feishu_sync：显式授权后同步飞书多维表格 ──────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_feishu_sync',
    description: '[legacy/internal] 逐篇确认后同步飞书；不进入快速入库流程。',
    parameters: {
      paper_id: { type: 'string', required: true, description: '论文 ID' },
      confirm: { type: 'boolean', required: true, description: '是否已获得用户对本次飞书写入的确认（必须先预览）' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean', required: true },
          job_id: { type: 'string' },
          detail: { type: 'string', required: true },
        },
      },
      render: (_args: unknown, value: unknown) => {
        const v = value as Record<string, unknown>
        return v.ok ? text('飞书同步已排队：' + String(v.job_id)) : text('失败：' + String(v.detail))
      },
    },
    async execute(args: { paper_id: string; confirm: boolean }) {
      if (!args.confirm) {
        return { ok: false, job_id: '', detail: 'write_confirmation_required：请先 sr_feishu_preview 预览并取得用户确认' }
      }
      const r = await engineFeishuSync(config, resolveMeta(config, args.paper_id))
      if (!r.ok || !r.json || r.json.error) {
        return { ok: false, job_id: '', detail: (r.json?.error as string) || r.stderr || '同步失败' }
      }
      return { ok: true, job_id: String(r.json.job_id ?? ''), detail: String(r.json.status ?? '') }
    },
  })), '@dsh-external/dsh-scientific-reading: sr_feishu_sync')

  // ── sr_zotero_migrate：Zotero 旧数据一次性迁移 ─────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_zotero_migrate',
    description: '[legacy/internal] Zotero 旧数据一次性迁移。',
    parameters: {
      dry_run: { type: 'boolean', description: '为 true 时只列出将迁移的条目，不写入本地库' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          status: { type: 'string', required: true },
          total: { type: 'integer' },
          migrated: { type: 'integer' },
          ambiguous: { type: 'integer' },
          entries: { type: 'array' },
          ambiguous_entries: { type: 'array' },
          error: { type: 'string' },
        },
      },
      render: (_args: unknown, value: unknown) => {
        const v = value as Record<string, unknown>
        if (v.error) return text('迁移失败：' + String(v.error))
        return text('Zotero 迁移：status=' + String(v.status) + ' total=' + String(v.total) + ' migrated=' + String(v.migrated ?? 0) + ' ambiguous=' + String(v.ambiguous ?? 0))
      },
    },
    async execute(args: { dry_run?: boolean }) {
      const r = await engineZoteroMigrate(config, args.dry_run === true)
      if (!r.ok) {
        // 连接失败（Zotero 未运行）等：exit 4 但 json 含 error
        return (r.json ?? { status: 'failed', error: r.stderr || '迁移失败' }) as never
      }
      return (r.json ?? { status: 'failed', error: '无输出' }) as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_zotero_migrate')

  // ── sr_feishu_resync：仅在本地 probe enabled 后重排 ──────────────────
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
        const reason = d.reason_code ? '（' + String(d.reason_code) + '）' : ''
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
