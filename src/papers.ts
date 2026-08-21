/** paper_id 解析：校验格式并映射到仓库外元数据路径。 */
import { join } from 'node:path'

const PAPER_ID_RE = /^(pmid_|doi_|zotero_|title_)[A-Za-z0-9_.\-]+$/

export function isPaperId(value: string): boolean {
  return PAPER_ID_RE.test(value)
}

export function paperMetadataPath(dataRoot: string, paperId: string): string {
  if (!isPaperId(paperId)) throw new Error("invalid_paper_id: " + paperId)
  return join(dataRoot, "papers", paperId, "metadata.json")
}
