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
  engineList,
  engineSearch,
  engineInit,
  engineParse,
  engineQuickRead,
  engineJobStatus,
  engineFullRead,
  engineFeishuPreview,
  engineFeishuSync,
  engineZoteroMigrate,
} from './cli.js'

type Block = { type: 'text'; text: string }
const text = (t: string): Block[] => [{ type: 'text', text: t }]

function resolveMeta(config: Config, paperId: string): string {
  return paperMetadataPath(resolveDataRoot(config), paperId)
}

/**
 * Phase 1 工具集：本地文献库（替代 Zotero）闭环。
 * sr_init → sr_library_check → sr_library_ensure(confirm) → sr_pdf_attach
 * → sr_parse → sr_quick_read → sr_job_status
 */
export function registerLibraryTools(ctx: Context, config: Config): void {

  // ── sr_init：初始化论文工作区 ──────────────────────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_init',
    description: '新建一篇论文的工作区（元数据入参，返回 paper_id）。后续用 paper_id 调用入库/挂PDF/解析。',
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
    description: '本地文献库只读查重（不写入）：dedupe = exact（已存在）| none（可新建）| ambiguous（冲突，需用户选择）。',
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
    description: '把论文写入本地文献库（替代 Zotero 入库）。新建条目需要 confirm=true（agent 先取得用户确认）；已存在时无需确认。歧义时返回 ambiguous 由用户选择。',
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
    description: '把本地 PDF 登记到文献库附件（校验 + 复制到工作区 + 读回验证）。pdf 必须是绝对路径。',
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
    description: '列出本地文献库全部条目（论文 ID/题名/状态/年份）。文献页数据源。',
    parameters: {},
    output: {
      schema: { type: 'json' },
      render: (_args: unknown, value: unknown) => {
        const items = Array.isArray(value) ? (value as Array<Record<string, unknown>>) : []
        if (items.length === 0) return text('文献库为空')
        const lines = items.map((it) => '· ' + String(it.paper_id) + ' | ' + String(it.title) + ' | ' + String(it.status))
        return text(lines.join('\n'))
      },
    },
    async execute() {
      const r = await engineList(config)
      if (!r.ok) throw new Error(r.stderr || 'library-list 失败')
      return (r.json ?? []) as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_library_list')

  // ── sr_library_search：全文搜索 ─────────────────────────────────────
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_library_search',
    description: '全文搜索本地文献库（FTS5：标题/作者/DOI/期刊）。返回匹配条目。',
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
    description: '把已挂 PDF 的论文排入后台解析（parsed_fast）。返回 job_id，用 sr_job_status 轮询。',
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
    description: '把已解析的论文排入后台浅读任务。到达 produce_quick_read gate 时，agent 需读取 gate 列出的本地文件并提交 quick-read-v1 提案。',
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
    description: '把已解析的论文排入后台全文精读任务。到达 produce_full_read gate 时，agent 需读取 gate 列出的本地文件并提交 full-read-v1 提案（含翻译与复核）。',
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
    description: '零网络生成飞书多维表格同步预览（需设置页配置 feishuConfig JSON 路径）。返回预览文件路径与去重键，写库前先预览确认。',
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
    description: '显式授权后后台同步飞书多维表格（设置页只配 feishuConfig；FEISHU_APP_ID/SECRET 须在启动 DSH 前设为宿主环境变量）。写库前必须先用 sr_feishu_preview 预览并取得用户确认（confirm=true）。',
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
    description: 'Zotero 旧数据一次性迁移：读 Zotero Desktop（须本机运行）条目列表 → 批量写入本地文献库，保留 zotero_key。dry_run=true 只列出将迁移的条目（不写入）。',
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
      const r = await engineJobStatus(config, args.job_id)
      if (!r.ok || !r.json) throw new Error(r.stderr || 'job-status 失败')
      return r.json as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_job_status')
}
