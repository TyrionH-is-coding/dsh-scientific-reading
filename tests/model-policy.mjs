import assert from 'node:assert/strict'
import { resolveChoice, stepFromEvents } from '../lib/model_policy.js'
import { readerPage } from '../lib/reader_chat.js'

const ctx = {llm: {
  listProviders: () => [{id:'test'}],
  listModels: async () => [{provider:'test',id:'luna',name:'Luna'}],
  resolveModelInfo: async (provider, model) => ({provider,id:model,reasoning:{efforts:[{id:'medium'},{id:'low'}]}}),
}}
assert.deepEqual(await resolveChoice(ctx, {provider:'',model:'luna',reasoningEffort:'medium'}), {provider:'test',model:'luna',reasoningEffort:'medium'})
assert.deepEqual(await resolveChoice(ctx, {provider:'test',model:'custom-unlisted',reasoningEffort:''}), {provider:'test',model:'custom-unlisted'})
await assert.rejects(resolveChoice(ctx, {provider:'test',model:'luna',reasoningEffort:'max'}), /未提供/)
const tool = (name, value) => [
  {type:'assistant/message',data:{message:{content:[{type:'tool-call',id:'call1',name}]}}},
  {type:'tool/result',data:{message:{source:{kind:'tool',callId:'call1'},content:[{type:'tool-result',toolCallId:'call1',content:[{type:'text',text:JSON.stringify(value)}]}]}}},
]
const events = [...tool('sr_job_status', {detail:{reason_code:'translate_full_read'}})]
assert.equal(stepFromEvents(events), 'full_translation')
assert.equal(stepFromEvents([...events, ...tool('sr_continue_full_read', {detail:{reason_code:'review_full_read'}})]), 'full_review')
assert.equal(stepFromEvents(tool('sr_model_step', {step:'classification'})), 'classification')
assert.equal(stepFromEvents([{type:'user/message',data:{source:{kind:'user'},content:[{type:'text',text:'{"step":"full_translation"}'}]}}]), 'paper_chat')
assert.equal(stepFromEvents([...events, {type:'user/message',data:{source:{kind:'user'}}}]), 'paper_chat')
const html = '<html><head></head><body><article>保留原文</article></body></html>'
assert.match(readerPage(html, true), /data-reader-mode="offline"/)
assert.match(readerPage(html, true), /connect-src 'none'/)
assert.match(readerPage(html, false), /data-reader-mode="online"/)
assert.match(readerPage(html, false), /保留原文/)
console.log('PASS: 模型能力校验、真实工具阶段路由、独立离线 Reader')
