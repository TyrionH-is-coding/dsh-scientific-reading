import assert from 'node:assert/strict'
import { conversationEvents, readSelectedChats, readLegacyChat, discussFigure } from '../lib/paper_sessions.js'

const event = (seq, type, content, source = { kind: 'user' }) => ({ event: {
  seq, time: '2026-09-08', type, surfaceOp: 'append', data: type === 'user/message'
    ? { source, content } : { message: { content } },
} })
const messages = [
  event(1, 'user/message', [{ type: 'text', text: '论文真的支持这个结论吗？' }]),
  event(2, 'user/message', [{ type: 'text', text: 'hidden instructions' }], { kind: 'system' }),
  event(3, 'assistant/message', [{ type: 'thinking', text: 'private reasoning' }, { type: 'text', text: '这是待验证推断。' + '正文'.repeat(150) }]),
  event(4, 'tool/result', [{ type: 'text', text: '{"block_id":"b1","source_pdf_sha256":"verified"}' }]),
]
const projected = conversationEvents(messages)
assert.deepEqual(projected.map(row => row.seq), [1, 3, 4])
assert.doesNotMatch(JSON.stringify(projected), /private reasoning|hidden instructions/)
assert.equal(projected[1].evidence_status, 'discussion_not_paper_fact')

const reads = []
const engine = async (_args, input) => ({ paper_id: input.paper_id, session_id: input.paper_id === 'missing' ? null : 'chat-' + input.paper_id,
  paper: { folder_id: input.paper_id === 'a' ? 'one' : 'two' }, confirmed_conclusions: [] })
const rpc = async (method, payload) => {
  assert.equal(method, 'session.history')
  reads.push(payload)
  return { events: messages, hasMore: true }
}
const request = { question: '比较两篇方法的差异', selection: [{ paper_id: 'a' }, { paper_id: 'b' }], maxChars: 100 }
const result = await readSelectedChats(engine, rpc, request)
assert.deepEqual(reads.map(row => row.sessionId), ['chat-a', 'chat-b'])
assert.deepEqual(result.selectedPaperIds, ['a', 'b'])
const history = result.chats[0].history
assert.equal(history.truncated, true)
assert.equal(history.nextBeforeSeq, 1)
assert.equal(history.nextTextOffset, 100)
const rest = await readSelectedChats(engine, rpc, { ...request, selection: [{ paper_id: 'a',
  beforeSeq: history.beforeSeq, textOffset: 100, pageSha256: history.pageSha256 }], maxChars: 10000 })
assert.deepEqual(JSON.parse(history.text + rest.chats[0].history.text), projected)
assert.equal(reads.at(-1).beforeSeq, 5)
await assert.rejects(readSelectedChats(engine, rpc, { ...request, selection: [{ paper_id: 'a', textOffset: 100 }] }), /chat_cursor_invalid/)
await assert.rejects(readSelectedChats(engine, rpc, { ...request, selection: [{ paper_id: 'a', beforeSeq: 5, textOffset: 100, pageSha256: 'changed' }] }), /chat_page_changed/)
const prior = reads.length
await assert.rejects(readSelectedChats(engine, rpc, { ...request, selection: [{ paper_id: 'a' }, { paper_id: 'missing' }] }), /paper_chat_missing/)
assert.equal(reads.length, prior)
await assert.rejects(readSelectedChats(engine, rpc, { ...request, selection: [{ paper_id: 'a' }, { paper_id: 'a' }] }), /chat_selection_invalid/)
console.log('PASS: 多选 chat 只读取指定会话，保留证据范围并校验跨页内容身份')

const legacyEngine = async () => ({sessions:[{session_id:'old-category',origin:'v0.1-category'}],reviews:[{session_id:'old-review',paper_id:'a'}],evidence_boundary:'混合讨论未分配到单篇论文'})
const legacy = await readLegacyChat(legacyEngine,rpc,{session_id:'old-category'})
assert.equal(legacy.read_only,true)
assert.equal(legacy.nextBeforeSeq,1)
assert.match(legacy.text,/待验证推断/)
assert.doesNotMatch(legacy.text,/private reasoning|hidden instructions/)
assert.equal((await readLegacyChat(legacyEngine,rpc,{session_id:'old-review'})).paper_id,'a')
await assert.rejects(readLegacyChat(legacyEngine,rpc,{session_id:'unselected-secret'}),/legacy_chat_unregistered/)
await assert.rejects(readLegacyChat(legacyEngine,rpc,{session_id:'old-category',beforeSeq:5,textOffset:1,pageSha256:'changed'}),/chat_page_changed/)

const figureCalls = []
const figureEngine = async (_args, input) => {
  figureCalls.push(input)
  if (input.action === 'figure_select') return {session_id:'chat-a', context:{asset_id:'fig1', revision:1}, image:{type:'image', mediaType:'image/png', data:'actual-image-bytes'}}
  return {image_status:'supplied_to_native_chat', revision:1}
}
let prompt
await discussFigure(figureEngine, async (method, input) => { assert.equal(method, 'session.prompt'); prompt=input }, {paper_id:'a', question:'解释此图'})
assert.equal(prompt.sessionId, 'chat-a')
assert.equal(prompt.content[1].data, 'actual-image-bytes')
assert.match(prompt.content[0].text, /此前选图不再是当前对象/)
assert.equal(figureCalls.at(-1).image_supplied, true)
figureCalls.length = 0
await assert.rejects(discussFigure(figureEngine, async () => { throw new Error('model_unavailable') }, {paper_id:'a'}), /model_unavailable/)
assert.equal(figureCalls.length, 1)
console.log('PASS: Figure 发送实际图像，失败不记录图像已提交')
