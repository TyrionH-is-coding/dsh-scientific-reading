import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../client/client.js', import.meta.url), 'utf8')
for (const label of ['设置与状态', '模型与连接', 'PDF 解析', '文献库', '关于', '重新检测', 'PDF 自动获取', 'PDF 解析', '本地文献库', '保存密钥', '删除密钥', '存储位置', '管理模型连接', '密钥已保存，连接待验证']) {
  assert.match(source, new RegExp(label), `设置页缺少：${label}`)
}
assert.match(source, /id:\s*'scientific-reading-settings'/, '必须注册独立设置视图')
assert.match(source, /show_settings[^]*mark-presented/, '首次展示必须读取 onboarding 并立即标记已展示')
assert.match(source, /btn\('文献设置',openSettings/, '首次配置提示必须提供设置页签入口')
assert.doesNotMatch(source, /onboardingMount/, '未配置服务也不得用设置覆盖文献库')
assert.doesNotMatch(source, /input\('阅读主题'/, '阅读外观不得提供会被全局主题覆盖的另一套配色选择')
assert.match(source, /btn\('主题设置'[^]*openSettings/, '阅读外观应链接到同一套主题设置')
assert.match(source, /type = 'password'/, 'MinerU Key 输入必须使用 password')
assert.match(source, /keyInput\.value = ''/, '提交后必须清空 Key 输入')
assert.match(source, /x-sr-csrf[^]*'1'/, '设置写操作必须发送 CSRF header')
assert.match(source, /settings\/mineru-key[^]*settings\/recheck[^]*mineru_api/, '保存或删除 Key 后必须立即刷新 MinerU API 状态快照')
assert.doesNotMatch(source, /MINERU_API_TOKEN；插件不保存密钥/, '不得保留环境变量唯一入口旧文案')
assert.doesNotMatch(source, /CloakBrowser|灰色来源|Sci-Hub|LibGen/, '设置页不得展示用户无需操作的反自动化或灰色来源选项')
assert.doesNotMatch(source, /学校名（CARSI\/WebVPN）|scansci-pdf 可执行|Python 解释器|机构登录类型|引擎 Python 路径/, '插件设置卡不得暴露内部实现字段')
assert.doesNotMatch(source, /settings\/institution|高校 WebVPN|选择高校|使用机构浏览器|loadInstitution/, 'A 不应提供机构或浏览器获取入口')
assert.match(source, /library\.data_root/, '资产位置必须来自实际状态数据')
console.log('PASS: 独立设置页、首次展示与 MinerU Key UI 合同')
