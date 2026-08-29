/**
 * 展示格式化工具
 */

/** 字节数 -> 人类可读 */
export function formatSize(bytes) {
  if (bytes === null || bytes === undefined) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(2)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

/** datetime -> yyyy-MM-dd HH:mm */
export function formatTime(dt) {
  if (!dt) return '-'
  const d = new Date(dt)
  if (Number.isNaN(d.getTime())) return String(dt)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 文档解析状态 -> {text, tagType} */
export function docStatus(status) {
  const map = {
    pending: { text: '待处理', type: 'info' },
    processing: { text: '解析中', type: 'warning' },
    done: { text: '已完成', type: 'success' },
    failed: { text: '失败', type: 'danger' },
  }
  return map[status] || { text: status, type: 'info' }
}

/** 切分器显示名 */
export const SPLITTER_OPTIONS = [
  { value: 'auto', label: '自动(按文件类型)' },
  { value: 'sentence', label: '句子切分(推荐)' },
  { value: 'paragraph', label: '段落切分' },
  { value: 'token', label: 'Token 切分' },
  { value: 'simple', label: '简单定长切分' },
  { value: 'markdown', label: 'Markdown 标题切分' },
  { value: 'html', label: 'HTML 标签切分' },
  { value: 'json', label: 'JSON 结构切分' },
]

export function splitterLabel(v) {
  const hit = SPLITTER_OPTIONS.find((o) => o.value === v)
  return hit ? hit.label : v
}

/** 检索方式选项(与后端 schemas.RETRIEVAL_MODES 对齐) */
export const RETRIEVAL_MODE_OPTIONS = [
  { value: 'dense', label: '向量检索(语义相似度)' },
  { value: 'sparse', label: '全文检索(BM25 关键词)' },
  { value: 'hybrid', label: '混合检索(向量 + BM25 融合)' },
]

export function retrievalModeLabel(v) {
  const hit = RETRIEVAL_MODE_OPTIONS.find((o) => o.value === v)
  return hit ? hit.label : v
}

/** 检索方式标签颜色 */
export function retrievalModeTag(v) {
  return { dense: 'info', sparse: 'warning', hybrid: 'success' }[v] || 'info'
}

/** 检索方式短标签(表格展示用) */
export function retrievalModeShort(v) {
  return { dense: '向量检索', sparse: '全文检索', hybrid: '混合检索' }[v] || v
}

/** 混合检索融合排序器(与 Milvus 保留值一致,大小写敏感) */
export const HYBRID_RANKER_OPTIONS = [
  { value: 'RRFRanker', label: 'RRF 倒数排名融合(推荐)' },
  { value: 'WeightedRanker', label: '加权求和融合' },
]

export function hybridRankerLabel(v) {
  const hit = HYBRID_RANKER_OPTIONS.find((o) => o.value === v)
  return hit ? hit.label : v
}
