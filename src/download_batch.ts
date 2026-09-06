import { randomUUID } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import type { Config } from './config.js'
import { resolveDataRoot, resolveOutputDir } from './config.js'
import { engineAttachLibraryPdf, engineJson, engineLibraryItem, engineResolveArtifact, fetchPaper } from './cli.js'

type FetchResult = { status: string; pdfPath?: string }
type Child = { paperId: string; status: string; phase?: string }
type DownloadJob = Record<string, unknown>
export type DownloadDeps = {
  loadPaper(id: string): Promise<Record<string, unknown> | undefined>
  hasPdf(id: string): Promise<boolean>
  directFetch(id: string, paper: Record<string, unknown>): Promise<FetchResult>
  attachPdf(id: string, path: string): Promise<{ status: string }>
}

function summarize(children: Child[]) {
  const summary: Record<string, number> = { total: children.length, completed: 0, skipped_existing: 0, anti_automation_challenge: 0, manual_required: 0, failed: 0 }
  for (const child of children) summary[child.status] = (summary[child.status] ?? 0) + 1
  return summary
}

function ownerIsAlive(value: unknown): boolean {
  if (!Number.isInteger(value) || Number(value) <= 0) return false
  try {
    process.kill(Number(value), 0)
    return true
  } catch (error) {
    return error instanceof Error && 'code' in error && error.code === 'EPERM'
  }
}

function needsUser(value: DownloadJob): boolean {
  if (value.status === 'failed') return true
  if (value.status !== 'completed') return false
  const summary = value.summary
  if (!summary || typeof summary !== 'object' || Array.isArray(summary)) return false
  return ['failed', 'manual_required', 'anti_automation_challenge']
    .some((key) => Number((summary as Record<string, unknown>)[key] ?? 0) > 0)
}

function normalizeJob(jobId: string, value: DownloadJob): DownloadJob {
  const status = typeof value.status === 'string' ? value.status : 'failed'
  return {
    ...value,
    job_id: jobId,
    parent_job_id: jobId,
    status,
    next_action: status === 'queued' || status === 'running' ? 'poll' : needsUser({ ...value, status }) ? 'user' : 'done',
  }
}

export async function runDownloadBatch(selection: string[], deps: DownloadDeps) {
  if (!Array.isArray(selection) || selection.length === 0) throw new Error('download_batch_selection_required')
  if (selection.length > 100) throw new Error('download_batch_too_large')
  const ids = [...new Set(selection)]
  const papers = new Map<string, Record<string, unknown>>()
  const children = new Map<string, Child>()
  const directCandidates: string[] = []
  for (const id of ids) {
    try {
      const paper = await deps.loadPaper(id)
      if (!paper) { children.set(id, { paperId: id, status: 'failed' }); continue }
      papers.set(id, paper)
      if (await deps.hasPdf(id)) children.set(id, { paperId: id, status: 'skipped_existing' })
      else directCandidates.push(id)
    } catch { children.set(id, { paperId: id, status: 'failed' }) }
  }
  await Promise.all(directCandidates.map(async (id) => {
    try {
      const result = await deps.directFetch(id, papers.get(id)!)
      if (result.status === 'completed' && result.pdfPath) {
        const attached = await deps.attachPdf(id, result.pdfPath)
        children.set(id, { paperId: id, status: attached.status === 'completed' ? 'completed' : 'failed', phase: 'direct' })
      } else children.set(id, { paperId: id, status: 'manual_required', phase: 'oa' })
    } catch { children.set(id, { paperId: id, status: 'manual_required', phase: 'oa' }) }
  }))
  const ordered = ids.map((id) => children.get(id) ?? { paperId: id, status: 'failed' })
  return {
    status: 'completed',
    children: ordered,
    summary: summarize(ordered),
    challengePaperIds: ordered.filter((child) => child.status === 'anti_automation_challenge').map((child) => child.paperId),
  }
}

