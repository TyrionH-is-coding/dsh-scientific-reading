# PubMed 内容保真小样本 v1

`pubmed-content-v1.json` 于 2026-09-05 原创合成，共 13 个案例。它复用了调研中的失败形式，没有复制真实论文或覆盖历史调研结果。XML 是供 provider 注入的精简结构，不是完整 PubMed DTD 合规样本；测试不联网，PMID 只充当固定请求参数。

依据：[AbstractText](https://dtd.nlm.nih.gov/ncbi/pubmed/doc/out/250101/el-AbstractText.html)、[Abstract](https://dtd.nlm.nih.gov/ncbi/pubmed/doc/out/250101/el-Abstract.html)、[OtherAbstract](https://dtd.nlm.nih.gov/ncbi/pubmed/doc/out/250101/el-OtherAbstract.html)。主 Abstract 为英文摘要，OtherAbstract 可能是其他语言或通俗摘要，不能无条件拼接。

## 固定提取合同

- 保留内联嵌套、子元素及 tail 的所有文字，按文档顺序连接，不在标签边界插入空格；摘要仅去除段落外围空白。
- 普通和单段摘要沿用正文字符串，包括只有一个 Label 的原复现形式。多段摘要以空行分隔，并保留存在的 Label；不根据 NlmCategory 编造节标题。
- 不把 OtherAbstract 合并或代替主摘要；不根据文章 Language 丢弃主英文摘要。无摘要、空摘要保持 `None`，不会根据标题生成。
- `sub`/`sup` 保留文字字符，但 `abstract_en` 仍是纯文本，排版信息不会保留，例如 `TiO<sub>2</sub>` 变为 `TiO2`。
- `mathml-lexical-limit` 专门记录限制：分式的文字节点 `a`、`b` 会展开为 `ab`，这**不等价于分数 a/b，也不能作为公式语义通过**。本轮没有引入公式转换器；含结构性公式时须回到来源校核。字符完整性和数学含义是两个验收项。

## 四层验收

| 层次 | 样本与断言 | 可得结论 |
|---|---|---|
| 请求/结构成功 | 精确请求参数、provider success/retry；合法与损坏 XML | 只证明解析/请求状态合同 |
| 来源文字完整 | 13 例完整字符串对照，含数字、单位、否定词、希腊字母、空段边界及其他语言隔离 | 在这些合成输入中提取符合既定纯文本合同，不外推全库错误比例 |
| 译文和论断支持 | 复用 `review/fixtures/superscript-text.json`，增加数字、否定和“关联不确立因果”的英中配对 | 确定性检查只证明固定英中内容被保留；译文为样本作者提供，未测试模型翻译质量或真实论文结论 |
| 实际视觉表现 | 用既有 Reader review 检查同一 fixture 的上下标、词间距和英中排列；真实 generation 另记 | HTML 字符串断言不能代替浏览器实看；学术人工复核仍单列 |

固定输入版本为 `pubmed-content-v1`；Reader fixture 保持既有 schema `reader-review-fixture-v1`。两者的内容 SHA 与浏览器 revision 记录在本轮执行文档。后续升级先复跑这组小样本，再扩展真实失败类型及未参与修复的留出样本，不把这 13 例当完整质量基准。

从仓库根执行 `node scripts/run-python.mjs -m pytest -q engine/tests/test_metadata_enrichment.py engine/tests/test_reader_review_fixtures.py`。安装包验收需另行设置仅含独立安装目标的 `PYTHONPATH`，关闭 pytest 的源码路径覆盖并断言导入来源。
