import type { Context } from 'cordis'
import type { Context as CordisContext } from 'cordis'

declare module 'cordis' {
  interface Context {
    webServer: {
      register(route: {
        kind: 'exact' | 'prefix'
        path: string
        handler: (req: import('node:http').IncomingMessage, res: import('node:http').ServerResponse) => void | Promise<void>
      }): () => void
    }
  }
}
import type { IncomingMessage, ServerResponse } from 'node:http'
import { mkdir, writeFile, readFile, access, rename, lstat } from 'node:fs/promises'
import { isAbsolute, join } from 'node:path'
import { createHash, randomUUID } from 'node:crypto'
import type { Config } from './config.js'
import { resolveDataRoot, resolveOutputDir } from './config.js'
import { isPaperId, parsePaperRoute } from './papers.js'
import { BATCH_ACTIONS, listNavigation, resolveNavigationArtifact, submitBatch } from './library_tools.js'
import {
  engineList,
  engineJobStatus,
  engineParse,
  engineQuickRead,
  engineCheckItem,
  engineInit,
  engineLibraryItem,
  engineLibraryIngest,
  engineFolderManage,
  engineDerivedEnqueue,
  fetchPaper,
  engineStartFullRead,
  engineContinueFullRead,
  engineExportAssets,
  engineResolveArtifact,
  engineAttachAndResumeFullReadPdf,
} from './cli.js'

const JOB_ID_RE = /^job_[0-9a-f]{16}$/

function sendJson(res: ServerResponse, status: number, value: unknown): void {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' })
  res.end(JSON.stringify(value))
}

function sendText(res: ServerResponse, status: number, text: string, contentType = 'text/plain; charset=utf-8'): void {
  res.writeHead(status, { 'Content-Type': contentType })
  res.end(text)
}

function readBody(req: IncomingMessage, maxBytes = 64 * 1024 * 1024): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = []
    let size = 0
    req.on('data', (c: Buffer) => {
      size += c.length
      if (size > maxBytes) { reject(new Error('body_too_large')); req.destroy?.() }
      else chunks.push(c)
    })
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
    req.on('error', reject)
  })
}

function readJsonBody(req: IncomingMessage, maxBytes = 64 * 1024 * 1024): Promise<Record<string, unknown>> {
  return readBody(req, maxBytes).then((text) => {
    try { return text ? (JSON.parse(text) as Record<string, unknown>) : {} }
    catch { throw new Error('invalid_json') }
  })
}

