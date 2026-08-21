/**
 * axios 封装:
 * - 统一 baseURL(/api 走 vite 代理)
 * - 自动注入 Authorization 头(来自 localStorage)
 * - 401 自动清登录态并跳转登录页
 * - 错误统一提示
 */
import axios from 'axios'
import { ElMessage } from 'element-plus'

const TOKEN_KEY = 'kb_rag_token'
const USER_KEY = 'kb_rag_user'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function getUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}

export function setAuth(token, user) {
  localStorage.setItem(TOKEN_KEY, token || '')
  localStorage.setItem(USER_KEY, JSON.stringify(user || null))
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function hasPermission(code) {
  const u = getUser()
  if (!u || !u.permissions) return false
  if (u.permissions.includes('*')) return true
  return u.permissions.includes(code)
}

const http = axios.create({
  baseURL: '/api',
  timeout: 300000, // RAG 问答 / 大文件解析较慢,给足 5 分钟
})

http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (resp) => resp.data,
  (err) => {
    let msg = err.message || '请求失败'
    const status = err.response?.status
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') msg = detail
    else if (detail) msg = JSON.stringify(detail)
    else if (err.code === 'ECONNABORTED') msg = '请求超时,请稍后重试'
    else if (!err.response) msg = '无法连接后端服务,请确认 API 已启动'

    // 401/403(权限):清登录态并跳登录页(仅在浏览器端,避免 SSR 报错)
    if (status === 401) {
      clearAuth()
      if (location.pathname !== '/login') {
        ElMessage.error('登录已失效,请重新登录')
        location.href = `/login?redirect=${encodeURIComponent(location.pathname + location.search)}`
      } else {
        ElMessage.error(msg)
      }
      return Promise.reject(err)
    }
    ElMessage.error(msg)
    return Promise.reject(err)
  }
)

// ---------------- 认证 ----------------
export const authApi = {
  login: (username, password) =>
    http.post('/auth/login', { username, password }),
  me: () => http.get('/auth/me'),
  changePassword: (oldPassword, newPassword) =>
    http.post('/auth/change-password', { old_password: oldPassword, new_password: newPassword }),
}

// ---------------- 用户管理 ----------------
export const userApi = {
  list: () => http.get('/users'),
  get: (id) => http.get(`/users/${id}`),
  create: (data) => http.post('/users', data),
  update: (id, data) => http.put(`/users/${id}`, data),
  remove: (id) => http.delete(`/users/${id}`),
  assignRoles: (id, roleIds) => http.put(`/users/${id}/roles`, { role_ids: roleIds }),
  resetPassword: (id, newPassword) =>
    http.put(`/users/${id}/password`, { new_password: newPassword }),
}

// ---------------- 角色管理 ----------------
export const roleApi = {
  list: () => http.get('/roles'),
  get: (id) => http.get(`/roles/${id}`),
  create: (data) => http.post('/roles', data),
  update: (id, data) => http.put(`/roles/${id}`, data),
  remove: (id) => http.delete(`/roles/${id}`),
  assignPermissions: (id, permIds) =>
    http.put(`/roles/${id}/permissions`, { permission_ids: permIds }),
}

// ---------------- 权限管理 ----------------
export const permApi = {
  list: () => http.get('/permissions'),
  create: (data) => http.post('/permissions', data),
  remove: (id) => http.delete(`/permissions/${id}`),
}

// ---------------- 知识库 ----------------
export const kbApi = {
  list: () => http.get('/kb'),
  get: (id) => http.get(`/kb/${id}`),
  create: (data) => http.post('/kb', data),
  update: (id, data) => http.put(`/kb/${id}`, data),
  remove: (id) => http.delete(`/kb/${id}`),
}

// ---------------- 文档 ----------------
export const docApi = {
  list: (kbId) => http.get(`/kb/${kbId}/documents`),
  /**
   * 批量上传
   * @param {number} kbId 知识库 id
   * @param {File[]} files 文件数组
   * @param {{splitter:string, chunk_size:number, chunk_overlap:number}} params 切分参数
   */
  upload: (kbId, files, params) => {
    const fd = new FormData()
    files.forEach((f) => fd.append('files', f))
    fd.append('splitter', params.splitter)
    fd.append('chunk_size', params.chunk_size)
    fd.append('chunk_overlap', params.chunk_overlap)
    return http.post(`/kb/${kbId}/documents`, fd)
  },
  remove: (docId) => http.delete(`/kb/documents/${docId}`),
  retry: (docId) => http.post(`/kb/documents/${docId}/retry`),
}

