import type { Context } from 'cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { Config } from './config.js'
import {
  engineReviewConfirm,
  engineReviewContext,
  engineXlsxRefresh,
  runEngine,
} from './cli.js'

type EngineResult = { ok: boolean; json: Record<string, unknown> | null; stderr: string }
type Block = { type: 'text'; text: string }
const text = (value: string): Block[] => [{ type: 'text', text: value }]

export interface ReviewToolDependencies {
  context(config: Config, reviewSessionId: string): Promise<EngineResult>
  confirm(config: Config, reviewSessionId: string, conclusions: unknown[]): Promise<EngineResult>
  refreshXlsx(config: Config): Promise<EngineResult>
  locate(config: Config, input: EvidenceLocateInput): Promise<EngineResult>
  prepareCandidate(config: Config, input: CandidateRebuildInput): Promise<EngineResult>
}

type EvidenceLocateInput = {
  paper_id: string
  block_id: string
  quote: string
  page?: number
}

type CandidateRebuildInput = {
  paper_id: string
  target_root: string
}

const defaultDependencies: ReviewToolDependencies = {
  context: engineReviewContext,
  confirm: engineReviewConfirm,
  refreshXlsx: engineXlsxRefresh,
  async locate(config, input) {
    const args = [
      'evidence-locate',
      '--paper-id', input.paper_id,
      '--block-id', input.block_id,
      '--quote', input.quote,
    ]
    if (input.page !== undefined) args.push('--page', String(input.page))
    return runEngine(config, args)
  },
  async prepareCandidate(config, input) {
    return runEngine(
      config,
      [
        'candidate-rebuild',
        '--paper-id', input.paper_id,
        '--target-root', input.target_root,
      ],
      { timeoutMs: 120_000 },
    )
  },
}

function currentReviewSessionId(exec: { agent?: { id?: unknown } }): string {
  const id = exec.agent?.id
  if (typeof id !== 'string' || !id.trim()) throw new Error('review_agent_required')
  return id
}

export function registerReviewTools(
  ctx: Context,
  config: Config,
  dependencies: ReviewToolDependencies = defaultDependencies,
): void {
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_evidence_locate',
    description: '为已验证的当前论文原文块生成版本绑定定位。必须给出明确 block_id 和不超过 500 个 Unicode 字符的逐字短引文；定位只证明来源位置。',
    parameters: {
      paper_id: { type: 'string', required: true },
      block_id: { type: 'string', required: true },
      quote: { type: 'string', required: true },
      page: { type: 'number' },
    },
    output: {
      schema: { type: 'json' },
      render: (_args: unknown, value: unknown) => text('证据定位：' + JSON.stringify(value)),
    },
    async execute(args: EvidenceLocateInput) {
      const result = await dependencies.locate(config, args)
      if (!result.ok || !result.json) throw new Error(result.stderr || 'evidence_locate_failed')
      return result.json as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_evidence_locate')

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_candidate_rebuild',
    description: '从已验证缓存 raw 在数据根外的新或空目录准备可审核候选计划；只分类精确复用、待翻译和待审核项，不自动翻译、复核或发布。',
    parameters: {
      paper_id: { type: 'string', required: true },
      target_root: { type: 'string', required: true },
    },
    output: {
      schema: { type: 'json' },
      render: (_args: unknown, value: unknown) => text('候选重建：' + JSON.stringify(value)),
    },
    async execute(args: CandidateRebuildInput) {
      const result = await dependencies.prepareCandidate(config, args)
      if (!result.ok || !result.json) throw new Error(result.stderr || 'candidate_rebuild_failed')
      return result.json as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_candidate_rebuild')

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_review_context',
    description: '读取当前论文整理子会话绑定的论文资产和已确认结论；会话身份由 DSH 注入，不接受外部指定。',
    parameters: {},
    output: {
      schema: { type: 'json' },
      render: (_args: unknown, value: unknown) => text('整理上下文：' + JSON.stringify(value)),
    },
    async execute(_args, exec) {
      const result = await dependencies.context(config, currentReviewSessionId(exec))
      if (!result.ok || !result.json) throw new Error(result.stderr || 'review_context_failed')
      return result.json as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_review_context')

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'sr_review_confirm',
    description: '仅在用户明确确认当前版本需要入库后追加保存结论。论文来源必须提交预先取得并复核通过的完整定位；定位只证明原文位置，不能证明结论的科学有效性。',
    parameters: {
      conclusions: {
        type: 'array',
        required: true,
        items: {
          type: 'object',
          properties: {
            conclusion_type: { type: 'string', required: true },
            conclusion_text: { type: 'string', required: true },
            basis: {
              type: 'string',
              enum: ['paper', 'personal', 'inference', 'question', 'legacy'],
            },
            evidence: {
              type: 'object',
              properties: {
                contract: { type: 'string', required: true },
                paper_id: { type: 'string', required: true },
                source_sha256: { type: 'string', required: true },
                generation: { type: 'string', required: true },
                source_map_sha256: { type: 'string', required: true },
                block_id: { type: 'string', required: true },
                page: { type: 'number', required: true },
                quote: { type: 'string', required: true },
              },
              additionalProperties: false,
            },
            evidence_locator: { type: 'string' },
          },
          additionalProperties: false,
        },
      },
    },
    output: {
      schema: { type: 'json' },
      render: (_args: unknown, value: unknown) => text('整理入库：' + JSON.stringify(value)),
    },
    async execute(args: { conclusions: unknown[] }, exec) {
      const result = await dependencies.confirm(
        config,
        currentReviewSessionId(exec),
        args.conclusions,
      )
      if (!result.ok || !result.json) throw new Error(result.stderr || 'review_confirm_failed')
      const xlsx = await dependencies.refreshXlsx(config)
      return {
        ...result.json,
        xlsx: xlsx.json ?? { status: 'failed', error: xlsx.stderr || 'xlsx_refresh_failed' },
      } as never
    },
  })), '@dsh-external/dsh-scientific-reading: sr_review_confirm')
}
