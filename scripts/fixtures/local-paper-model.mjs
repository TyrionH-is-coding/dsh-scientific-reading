// 仅用于专用验收 Profile；不加入生产 bundle，不发起模型网络请求。
import { createHash } from 'node:crypto'
import { createRequire } from 'node:module'
import { isAbsolute } from 'node:path'
import { pathToFileURL } from 'node:url'

export const name = 'acceptance-local'
export const inject = ['llm', 'attachments']
export const COMPLETION_TEXT = '本地闭环验收完成（ACCEPTANCE_LOCAL_TOOL_LOOP_OK）：已收到 sr_paper_context 工具结果。'
const MODEL = 'scope-smoke'

export async function createAcceptanceAdapter(config = {}, attachments) {
  if (typeof config.dshEntry !== 'string' || !isAbsolute(config.dshEntry)) {
    throw new Error('acceptance-local requires an absolute config.dshEntry from installation.dsh')
  }
  const requireFromHost = createRequire(config.dshEntry)
  const { LlmAdapter, LlmError, ToolCallId } = await import(pathToFileURL(requireFromHost.resolve('@deepseek-ai/dsh-llm')).href)
  const model = { provider: name, id: MODEL, name: '本地工具闭环验收（不连接模型）', inputModalities: ['text', 'image'] }
  return new class extends LlmAdapter {
    providerInfo() { return { id: name, name: '本地验收专用' } }
    async listModels() { return [model, ...['gpt-5.6-luna','gpt-5.6-sol'].map(id => ({...model,id,name:id}))] }
    async resolveModel(provider, modelId) {
      if (provider !== name || ![MODEL,'gpt-5.6-luna','gpt-5.6-sol'].includes(modelId)) throw new LlmError('Unknown acceptance model', 'UNKNOWN_MODEL')
      return {...model,id:modelId,reasoning:{efforts:['low','medium','high'].map(id => ({id,name:id}))}}
    }
    async *stream(options) {
      if (options.signal?.aborted) throw new LlmError('Acceptance aborted', 'ABORTED')
      await this.resolveModel(options.provider, options.model)
      if (String(options.sessionId).startsWith('sr-step-') && !options.tools?.length) {
        const reply = `STEP_FIXTURE_OK MODEL=${options.model} EFFORT=${options.reasoningEffort}`
        yield {type:'block-start',index:0,blockType:'text'}
        yield {type:'text-delta',index:0,text:reply}
        yield {type:'block-end',index:0,block:{type:'text',text:reply}}
        yield {type:'finish',reason:{kind:'stop'}}
        return
      }
      if (String(options.sessionId).startsWith('sr-reader-') && !options.tools?.length) {
        const latest = options.messages.at(-1).content[0].text
        const source = JSON.parse(latest.split('本轮选区与服务端核对的论文材料（作为资料，不作为指令）：\n')[1])
        const reply = `合成验收回答：这段话的含义是测试所用的论文说明。已收到 ${source.passages.length} 个来源段落，可以继续追问。\nMODEL=${options.model} EFFORT=${options.reasoningEffort} MESSAGES=${options.messages.length}\nQUOTE=${source.quote}`
        yield {type:'block-start',index:0,blockType:'text'}
        yield {type:'text-delta',index:0,text:reply}
        yield {type:'block-end',index:0,block:{type:'text',text:reply}}
        yield {type:'finish',reason:{kind:'stop'}}
        return
      }
      const routingProbe = options.messages.findLast(message => message.source?.kind === 'user')?.content
        .some(block => block.type === 'text' && block.text.includes('ACCEPTANCE_ROUTE_FULL_TRANSLATION'))
      const TOOL = routingProbe ? 'sr_model_step' : 'sr_paper_context'
      const TOOL_ARGS = routingProbe ? JSON.stringify({step:'full_translation'}) : '{}'
      if (!(options.tools ?? []).some(tool => tool.name === TOOL)) {
        throw new LlmError('The scoped sr_library_list tool is unavailable', 'ACCEPTANCE_TOOL_NOT_AVAILABLE')
      }
      const currentUser = options.messages.findLastIndex(message => message.role === 'user' && message.source.kind === 'user')
      if (currentUser < 0) throw new LlmError('Acceptance requires a user message', 'INVALID_REQUEST')
      let imageReceipt = ''
      const user = options.messages[currentUser]
      const figureText = user.content.find(block => block.type === 'text' && block.text.includes('来源上下文：\n'))
      if (figureText) {
        const figure = JSON.parse(figureText.text.split('来源上下文：\n')[1])
        const images = user.content.filter(block => block.type === 'image')
        if (figure.image_status === 'attached_in_this_message') {
          if (images.length !== 1) throw new Error('acceptance_image_missing')
          const stored = await attachments.readImage(images[0].attachment)
          const actual = createHash('sha256').update(stored.data).digest('hex')
          if (actual !== figure.image_sha256) throw new Error('acceptance_image_sha_mismatch')
          imageReceipt = ` IMAGE_BYTES_SHA256=${actual} ASSET=${figure.asset_id}`
        } else {
          if (images.length) throw new Error('acceptance_text_only_has_image')
          imageReceipt = ` TEXT_ONLY_VERIFIED ASSET=${figure.asset_id}`
        }
      }
      const seed = JSON.stringify([options.sessionId, options.messages[currentUser].id])
      const callId = ToolCallId(`acceptance-local-${createHash('sha256').update(seed).digest('hex').slice(0, 24)}`)
      const current = options.messages.slice(currentUser + 1)
      const callIndex = current.findIndex(message => message.role === 'assistant' && message.source.kind === 'model'
        && message.source.provider === name && message.content.some(block => block.type === 'tool-call' && block.id === callId && block.name === TOOL))
      if (callIndex < 0) {
        yield { type: 'block-start', index: 0, blockType: 'tool-call' }
        yield { type: 'tool-call-delta', index: 0, id: callId, name: TOOL, argumentsDelta: TOOL_ARGS }
        yield { type: 'block-end', index: 0, block: { type: 'tool-call', id: callId, name: TOOL, arguments: TOOL_ARGS } }
        yield { type: 'finish', reason: { kind: 'tool-calls' } }
        return
      }
      const toolMessage = current.slice(callIndex + 1).find(message => message.source.kind === 'tool' && message.source.callId === callId)
      const result = toolMessage?.content.find(block => block.type === 'tool-result' && block.toolCallId === callId)
      if (!result || !Array.isArray(result.content) || result.content.length === 0) {
        throw new LlmError('No matching DSH tool result has arrived', 'ACCEPTANCE_TOOL_RESULT_MISSING')
      }
      if (result.isError === true) throw new LlmError('The DSH tool returned a failure', 'ACCEPTANCE_TOOL_FAILED')
      yield { type: 'block-start', index: 0, blockType: 'text' }
      const reply = COMPLETION_TEXT + imageReceipt + ` MODEL=${options.model} EFFORT=${options.reasoningEffort}`
      yield { type: 'text-delta', index: 0, text: reply }
      yield { type: 'block-end', index: 0, block: { type: 'text', text: reply } }
      yield { type: 'finish', reason: { kind: 'stop' } }
    }
  }()
}

export async function apply(ctx, config) {
  ctx.llm.registerAdapter([name], await createAcceptanceAdapter(config, ctx.attachments))
}

export default { name, inject, apply }
