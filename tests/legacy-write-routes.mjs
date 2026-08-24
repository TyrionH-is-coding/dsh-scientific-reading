import assert from 'node:assert/strict'

import { registerRoutes } from '../lib/routes.js'

delete process.env.FEISHU_APP_ID
delete process.env.FEISHU_APP_SECRET

const routes = []
registerRoutes(
  {
    effect(fn) { fn() },
    logger() {},
    webServer: { register(route) { routes.push(route); return () => {} } },
  },
  {
    dataRoot: '', python: 'python', scansciExe: 'scansci-pdf', school: '',
    legalOnly: true, outputDir: '', loginType: 'carsi', scansciPython: '',
    enginePython: 'python', feishuConfig: '',
  },
)

assert.equal(
  routes.some((route) => route.kind === 'exact' && route.path === '/sr/api/paper'),
  false,
  '旧 POST /sr/api/paper 不得再注册；入库只允许 POST /sr/api/library',
)

const paperRoute = routes.find((route) => route.kind === 'prefix' && route.path === '/sr/api/paper')
assert.ok(paperRoute, '论文读取与批准动作路由必须保留')

const request = (url) => ({
  method: 'POST',
  url,
  on(event, callback) {
    if (event === 'data') callback(Buffer.from('{"project_context":"SECRET token Traceback"}'))
    if (event === 'end') queueMicrotask(callback)
  },
  destroy() {},
})
const response = () => ({
  statusCode: 0,
  body: '',
  writeHead(statusCode) { this.statusCode = statusCode },
  end(body = '') { this.body = String(body) },
})

const legacyCreate = response()
await paperRoute.handler(request('/sr/api/paper'), legacyCreate)
assert.equal(legacyCreate.statusCode, 404, '旧根级 POST 必须不可用')
assert.deepEqual(JSON.parse(legacyCreate.body), { error: 'not_found' })
assert.doesNotMatch(legacyCreate.body, /traceback|secret|token|password|exception/i)

for (const action of ['parse', 'quick-read']) {
  const output = response()
  await paperRoute.handler(request(`/sr/api/paper/title_fixture/${action}`), output)
  assert.equal(output.statusCode, 404, `${action} 旧单阶段写动作必须不可用`)
  assert.deepEqual(JSON.parse(output.body), { error: 'not_found' })
  assert.doesNotMatch(output.body, /traceback|secret|token|password|exception/i)
}

console.log('PASS: 旧根级入库与单阶段写路由已收口')
