import type { Context } from 'cordis'
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { Config } from './config.js'
import { engineJson } from './cli.js'
import { isPaperId } from './papers.js'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const pluginVersion = require('../package.json').version as string
let dshVersion: string | null = null
try { dshVersion = require('@deepseek-ai/dsh/package.json').version } catch { /* 非完整宿主环境不推测版本。 */ }

const JSON_LIMIT = 16 * 1024

function sendJson(res: ServerResponse, status: number, value: unknown): void {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
  res.end(JSON.stringify(value))
}

function sameOrigin(req: IncomingMessage): boolean {
  const origin = req.headers.origin
  const host = req.headers.host
  if (typeof origin !== 'string' || typeof host !== 'string' || req.headers['x-sr-csrf'] !== '1') return false
  try { return new URL(origin).host === host } catch { return false }
}

function readJson(req: IncomingMessage): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = []
    let size = 0
    req.on('data', (chunk: Buffer) => {
      size += chunk.length
      if (size > JSON_LIMIT) { reject(new Error('body_too_large')); req.destroy() } else chunks.push(chunk)
    })
    req.on('end', () => {
      try {
        const parsed = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}')
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('invalid_json')
        resolve(parsed as Record<string, unknown>)
      } catch { reject(new Error('invalid_json')) }
    })
  })
}

export function registerStatusRoutes(ctx: Context, config: Config): void {
  const register = (path: string, handler: (req: IncomingMessage, res: ServerResponse) => Promise<void>) => {
    ctx.effect(() => ctx.webServer.register({ kind: 'exact', path, handler }), 'sr-route:' + path)
  }

  register('/sr/api/settings/status', async (req, res) => {
    if (req.method !== 'GET') return sendJson(res, 405, { error: 'method_not_allowed' })
    const result = await engineJson(config, ['environment-status'])
    if (!result.ok || !result.json) return sendJson(res, 502, { error: 'environment_status_unavailable' })
    sendJson(res, 200, { ...result.json, versions: { plugin: pluginVersion, dsh: dshVersion } })
  })

  register('/sr/api/settings/recheck', async (req, res) => {
    if (req.method !== 'POST') return sendJson(res, 405, { error: 'method_not_allowed' })
    if (!sameOrigin(req)) return sendJson(res, 403, { error: 'request_forbidden' })
    try {
      const body = await readJson(req)
      const targets = Array.isArray(body.targets) ? body.targets.filter((value): value is string => typeof value === 'string') : []
      if (!targets.length || targets.some((target) => !['download', 'mineru_local', 'mineru_api'].includes(target))) return sendJson(res, 400, { error: 'environment_target_invalid' })
      const args = ['environment-recheck']
      for (const target of targets) args.push('--target', target)
      const result = await engineJson(config, args)
      if (!result.ok || !result.json) return sendJson(res, 400, { error: 'environment_recheck_failed' })
      sendJson(res, 200, result.json)
    } catch (error) {
      sendJson(res, error instanceof Error && error.message === 'body_too_large' ? 413 : 400, { error: 'invalid_request' })
    }
  })

  register('/sr/api/settings/mark-presented', async (req, res) => {
    if (req.method !== 'POST') return sendJson(res, 405, { error: 'method_not_allowed' })
    if (!sameOrigin(req)) return sendJson(res, 403, { error: 'request_forbidden' })
    try {
      const body = await readJson(req)
      if (body.version !== 'v1') return sendJson(res, 400, { error: 'onboarding_version_invalid' })
      const result = await engineJson(config, ['environment-mark-presented', '--version', 'v1'])
      if (!result.ok || !result.json) return sendJson(res, 400, { error: 'onboarding_update_failed' })
      sendJson(res, 200, result.json)
    } catch (error) {
      sendJson(res, error instanceof Error && error.message === 'body_too_large' ? 413 : 400, { error: 'invalid_request' })
    }
  })

  register('/sr/api/settings/mineru-key', async (req, res) => {
    if (!['POST', 'DELETE'].includes(req.method ?? '')) return sendJson(res, 405, { error: 'method_not_allowed' })
    if (!sameOrigin(req)) return sendJson(res, 403, { error: 'request_forbidden' })
    try {
      const payload = req.method === 'POST' ? await readJson(req) : {}
      if (req.method === 'POST' && (typeof payload.api_key !== 'string' || !payload.api_key.trim())) {
        return sendJson(res, 400, { error: 'mineru_api_token_required' })
      }
      const command = req.method === 'POST' ? 'mineru-secret-save' : 'mineru-secret-delete'
      const result = await engineJson(config, [command], payload)
      if (!result.ok || !result.json) return sendJson(res, 400, { error: 'mineru_secret_update_failed' })
      const source = typeof result.json.source === 'string' ? result.json.source : 'none'
      sendJson(res, 200, {
        status: result.json.status === 'configured' ? 'configured' : 'not_configured',
        source,
        checked_at: typeof result.json.checked_at === 'string' ? result.json.checked_at : null,
      })
    } catch (error) {
      sendJson(res, error instanceof Error && error.message === 'body_too_large' ? 413 : 400, { error: 'invalid_request' })
    }
  })

  register('/sr/api/excel/locate', async (req, res) => {
    if (req.method !== 'POST') return sendJson(res, 405, { error: 'method_not_allowed' })
    const url = new URL(req.url ?? '/sr/api/excel/locate', 'http://localhost')
    const paperId = url.searchParams.get('paper_id') ?? ''
    if (!isPaperId(paperId) || [...url.searchParams.keys()].some((key) => key !== 'paper_id')) {
      return sendJson(res, 400, { error: 'paper_id_invalid' })
    }
    const result = await engineJson(config, ['xlsx-locate', '--paper-id', paperId])
    if (!result.ok || !result.json) return sendJson(res, 409, { error: 'xlsx_locate_failed' })
    sendJson(res, 200, result.json)
  })
}