// ---------------- 对话 ----------------
export const chatApi = {
  /**
   * 会话列表
   * @param {number|null} kbId 可选,按知识库过滤
   */
  sessions: (kbId) =>
    http.get('/chat/sessions', {
      params: kbId ? { kb_id: kbId } : {},
    }),
  /**
   * 创建会话
   * @param {number|null} kbId 知识库 id;为 null 表示纯 LLM 对话
   * @param {string} title 会话标题
   */
  createSession: (kbId, title) =>
    http.post('/chat/sessions', {
      kb_id: kbId ?? null,
      title,
      mode: kbId ? 'rag' : 'chat',
    }),
  removeSession: (sid) => http.delete(`/chat/sessions/${sid}`),
  renameSession: (sid, title) =>
    http.patch(`/chat/sessions/${sid}`, { title }),
  clearSession: (sid) => http.post(`/chat/sessions/${sid}/clear`),
  compressSession: (sid) => http.post(`/chat/sessions/${sid}/compress`),
  messages: (sid) => http.get(`/chat/sessions/${sid}/messages`),
  send: (sid, message) => http.post(`/chat/sessions/${sid}/chat`, { message }),
  /**
   * 流式对话(SSE)。
   * @param {number} sid 会话 id
   * @param {string} message 用户消息
   * @param {object} handlers 事件回调:{ onSources, onDelta, onDone, onError }
   * @returns {Promise<void>} 流结束后 resolve
   */
  sendStream: async (sid, message, handlers = {}) => {
    const token = getToken()
    const resp = await fetch(`/api/chat/sessions/${sid}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ message }),
    })
    if (!resp.ok) {
      let msg = `请求失败(${resp.status})`
      try {
        const data = await resp.json()
        if (data?.detail) msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
      } catch { /* 非 JSON 错误体,忽略 */ }
      if (handlers.onError) handlers.onError(msg)
      throw new Error(msg)
    }
    if (!resp.body) {
      const msg = '当前浏览器不支持流式接收'
      if (handlers.onError) handlers.onError(msg)
      throw new Error(msg)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buf = ''

    // 逐行解析 SSE:事件以空行分隔,行格式 data: {json}
    const handleEvent = (lineBlock) => {
      for (const line of lineBlock.split('\n')) {
        const trimmed = line.trim()
        if (!trimmed.startsWith('data:')) continue
        const payload = trimmed.slice(5).trim()
        if (!payload) continue
        let evt
        try {
          evt = JSON.parse(payload)
        } catch {
          continue // 忽略无法解析的行(如心跳注释)
        }
        if (evt.event === 'sources' && handlers.onSources) handlers.onSources(evt.sources || [])
        else if (evt.event === 'delta' && handlers.onDelta) handlers.onDelta(evt.text || '')
        else if (evt.event === 'done' && handlers.onDone) handlers.onDone(evt)
        else if (evt.event === 'error' && handlers.onError) handlers.onError(evt.detail || '对话服务异常')
      }
    }

    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      // SSE 事件以空行(\n\n)分隔
      let sep
      while ((sep = buf.indexOf('\n\n')) !== -1) {
        const block = buf.slice(0, sep)
        buf = buf.slice(sep + 2)
        handleEvent(block)
      }
    }
    // 处理残块
    if (buf.trim()) handleEvent(buf)
  },
}

// ---------------- 提示词模版 ----------------
export const promptApi = {
  /**
   * 提示词列表
   * @param {string} keyword 可选,按标题搜索
   */
  list: (keyword) =>
    http.get('/prompts', { params: keyword ? { keyword } : {} }),
  create: (data) => http.post('/prompts', data),
  update: (id, data) => http.put(`/prompts/${id}`, data),
  remove: (id) => http.delete(`/prompts/${id}`),
}
