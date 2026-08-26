/** paper_id 解析：校验格式并映射到仓库外元数据路径。 */
import { join } from 'node:path'

const PAPER_ID_RE = /^(pmid_|doi_|arxiv_|library_|title_)[A-Za-z0-9_.\-]+$/

export function isPaperId(value: string): boolean {
  return PAPER_ID_RE.test(value) && !value.includes('..')
}

/** 严格解析 paper 路由，拒绝编码错误、路径穿越和多余层级。 */
export function parsePaperRoute(url: string, base: string): string[] | null {
  try {
    const path = new URL(url, 'http://localhost').pathname
    if (!path.startsWith(base + '/')) return null
    const parts = decodeURIComponent(path.slice(base.length + 1)).split('/')
    if (!parts.length || parts.some((part) => !part || part === '.' || part === '..')) return null
    return parts
  } catch {
    return null
  }
}

export function paperMetadataPath(dataRoot: string, paperId: string): string {
  if (!isPaperId(paperId)) throw new Error("invalid_paper_id: " + paperId)
  return join(dataRoot, "papers", paperId, "metadata.json")
}