async function readOrNull(path: string): Promise<string | null> {
  try { return await readFile(path, 'utf8') } catch { return null }
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function artifactPath(root: string, rel: string, kind: 'reader' | 'exports' | 'pdf'): string | null {
  const normalized = rel.replace(/\\/g, '/')
  const allowed = kind === 'reader'
    ? /^generations\/[0-9a-f]{16}\/(?:reading\/reader\.html|output\/reader_full\.html)$/.test(normalized)
    : kind === 'pdf'
      ? /^generations\/[0-9a-f]{16}\/source\.pdf$/.test(normalized)
      : /^generations\/[0-9a-f]{16}\/exports$/.test(normalized)
  if (!allowed || normalized !== rel) return null
  return join(root, ...normalized.split('/'))
}

function sha256(bytes: Buffer): string {
  return createHash('sha256').update(bytes).digest('hex')
}

async function hasSymlink(root: string, target: string): Promise<boolean> {
  const relative = target.slice(root.length).replace(/^[\\/]+/, '').split(/[\\/]+/).filter(Boolean)
  let current = root
  for (const part of relative) {
    current = join(current, part)
    if ((await lstat(current).catch(() => null))?.isSymbolicLink()) return true
  }
  return false
}

const safeString = (value: unknown): string => typeof value === 'string' ? value : ''
const safeNullableString = (value: unknown): string | null => typeof value === 'string' ? value : null
const safeError = (value: unknown): string => typeof value === 'string'
  ? String(withoutSensitiveFields(value))
  : ''
const safeNonnegativeInteger = (value: unknown, fallback: number): number => Number.isInteger(value) && Number(value) >= 0 ? Number(value) : fallback

function navigationList(value: unknown, page: number, pageSize: number): Record<string, unknown> {
  const source = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  const rawItems = Array.isArray(source.items) ? source.items : []
  const items = rawItems.map((raw) => {
    const sourceItem = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
    return {
      paper_id: safeString(sourceItem.paper_id),
      title: safeString(sourceItem.title),
      authors_short: safeString(sourceItem.authors_short),
      year: Number.isInteger(sourceItem.year) ? sourceItem.year : null,
      folder: safeNullableString(sourceItem.folder),
      tags: Array.isArray(sourceItem.tags) ? sourceItem.tags.filter((tag): tag is string => typeof tag === 'string') : [],
      abstract_status: safeString(sourceItem.abstract_status),
      full_read_status: safeString(sourceItem.full_read_status),
      feishu_sync_state: safeString(sourceItem.feishu_sync_state),
      has_pdf: typeof sourceItem.has_pdf === 'boolean' ? sourceItem.has_pdf : false,
      has_reader: typeof sourceItem.has_reader === 'boolean' ? sourceItem.has_reader : false,
      feishu_record_url: safeString(sourceItem.feishu_record_url),
      last_error: safeError(sourceItem.last_error),
    }
  })
  const jobs = source.jobs && typeof source.jobs === 'object' ? source.jobs as Record<string, unknown> : {}
  return {
    items,
    page: Number.isInteger(source.page) && Number(source.page) >= 1 ? Number(source.page) : page,
    page_size: Number.isInteger(source.page_size) && Number(source.page_size) >= 1 && Number(source.page_size) <= 100 ? Number(source.page_size) : pageSize,
    total: safeNonnegativeInteger(source.total, items.length),
    jobs: {
      running: safeNonnegativeInteger(jobs.running, 0),
      queued: safeNonnegativeInteger(jobs.queued, 0),
    },
  }
}

function hasClientFeishuUrl(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false
  if (Array.isArray(value)) return value.some(hasClientFeishuUrl)
  return Object.entries(value as Record<string, unknown>).some(([key, child]) => key === 'feishu_record_url' || hasClientFeishuUrl(child))
}

function withoutSensitiveFields(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(withoutSensitiveFields)
  if (typeof value === 'string' && /(?:traceback|secret|token|password)/i.test(value)) return 'redacted'
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(Object.entries(value as Record<string, unknown>)
    .filter(([key]) => !/(?:stack|secret|token|password)/i.test(key))
    .map(([key, child]) => [key, withoutSensitiveFields(child)]))
}

const ERROR_TEXT_FIELDS = new Set(['error', 'last_error', 'error_status', 'message', 'detail'])

function safeLibraryItem(value: unknown, field = ''): unknown {
  if (Array.isArray(value)) return value.map((child) => safeLibraryItem(child))
  if (typeof value === 'string') return ERROR_TEXT_FIELDS.has(field) ? safeError(value) : value
  if (!value || typeof value !== 'object') return ERROR_TEXT_FIELDS.has(field) ? '' : value
  return Object.fromEntries(Object.entries(value as Record<string, unknown>)
    .filter(([key]) => !/(?:stack|secret|token|password)/i.test(key))
    .map(([key, child]) => [key, safeLibraryItem(child, key)]))
}

/**
 * 文献页 API 路由（只读数据 + 动作触发）。动作端点复用插件同一套引擎适配器。
 * 安全：paper_id / job_id 白名单校验；只读 dataRoot 内路径。
 */
export function registerRoutes(ctx: Context, config: Config): void {
  const dataRoot = () => resolveDataRoot(config)
  const paperRoot = (id: string) => join(dataRoot(), 'papers', id)

  // 注册容忍重复：历史残留路由（热重载遗留）由旧 handler 继续服务，
  // 宿主重启后残留清空、新注册自然接管。不因 duplicate 抛错导致 fiber 失败。
  const registerSafe = (route: { kind: 'exact' | 'prefix'; path: string; handler: (req: IncomingMessage, res: ServerResponse) => void | Promise<void> }) => {
    try {
      return ctx.webServer.register(route)
    } catch (e) {
      ctx.logger?.('sr-route duplicate ignored: ' + route.path + ' — ' + (e as Error).message)
      return () => {}
    }
  }
  const exact = (path: string, handler: (req: IncomingMessage, res: ServerResponse) => Promise<void>) => {
    ctx.effect(() => registerSafe({ kind: 'exact', path, handler }), 'sr-route:' + path)
  }
  const prefix = (path: string, handler: (req: IncomingMessage, res: ServerResponse) => Promise<void>) => {
    ctx.effect(() => registerSafe({ kind: 'prefix', path, handler }), 'sr-route:' + path)
  }

  const scheduleDerived = (paperId: string): void => {
    queueMicrotask(() => {
      void (async () => {
        const result = await engineDerivedEnqueue(config, paperId)
        if (!result.ok) ctx.logger?.('sr-derived pending: enqueue_failed')
      })().catch(() => { ctx.logger?.('sr-derived pending: enqueue_failed') })
    })
  }

  const requirePdfGate = async (paperId: string, jobId: string): Promise<boolean> => {
    if (!JOB_ID_RE.test(jobId)) return false
    const status = await engineJobStatus(config, jobId)
    const detail = status.json?.detail as Record<string, unknown> | undefined
    return status.ok && status.json?.paper_id === paperId && status.json?.status === 'waiting_user' && detail?.reason_code === 'pdf_required'
  }

  const safePdfResult = (paperId: string, jobId: string, attach: Record<string, unknown>, resumed: Record<string, unknown> | null) => {
    const detail = attach.detail as Record<string, unknown> | undefined
    return {
      paper_id: paperId,
      parent_job_id: jobId,
      status: String(resumed?.state ?? resumed?.status ?? 'queued'),
      sha256: typeof attach.sha256 === 'string' ? attach.sha256 : typeof detail?.sha256 === 'string' ? detail.sha256 : undefined,
      page_count: typeof attach.page_count === 'number' ? attach.page_count : typeof detail?.page_count === 'number' ? detail.page_count : undefined,
    }
  }

  // ── 轻量主库 API：只校验/转发，不在插件内实现筛选或批处理 ─────────────
  exact('/sr/api/library', async (req, res) => {
    try {
      if (req.method === 'GET') {
        const url = new URL(req.url ?? '/sr/api/library', 'http://localhost')
        const page = Number(url.searchParams.get('page') ?? 1)
        const pageSize = Number(url.searchParams.get('page_size') ?? 50)
        const recentRaw = url.searchParams.get('recent_days')
        const recentDays = recentRaw === null || recentRaw === '' ? undefined : Number(recentRaw)
        if (!Number.isInteger(page) || page < 1 || !Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100 || (recentDays !== undefined && (!Number.isInteger(recentDays) || recentDays < 0))) {
          return sendJson(res, 400, { error: 'invalid_pagination' })
        }
        const tags = [...url.searchParams.getAll('tags'), ...url.searchParams.getAll('tag')]
          .flatMap((value) => value.split(',').map((tag) => tag.trim()).filter(Boolean))
        const r = await listNavigation(config, {
          page,
          pageSize,
          query: url.searchParams.get('q') ?? url.searchParams.get('query') ?? undefined,
          folder: url.searchParams.get('folder') ?? url.searchParams.get('folder_id') ?? undefined,
          tags,
          status: url.searchParams.get('status') ?? undefined,
          recentDays,
        })
        if (!r.ok) return sendJson(res, 502, { error: 'library_unavailable', detail: 'library_list_failed' })
        return sendJson(res, 200, navigationList(r.json, page, pageSize))
      }
      if (req.method !== 'POST') return sendJson(res, 405, { error: 'method_not_allowed' })
      const body = await readJsonBody(req, 1 * 1024 * 1024)
      const r = await engineLibraryIngest(config, body.metadata && typeof body.metadata === 'object' ? body.metadata : body)
      if (!r.ok || !r.json) return sendJson(res, 502, { error: 'library_ingest_failed', detail: 'engine_rejected_request' })
      const paperId = String(r.json.paper_id ?? '')
      if (paperId && isPaperId(paperId)) {
        sendJson(res, 200, { local: r.json, paper_id: paperId, derived: 'pending' })
        scheduleDerived(paperId)
        return
      }
      sendJson(res, 200, { local: r.json, derived: 'pending' })
    } catch (error) {
      const detail = error instanceof Error && error.message === 'body_too_large' ? 'body_too_large' : 'invalid_request'
      sendJson(res, detail === 'body_too_large' ? 413 : 400, { error: detail })
    }
  })

  exact('/sr/api/folders', async (req, res) => {
    try {
      if (req.method === 'GET') {
        const r = await engineFolderManage(config, ['folder-list'])
        if (!r.ok) return sendJson(res, 502, { error: 'folders_unavailable', detail: 'folder_list_failed' })
        return sendJson(res, 200, r.json ?? [])
      }
      if (req.method !== 'POST') return sendJson(res, 405, { error: 'method_not_allowed' })
      const body = await readJsonBody(req, 1 * 1024 * 1024)
      const action = String(body.action ?? '')
      const args = action === 'create' && typeof body.name === 'string'
        ? ['folder-create', '--name', body.name]
        : action === 'rename' && typeof body.folder_id === 'string' && typeof body.name === 'string'
          ? ['folder-rename', '--folder-id', body.folder_id, '--name', body.name]
          : []
      if (!args.length) return sendJson(res, 400, { error: 'invalid_folder_request' })
      const r = await engineFolderManage(config, args)
      if (!r.ok) return sendJson(res, 502, { error: 'folder_operation_failed', detail: 'engine_rejected_request' })
      sendJson(res, 200, r.json ?? {})
    } catch (error) {
      sendJson(res, error instanceof Error && error.message === 'body_too_large' ? 413 : 400, { error: error instanceof Error && error.message === 'body_too_large' ? 'body_too_large' : 'invalid_request' })
    }
  })

  exact('/sr/api/batch', async (req, res) => {
    if (req.method !== 'POST') return sendJson(res, 405, { error: 'method_not_allowed' })
    try {
      const body = await readJsonBody(req, 1 * 1024 * 1024)
      const action = typeof body.action === 'string' ? body.action : ''
      const selection = Array.isArray(body.selection) ? body.selection : []
      if (!BATCH_ACTIONS.has(action)) return sendJson(res, 400, { error: 'invalid_batch_action' })
      if (!selection.length || selection.some((id) => typeof id !== 'string' || !isPaperId(id))) {
        return sendJson(res, 400, { error: 'invalid_selection' })
      }
      if (hasClientFeishuUrl(body.payload)) return sendJson(res, 400, { error: 'client_feishu_url_forbidden' })
      const request = {
        action,
        selection,
        payload: body.payload && typeof body.payload === 'object' ? body.payload : {},
      }
      const result = await submitBatch(config, request)
      if (!result.ok || !result.json) return sendJson(res, 502, { error: 'batch_unavailable', detail: 'engine_rejected_request' })
      return sendJson(res, 200, withoutSensitiveFields(result.json))
    } catch (error) {
      const tooLarge = error instanceof Error && error.message === 'body_too_large'
      return sendJson(res, tooLarge ? 413 : 400, { error: tooLarge ? 'body_too_large' : 'invalid_request' })
    }
  })

  prefix('/sr/api/abstract', async (req, res) => {
    const id = decodeURIComponent((req.url ?? '').slice('/sr/api/abstract'.length)).split('/').filter(Boolean)[0] ?? ''
    if (!isPaperId(id)) return sendJson(res, 404, { error: 'bad_paper_id' })
    if (req.method !== 'GET') return sendJson(res, 405, { error: 'method_not_allowed' })
    try {
      const r = await engineLibraryItem(config, id)
      const item = r.json
      if (!r.ok || !item || typeof item.abstract_status !== 'string') {
        return sendJson(res, 502, { error: 'abstract_unavailable', detail: 'library_item_failed' })
      }
      sendJson(res, 200, {
        paper_id: id,
        abstract_en: item.abstract_en ?? null,
        abstract_zh: item.abstract_zh ?? null,
        status: item.abstract_status,
        active_job_id: item.active_job_id ?? null,
        last_error: item.last_error ?? null,
      })
    } catch {
      sendJson(res, 502, { error: 'abstract_unavailable', detail: 'library_item_failed' })
    }
  })

  // ── 文献库列表（富化：每篇并入 job.json 实时状态）────────────────────
  exact('/sr/api/papers', async (_req, res) => {
    const r = await engineList(config)
    if (!r.ok) return sendJson(res, 500, { error: r.stderr || 'list_failed' })
    const papers = (r.json as Array<Record<string, unknown>> | null) ?? []
    const enriched = []
    for (const p of papers) {
      const pid = String(p.paper_id ?? '')
      const jobRaw = await readOrNull(join(paperRoot(pid), 'job.json'))
      if (jobRaw) {
        try {
          const job = JSON.parse(jobRaw)
          p.status = job.status ?? p.status
          p.job_status = job.status ?? null
        } catch { /* 保留库状态 */ }
      }
      enriched.push(p)
    }
    sendJson(res, 200, { papers: enriched })
  })

  // ── 新建论文（添加文献）─────────────────────────────────────────────
  exact('/sr/api/paper', async (req, res) => {
    if (req.method !== 'POST') return sendJson(res, 405, { error: 'method_not_allowed' })
    try {
      const body = await readJsonBody(req)
      const title = String(body.title ?? '').trim()
      if (!title) return sendJson(res, 400, { error: 'title_required' })
      const pendingDir = join(dataRoot(), '.pending')
      await mkdir(pendingDir, { recursive: true })
      const meta: Record<string, unknown> = {
        title,
        authors: Array.isArray(body.authors) ? (body.authors as string[]) : [],
        doi: typeof body.doi === 'string' && body.doi.trim() ? body.doi.trim() : null,
        pmid: typeof body.pmid === 'string' && body.pmid.trim() ? body.pmid.trim() : null,
        year: typeof body.year === 'number' ? body.year : null,
        journal: typeof body.journal === 'string' && body.journal.trim() ? body.journal.trim() : null,
        zotero_key: null,
      }
      const digest = createHash('sha256').update(JSON.stringify(meta)).digest('hex').slice(0, 12)
      const staging = join(pendingDir, 'meta_' + digest + '.json')
      await writeFile(staging + '.tmp', JSON.stringify(meta, null, 2), 'utf8')
      await rename(staging + '.tmp', staging)
      const init = await engineInit(config, staging)
      if (!init.ok || !init.json) return sendJson(res, 500, { error: init.stderr || 'init_failed' })
      const paperId = String(init.json.paper_id ?? '')
      const check = await engineCheckItem(config, join(paperRoot(paperId), 'metadata.json'))
      const d = (check.json?.detail ?? {}) as Record<string, unknown>
      sendJson(res, 200, { paper_id: paperId, dedupe: String(d.dedupe ?? 'none') })
    } catch (e) {
      sendJson(res, 400, { error: (e as Error).message })
    }
  })

  // ── 论文详情与动作 ──────────────────────────────────────────────────
  prefix('/sr/api/paper', async (req, res) => {
    const parts = parsePaperRoute(req.url ?? '', '/sr/api/paper')
    if (!parts) return sendJson(res, 404, { error: 'not_found' })
    const id = parts[0] ?? ''
    const action = parts[1] ?? ''
    if (!isPaperId(id)) return sendJson(res, 404, { error: 'bad_paper_id' })
    if (parts.length > 2 && action !== 'assets' && action !== 'exports') return sendJson(res, 404, { error: 'not_found' })
    const metaPath = join(paperRoot(id), 'metadata.json')
    const root = paperRoot(id)

    try {
      if (req.method === 'GET' && !action) {
        const itemRaw = await readOrNull(metaPath)
        const metadata = itemRaw ? JSON.parse(itemRaw) : null
        const libraryItem = await engineLibraryItem(config, id)
        const engineItem = libraryItem.ok && libraryItem.json ? safeLibraryItem(libraryItem.json) as Record<string, unknown> : null
        const item = engineItem ? { ...metadata, ...engineItem } : metadata
        const activeJobId = typeof item?.active_job_id === 'string' && JOB_ID_RE.test(item.active_job_id) ? item.active_job_id : ''
        const activeJob = activeJobId ? await engineJobStatus(config, activeJobId) : null
        const reading = await readOrNull(join(root, 'reading', 'quick_read.md'))
        const outputs: string[] = []
        for (const p of ['reading/quick_read.md']) {
          try { await access(join(root, p)); outputs.push(p) } catch { /* 不存在 */ }
        }
        sendJson(res, 200, { paper_id: id, item, job: activeJob?.json ? withoutSensitiveFields(activeJob.json) : null, reading, outputs })
        return
      }

      if (req.method === 'POST' && action === 'download') {
        const body = await readJsonBody(req)
        const identifier = String(body.identifier ?? '').trim()
        const jobId = String(body.job_id ?? '')
        if (!identifier || !await requirePdfGate(id, jobId)) return sendJson(res, 409, { error: 'pdf_gate_required' })
        const outcome = await fetchPaper(config.scansciExe, identifier, resolveOutputDir(config), config)
        if (outcome.status !== 'success' || !outcome.paper?.pdf_path) return sendJson(res, 502, { error: 'pdf_download_failed', options: ['institution_browser', 'local_pdf'] })
        const attached = await engineAttachAndResumeFullReadPdf(config, id, jobId, outcome.paper.pdf_path)
        if (!attached.ok || !attached.json) return sendJson(res, 502, { error: 'pdf_attach_failed', options: ['institution_browser', 'local_pdf'] })
        sendJson(res, 200, safePdfResult(id, jobId, attached.json, attached.json))
        return
      }

      if (!action && req.method !== 'GET') return sendJson(res, 405, { error: 'method_not_allowed' })

      if (req.method === 'GET' && action === 'abstract') {
        const result = await engineLibraryItem(config, id)
        const item = result.json
        if (!result.ok || !item) {
          return sendJson(res, 502, { error: 'abstract_unavailable', detail: 'library_item_failed' })
        }
        return sendJson(res, 200, {
          paper_id: id,
          abstract_en: safeNullableString(item.abstract_en),
          abstract_zh: safeNullableString(item.abstract_zh),
          status: safeString(item.abstract_status),
          active_job_id: typeof item.active_job_id === 'string' && JOB_ID_RE.test(item.active_job_id) ? item.active_job_id : null,
          last_error: safeError(item.last_error),
        })
      }

      if (req.method === 'GET' && action === 'pdf') {
        const result = await resolveNavigationArtifact(config, id, 'pdf')
        const rel = typeof result.json?.rel_path === 'string' ? result.json.rel_path : ''
        const resolved = artifactPath(root, rel, 'pdf')
        if (!result.ok || !resolved) return sendJson(res, 404, { error: 'pdf_not_ready' })
        if (await hasSymlink(root, resolved)) return sendJson(res, 409, { error: 'pdf_invalid' })
        const bytes = await readFile(resolved).catch(() => null)
        const expectedSha = typeof result.json?.sha256 === 'string' ? result.json.sha256 : ''
        if (!bytes || !/^[0-9a-f]{64}$/.test(expectedSha) || sha256(bytes) !== expectedSha) return sendJson(res, 409, { error: 'pdf_sha_mismatch' })
        res.writeHead(200, { 'Content-Type': 'application/pdf', 'Content-Length': String(bytes.length) })
        res.end(bytes)
        return
      }

      if (req.method === 'POST' && action === 'attach') {
        const body = await readJsonBody(req)
        const jobId = String(body.job_id ?? '')
        if (!await requirePdfGate(id, jobId)) return sendJson(res, 409, { error: 'pdf_gate_required' })
        const b64 = String(body.pdf_b64 ?? '')
        if (!b64) return sendJson(res, 400, { error: 'pdf_b64_required' })
        const bytes = Buffer.from(b64, 'base64')
        if (bytes.length < 1000) return sendJson(res, 400, { error: 'not_a_pdf' })
        const uploads = join(dataRoot(), '.uploads')
        await mkdir(uploads, { recursive: true })
        const file = join(uploads, id + '-' + randomUUID() + '.pdf')
        await writeFile(file, bytes)
        try {
          const r = await engineAttachAndResumeFullReadPdf(config, id, jobId, file)
          if (!r.ok || !r.json) return sendJson(res, 502, { error: 'pdf_attach_failed' })
          sendJson(res, 200, safePdfResult(id, jobId, r.json, r.json))
        } finally {
          await import('node:fs/promises').then(({ unlink }) => unlink(file).catch(() => {}))
        }
        return
      }

      if (req.method === 'POST' && action === 'start') {
        const r = await engineStartFullRead(config, id)
        if (!r.ok || !r.json) return sendJson(res, 502, { error: 'full_read_start_failed' })
        return sendJson(res, 200, { parent_job_id: String(r.json.parent_job_id ?? '') })
      }

      if (req.method === 'POST' && action === 'full-read') {
        try { await readJsonBody(req, 1 * 1024 * 1024) } catch (error) {
          const tooLarge = error instanceof Error && error.message === 'body_too_large'
          return sendJson(res, tooLarge ? 413 : 400, { error: tooLarge ? 'body_too_large' : 'invalid_request' })
        }
        const r = await engineStartFullRead(config, id)
        if (!r.ok || !r.json) return sendJson(res, 502, { error: 'full_read_start_failed' })
        return sendJson(res, 200, { parent_job_id: String(r.json.parent_job_id ?? '') })
      }

      if (req.method === 'POST' && action === 'attach-pdf') {
        const body = await readJsonBody(req, 8 * 1024 * 1024)
        const jobId = String(body.job_id ?? '')
        const pdfPath = typeof body.pdf === 'string' ? body.pdf : ''
        if (!isAbsolute(pdfPath) || !/\.pdf$/i.test(pdfPath)) return sendJson(res, 400, { error: 'absolute_pdf_required' })
        if (!await requirePdfGate(id, jobId)) return sendJson(res, 409, { error: 'pdf_gate_required' })
        const r = await engineAttachAndResumeFullReadPdf(config, id, jobId, pdfPath)
        if (!r.ok || !r.json) return sendJson(res, 502, { error: 'pdf_attach_failed' })
        return sendJson(res, 200, safePdfResult(id, jobId, r.json, r.json))
      }

      if (req.method === 'POST' && action === 'export') {
        const r = await engineExportAssets(config, id)
        return sendJson(res, r.ok ? 200 : 502, r.json ?? { error: 'asset_export_failed' })
      }

      if (req.method === 'POST' && action === 'export-assets') {
        try { await readJsonBody(req, 1 * 1024 * 1024) } catch (error) {
          const tooLarge = error instanceof Error && error.message === 'body_too_large'
          return sendJson(res, tooLarge ? 413 : 400, { error: tooLarge ? 'body_too_large' : 'invalid_request' })
        }
        const r = await engineExportAssets(config, id)
        return sendJson(res, r.ok ? 200 : 502, r.json ?? { error: 'asset_export_failed' })
      }

      if (req.method === 'GET' && action === 'reader') {
        const r = await engineResolveArtifact(config, id, 'reader')
        const rel = typeof r.json?.rel_path === 'string' ? r.json.rel_path : ''
        const resolved = artifactPath(root, rel, 'reader')
        if (!r.ok || !resolved) return sendJson(res, 404, { error: 'reader_not_ready' })
        if (await hasSymlink(root, resolved)) return sendJson(res, 409, { error: 'reader_invalid' })
        const bytes = await readFile(resolved).catch(() => null)
        const artifactJson = r.json ?? {}
        const manifest = artifactJson.manifest as Record<string, unknown> | undefined
        const expectedSha = typeof artifactJson.sha256 === 'string' ? artifactJson.sha256 : typeof manifest?.reader_sha256 === 'string' ? manifest.reader_sha256 : ''
        if (!bytes || !/^[0-9a-f]{64}$/.test(expectedSha) || sha256(bytes) !== expectedSha) return sendJson(res, 409, { error: 'reader_sha_mismatch' })
        return sendText(res, 200, bytes.toString('utf8'), 'text/html; charset=utf-8')
      }

      if (req.method === 'GET' && (action === 'assets' || action === 'exports')) {
        const r = await engineResolveArtifact(config, id, 'exports')
        const rel = typeof r.json?.rel_path === 'string' ? r.json.rel_path : ''
        const exportsRoot = artifactPath(root, rel, 'exports')
        const manifest = r.json?.manifest
        if (!r.ok || !exportsRoot || await hasSymlink(root, exportsRoot) || !manifest || typeof manifest !== 'object') return sendJson(res, 404, { error: 'assets_not_ready' })
        const requested = parts.slice(2).join('/')
        const rows = Array.isArray((manifest as Record<string, unknown>).assets) ? (manifest as { assets: Array<Record<string, unknown>> }).assets : []
        if (!requested) return sendJson(res, 200, {
          ...(manifest as Record<string, unknown>),
          exports_path: exportsRoot,
          figures: rows.filter((row) => row.kind === 'figure' || (typeof row.export_path === 'string' && row.export_path.startsWith('figures/'))).length,
          tables: rows.filter((row) => row.kind === 'table' || (typeof row.export_path === 'string' && row.export_path.startsWith('tables/'))).length,
        })
        const match = rows.flatMap((row) => [
          { path: row.export_path, sha: row.export_sha256 },
          { path: row.csv_path, sha: row.csv_sha256 },
        ]).find((entry) => entry.path === requested)
        if (!match || typeof match.path !== 'string' || typeof match.sha !== 'string' || !/^[0-9a-f]{64}$/.test(match.sha) || !/^(?:figures|tables)\/[A-Za-z0-9_.-]+$/.test(match.path)) return sendJson(res, 404, { error: 'asset_not_found' })
        const assetPath = join(exportsRoot, ...match.path.split('/'))
        if (await hasSymlink(exportsRoot, assetPath)) return sendJson(res, 409, { error: 'asset_invalid' })
        const bytes = await readFile(assetPath)
        if (sha256(bytes) !== match.sha) return sendJson(res, 409, { error: 'asset_sha_mismatch' })
        res.writeHead(200, { 'Content-Type': match.path.endsWith('.csv') ? 'text/csv; charset=utf-8' : 'image/png' })
        res.end(bytes)
        return
      }

      if (req.method === 'POST' && action === 'parse') {
        const r = await engineParse(config, metaPath)
        sendJson(res, r.ok ? 200 : 500, r.json ?? { error: r.stderr || 'parse_failed' })
        return
      }

      if (req.method === 'POST' && action === 'quick-read') {
        const body = await readJsonBody(req)
        const ctxText = typeof body.project_context === 'string' ? body.project_context : undefined
        const r = await engineQuickRead(config, metaPath, ctxText)
        sendJson(res, r.ok ? 200 : 500, r.json ?? { error: r.stderr || 'quick_read_failed' })
        return
      }

      const knownActions = new Set(['abstract', 'pdf', 'assets', 'exports', 'reader', 'full-read', 'attach-pdf', 'export-assets', 'download', 'attach', 'start', 'export', 'parse', 'quick-read'])
      sendJson(res, knownActions.has(action) ? 405 : 404, { error: knownActions.has(action) ? 'method_not_allowed' : 'not_found' })
    } catch {
      sendJson(res, 500, { error: 'internal_error' })
    }
  })

  // ── 任务状态 ────────────────────────────────────────────────────────
  // exact 兜底：无 job id 时 404；真正匹配走 prefix（/sr/api/job/<id>）
  exact('/sr/api/job', async (req, res) => {
    sendJson(res, 404, { error: 'bad_job_id' })
  })
  prefix('/sr/api/job', async (req, res) => {
    const parts = parsePaperRoute(req.url ?? '', '/sr/api/job')
    if (!parts || parts.length > 2 || (parts.length === 2 && parts[1] !== 'continue')) return sendJson(res, 404, { error: 'bad_job_id' })
    const id = parts[0] ?? ''
    if (!JOB_ID_RE.test(id)) return sendJson(res, 404, { error: 'bad_job_id' })
    if (parts[1] === 'continue' && req.method !== 'POST') return sendJson(res, 405, { error: 'method_not_allowed' })
    if (req.method === 'POST' && parts[1] === 'continue') {
      try {
        const body = await readJsonBody(req, 8 * 1024 * 1024)
        const r = await engineContinueFullRead(config, id, body)
        return sendJson(res, r.ok && r.json ? 200 : 409, r.ok && r.json ? withoutSensitiveFields(r.json) : { error: 'full_read_continue_failed' })
      } catch {
        return sendJson(res, 400, { error: 'invalid_request' })
      }
    }
    if (req.method !== 'GET') return sendJson(res, 405, { error: 'method_not_allowed' })
    const r = await engineJobStatus(config, id)
    sendJson(res, r.ok && r.json ? 200 : 502, r.ok && r.json ? withoutSensitiveFields(r.json) : { error: 'job_unavailable', detail: 'engine_rejected_request' })
  })

  // ── 浅读笔记（HTML 呈现）───────────────────────────────────────────
  prefix('/sr/reading', async (_req, res) => {
    const id = decodeURIComponent((_req.url ?? '').slice('/sr/reading'.length)).split('/').filter(Boolean)[0] ?? ''
    if (!isPaperId(id)) return sendText(res, 404, 'not found')
    const text = await readOrNull(join(paperRoot(id), 'reading', 'quick_read.md'))
    if (text === null) return sendText(res, 404, 'no quick read yet')
    const html = '<!doctype html><meta charset="utf-8"><title>' + id + '</title><body style="max-width:860px;margin:24px auto;font-family:system-ui;line-height:1.7"><pre style="white-space:pre-wrap">' + escapeHtml(text) + '</pre></body>'
    sendText(res, 200, html, 'text/html; charset=utf-8')
  })

  // ── 精读 HTML（Phase 3 产物，存在即服务）──────────────────────────
  prefix('/sr/reader', async (_req, res) => {
    if (_req.method !== 'GET' && _req.method !== 'HEAD') return sendText(res, 405, 'method not allowed')
    const routeParts = parsePaperRoute(_req.url ?? '', '/sr/reader')
    if (!routeParts || routeParts.length !== 1) return sendText(res, 404, 'not found')
    const id = routeParts[0]
    if (!isPaperId(id)) return sendText(res, 404, 'not found')
    try {
      const artifact = await engineResolveArtifact(config, id, 'reader')
      const rel = typeof artifact.json?.rel_path === 'string' ? artifact.json.rel_path : ''
      const resolved = artifactPath(paperRoot(id), rel, 'reader')
      if (!artifact.ok || !resolved) throw new Error('reader_not_ready')
      if (await hasSymlink(paperRoot(id), resolved)) throw new Error('reader_invalid')
      const bytes = await readFile(resolved)
      const artifactJson = artifact.json ?? {}
      const manifest = artifactJson.manifest as Record<string, unknown> | undefined
      const expectedSha = typeof artifactJson.sha256 === 'string' ? artifactJson.sha256 : typeof manifest?.reader_sha256 === 'string' ? manifest.reader_sha256 : ''
      if (!/^[0-9a-f]{64}$/.test(expectedSha) || sha256(bytes) !== expectedSha) throw new Error('reader_sha_mismatch')
      const html = bytes.toString('utf8')
      sendText(res, 200, _req.method === 'HEAD' ? '' : html, 'text/html; charset=utf-8')
    } catch {
      sendText(res, 404, 'no full read yet')
    }
  })

  // 仪表盘（兜底入口）
  exact('/sr', async (_req, res) => {
    sendText(res, 200, '<!doctype html><meta charset="utf-8"><title>文献库</title><body><h1>文献库</h1><p>请在对话栏打开【文献】标签页。</p></body>', 'text/html; charset=utf-8')
  })
}