function identifier(paper: Record<string, unknown>): string {
  for (const key of ['doi', 'pmid', 'source_url', 'title']) {
    if (typeof paper[key] === 'string' && paper[key].trim()) return paper[key].trim()
  }
  return ''
}

async function persist(config: Config, jobId: string, value: unknown): Promise<void> {
  const result = await engineJson(config, ['download-job-save', '--job-id', jobId], value)
  if (!result.ok || result.json?.status !== 'saved' || result.json.job_id !== jobId) {
    throw new Error('download_job_save_failed')
  }
}

export async function submitDownloadBatch(config: Config, selection: string[]) {
  if (!selection.length || selection.length > 100) throw new Error(selection.length ? 'download_batch_too_large' : 'download_batch_selection_required')
  const jobId = 'job_' + randomUUID().replaceAll('-', '').slice(0, 16)
  const dataRoot = resolveDataRoot(config)
  const activeState = (status: 'queued' | 'running') => normalizeJob(jobId, {
    status,
    selection,
    owner_pid: process.pid,
    updated_at: new Date().toISOString(),
  })
  await persist(config, jobId, activeState('queued'))
  queueMicrotask(() => {
    void (async () => {
      await persist(config, jobId, activeState('running'))
      const result = await runDownloadBatch(selection, {
        async loadPaper(id) {
          const result = await engineLibraryItem(config, id)
          return result.ok && result.json ? result.json : undefined
        },
        async hasPdf(id) { return (await engineResolveArtifact(config, id, 'pdf')).ok },
        async directFetch(id, paper) {
          const value = identifier(paper)
          if (!value) return { status: 'remaining' }
          const output = join(resolveOutputDir(config), '.batch', jobId, id)
          const outcome = await fetchPaper(config.scansciExe, value, output, config)
          return outcome.status === 'success' && outcome.paper?.pdf_path ? { status: 'completed', pdfPath: outcome.paper.pdf_path } : { status: 'remaining' }
        },
        async attachPdf(id, path) {
          const result = await engineAttachLibraryPdf(config, id, path)
          return { status: result.ok ? 'completed' : 'failed' }
        },
      })
      await persist(config, jobId, normalizeJob(jobId, {
        ...result,
        selection,
        owner_pid: process.pid,
        updated_at: new Date().toISOString(),
      }))
    })().catch(async () => {
      await persist(config, jobId, normalizeJob(jobId, {
        status: 'failed',
        selection,
        owner_pid: process.pid,
        updated_at: new Date().toISOString(),
      })).catch(() => {})
    })
  })
  return { parent_job_id: jobId, status: 'queued' }
}

const pendingJobReads = new Map<string, Promise<DownloadJob | null>>()

export function readDownloadJob(config: Config, jobId: string): Promise<DownloadJob | null> {
  if (!/^job_[0-9a-f]{16}$/.test(jobId)) return Promise.resolve(null)
  const dataRoot = resolveDataRoot(config)
  const key = join(dataRoot, 'jobs', 'downloads', jobId + '.json')
  const pending = pendingJobReads.get(key)
  if (pending) return pending
  const task = readDownloadJobFile(config, jobId).finally(() => { pendingJobReads.delete(key) })
  pendingJobReads.set(key, task)
  return task
}

async function readDownloadJobFile(config: Config, jobId: string): Promise<DownloadJob | null> {
  const dataRoot = resolveDataRoot(config)
  let current: DownloadJob
  try {
    const value = JSON.parse(await readFile(join(dataRoot, 'jobs', 'downloads', jobId + '.json'), 'utf8'))
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null
    current = value as DownloadJob
  } catch { return null }
  if ((current.status === 'queued' || current.status === 'running') && !ownerIsAlive(current.owner_pid)) {
    const failed = normalizeJob(jobId, {
      ...current,
      status: 'failed',
      updated_at: new Date().toISOString(),
      detail: {
        reason_code: 'download_process_restarted',
        message: 'DSH 已重启，请重新运行 sr_download_papers。',
      },
    })
    await persist(config, jobId, failed)
    return failed
  }
  return normalizeJob(jobId, current)
}
