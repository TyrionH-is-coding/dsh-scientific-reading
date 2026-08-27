import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../client/client.js', import.meta.url), 'utf8')
for (const label of ['设置与状态', '重新检测', '机构访问', 'PDF 下载', '全文解析', '本地文献库', 'CloakBrowser', '保存密钥', '删除密钥']) {
  assert.match(source, new RegExp(label), `设置页缺少：${label}`)
}
assert.match(source, /id: 'scientific-reading-settings'/, '必须注册独立设置视图')
assert.match(source, /show_settings[^]*mark-presented/, '首次展示必须读取 onboarding 并立即标记已展示')
assert.match(source, /进入文献库/, '首次设置覆盖层必须提供返回文献库的明确入口')
assert.match(source, /type = 'password'/, 'MinerU Key 输入必须使用 password')
assert.match(source, /keyInput\.value = ''/, '提交后必须清空 Key 输入')
assert.match(source, /x-sr-csrf[^]*'1'/, '设置写操作必须发送 CSRF header')
assert.doesNotMatch(source, /MINERU_API_TOKEN；插件不保存密钥/, '不得保留环境变量唯一入口旧文案')
console.log('PASS: 独立设置页、首次展示与 MinerU Key UI 合同')
