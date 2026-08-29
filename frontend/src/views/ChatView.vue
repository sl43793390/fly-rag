<template>
  <div class="chat-page">
    <!-- 左侧:新建会话 + 历史会话列表 -->
    <aside class="side">
      <div class="side-block">
        <div class="side-label">新建会话</div>
        <el-select
          v-model="newKbId"
          placeholder="选择知识库(可选)"
          clearable
          style="width: 100%"
        >
          <el-option :value="null" label="(不指定知识库,直接和大模型对话)" />
          <el-option
            v-for="kb in kbs"
            :key="kb.id"
            :value="kb.id"
            :label="kb.name"
          >
            <span>{{ kb.name }}</span>
            <span class="option-sub">{{ kb.doc_count }} 份文档</span>
          </el-option>
        </el-select>
        <el-input
          v-model="newTitle"
          placeholder="会话标题(可空)"
          style="margin-top: 8px"
          maxlength="60"
        />
        <el-button
          type="primary"
          :icon="Plus"
          style="width: 100%; margin-top: 8px"
          @click="newSession"
        >
          开始对话
        </el-button>
      </div>

      <div class="side-block sessions">
        <div class="side-label">
          会话历史
          <el-tooltip content="仅显示属于当前登录用户的会话,未登录时为匿名会话" placement="top">
            <el-icon class="hint-icon"><InfoFilled /></el-icon>
          </el-tooltip>
        </div>
        <div v-if="!sessions.length" class="session-empty">暂无会话</div>
        <div
          v-for="s in sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: s.id === currentSessionId }"
          @click="selectSession(s.id)"
        >
          <el-icon><ChatDotRound /></el-icon>
          <div class="session-meta">
            <div class="session-title">
              {{ s.title }}
              <el-tag v-if="s.mode === 'chat'" size="small" effect="plain">纯对话</el-tag>
              <el-tag v-else size="small" type="success" effect="plain">{{ s.kb_name }}</el-tag>
            </div>
            <div class="session-time">{{ formatTime(s.updated_at) }}</div>
          </div>
          <el-icon class="session-del" @click.stop="removeSession(s)"><Delete /></el-icon>
        </div>
      </div>
    </aside>

    <!-- 右侧:消息区 -->
    <section class="main">
      <div class="chat-header">
        <div class="chat-header-title">
          <template v-if="currentSession">
            {{ currentSession.title }}
            <el-tag v-if="currentSession.mode === 'chat'" size="small" effect="plain">纯 LLM 对话</el-tag>
            <el-tag v-else size="small" type="success" effect="plain">
              {{ currentSession.kb_name || '知识库' }}
            </el-tag>
          </template>
          <template v-else>
            <span class="muted">未选择会话</span>
          </template>
        </div>
        <div class="chat-header-actions" v-if="currentSession">
          <el-button link size="small" @click="onRename">重命名</el-button>
          <el-button
            link
            size="small"
            :disabled="sending || !messages.length"
            @click="clearMessages"
          >
            清空对话
          </el-button>
        </div>
      </div>

        <div ref="scrollRef" class="messages">
          <el-empty
            v-if="!currentSessionId"
            description="新建或从左侧选择会话,也可直接在下方输入消息(将自动创建一个纯 LLM 会话)"
            class="empty-center"
          />
          <div
            v-for="(m, idx) in messages"
            :key="m.id"
            class="msg-row"
            :class="m.role"
          >
            <div class="bubble" :class="{ 'bubble-summary': m.is_summary }">
              <div v-if="m.is_summary" class="summary-tag">
                <el-icon><Clock /></el-icon>
                <span>历史摘要(已自动压缩)</span>
              </div>
              <!-- AI 回复/摘要:markdown 渲染;用户消息保持纯文本 -->
              <div
                v-if="m.role === 'assistant'"
                class="bubble-content markdown-body"
                v-html="renderMarkdown(m.content)"
              />
              <div v-else class="bubble-content">{{ m.content }}</div>
              <!-- 引用元数据:文档名称标签 -->
              <div
                v-if="m.role === 'assistant' && !m.is_summary && m.sources && m.sources.length"
                class="source-tags"
              >
                <span class="source-tags-label">
                  <el-icon :size="12"><Collection /></el-icon>
                  引用知识库:
                </span>
                <el-tag
                  v-for="name in uniqueFileNames(m.sources)"
                  :key="name"
                  size="small"
                  effect="plain"
                  round
                  class="source-tag"
                >
                  {{ name }}
                </el-tag>
              </div>
              <!-- RAG 引用来源原文 -->
              <div
                v-if="m.role === 'assistant' && !m.is_summary && m.sources && m.sources.length"
                class="sources"
              >
                <el-collapse>
                  <el-collapse-item :title="`引用原文(${m.sources.length})`">
                    <div
                      v-for="(src, i) in m.sources"
                      :key="i"
                      class="source-item"
                    >
                      <div class="source-head">
                        <el-tag size="small" type="info" effect="plain">
                          {{ src.file_name || '未知来源' }}
                        </el-tag>
                        <span v-if="src.score != null" class="source-score">
                          相似度 {{ (src.score * 100).toFixed(1) }}%
                        </span>
                      </div>
                      <div class="source-text">{{ src.text }}</div>
                    </div>
                  </el-collapse-item>
                </el-collapse>
              </div>
            </div>

            <!-- AI 回复底部操作按钮:复制 / 重试 / 保存为提示词模版 -->
            <div
              v-if="m.role === 'assistant' && !m.is_summary"
              class="msg-actions"
            >
              <el-tooltip content="复制" placement="bottom" :hide-after="0">
                <button class="action-btn" type="button" @click="copyMessage(m)">
                  <el-icon :size="14"><CopyDocument /></el-icon>
                </button>
              </el-tooltip>
              <el-tooltip content="重试" placement="bottom" :hide-after="0">
                <button
                  class="action-btn"
                  type="button"
                  :disabled="sending"
                  @click="retryMessage(idx)"
                >
                  <el-icon :size="14"><RefreshRight /></el-icon>
                </button>
              </el-tooltip>
              <el-tooltip content="保存为提示词模版" placement="bottom" :hide-after="0">
                <button class="action-btn" type="button" @click="saveAsPrompt(m)">
                  <el-icon :size="14"><CollectionTag /></el-icon>
                </button>
              </el-tooltip>
            </div>
          </div>

          <div v-if="sending" class="msg-row assistant">
            <div class="bubble">
              <div class="bubble-content typing">
                <span class="dot" /><span class="dot" /><span class="dot" />
              </div>
            </div>
          </div>
        </div>

        <div class="input-bar">
          <el-input
            v-model="input"
            type="textarea"
            :rows="2"
            :disabled="sending"
            :placeholder="inputPlaceholder"
            resize="none"
            @keydown.enter.exact.prevent="onEnter"
          />
          <div class="input-actions">
            <span class="hint-text">Enter 发送,Shift+Enter 换行</span>
            <el-button
              type="primary"
              :icon="Promotion"
              :loading="sending"
              :disabled="!input.trim()"
              @click="onSend"
            >
              发送
            </el-button>
          </div>
        </div>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatDotRound,
  Clock,
  Collection,
  CollectionTag,
  CopyDocument,
  Delete,
  InfoFilled,
  Plus,
  Promotion,
  RefreshRight,
} from '@element-plus/icons-vue'
import { chatApi, kbApi, promptApi } from '../api'
import { authStore as auth } from '../store/auth'
import { formatTime } from '../utils/format'
import MarkdownIt from 'markdown-it'

// markdown 渲染:默认转义内嵌 HTML(防 XSS);breaks 让单个换行也显示为换行,适合聊天
const md = new MarkdownIt({ breaks: true, linkify: true })

/** AI 回复 markdown 渲染(v-html 使用);内容为空时返回空串 */
function renderMarkdown(text) {
  if (!text) return ''
  return md.render(text)
}

const route = useRoute()

const kbs = ref([])
const sessions = ref([])
const messages = ref([])
const currentSessionId = ref(null)
const currentSession = ref(null)
const input = ref('')
const sending = ref(false)
const scrollRef = ref(null)

const newKbId = ref(null)
const newTitle = ref('')

const inputPlaceholder = computed(() => {
  if (!currentSession.value) {
    return '未选择会话,输入后将自动创建一个纯 LLM 会话;或从左侧选择历史会话'
  }
  return currentSession.value.mode === 'chat'
    ? '和大模型自由对话,无需知识库'
    : '基于知识库提问,回答附带引用来源'
})

async function loadKbs() {
  try {
    kbs.value = await kbApi.list()
  } catch {
    kbs.value = []
  }
  // 支持从知识库列表页跳转携带 ?kb=N
  const fromQuery = Number(route.query.kb)
  if (fromQuery && kbs.value.some((k) => k.id === fromQuery)) {
    newKbId.value = fromQuery
  }
}

async function loadSessions() {
  try {
    sessions.value = await chatApi.sessions()
  } catch {
    sessions.value = []
  }
  // 如果有正在选中的会话,保留选中;否则不主动选
  if (currentSessionId.value && !sessions.value.some((s) => s.id === currentSessionId.value)) {
    currentSessionId.value = null
    currentSession.value = null
    messages.value = []
  }
}

async function newSession() {
  // 点击「开始对话」:只重置为新对话界面,不立即创建会话。
  // 空会话只有真正发送首条消息时才在 onSend 中创建并入库,
  // 避免用户点了按钮但没聊天就切到历史会话/其他页面时,把空会话写进数据库。
  currentSessionId.value = null
  currentSession.value = null
  messages.value = []
  input.value = ''
  scrollToBottom()
}

async function selectSession(sid) {
  currentSessionId.value = sid
  currentSession.value = sessions.value.find((s) => s.id === sid) || null
  // 切换历史会话时,把上方知识库下拉框联动到该会话当时绑定的知识库
  syncKbSelectWithSession(currentSession.value)
  try {
    messages.value = await chatApi.messages(sid)
  } catch {
    messages.value = []
    ElMessage.error('加载历史消息失败')
  }
  scrollToBottom()
}

/**
 * 会话切换联动上方「新建会话」的知识库下拉框:
 * - 会话绑定了知识库且该知识库仍存在 -> 切到对应知识库;
 * - 会话是纯 LLM 对话(kb_id 为空) -> 切到"(不指定知识库)";
 * - 绑定的知识库在列表中找不到(如已被删除) -> 不切换,保持当前选择。
 */
function syncKbSelectWithSession(s) {
  if (!s || s.kb_id == null) {
    newKbId.value = null
    return
  }
  if (kbs.value.some((k) => k.id === s.kb_id)) {
    newKbId.value = s.kb_id
  }
}

async function removeSession(s) {
  await ElMessageBox.confirm(`删除会话「${s.title}」及其全部消息?`, '删除确认', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await chatApi.removeSession(s.id)
  if (currentSessionId.value === s.id) {
    currentSessionId.value = null
    currentSession.value = null
    messages.value = []
  }
  await loadSessions()
}

async function onRename() {
  if (!currentSession.value) return
  try {
    const { value } = await ElMessageBox.prompt('会话标题', '重命名会话', {
      inputValue: currentSession.value.title,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValidator: (v) => (v && v.trim() ? true : '标题不能为空'),
    })
    await chatApi.renameSession(currentSession.value.id, value.trim())
    currentSession.value.title = value.trim()
    const item = sessions.value.find((s) => s.id === currentSession.value.id)
    if (item) item.title = value.trim()
    ElMessage.success('已重命名')
  } catch {
    /* 用户取消 */
  }
}

async function onSend() {
  const text = input.value.trim()
  if (!text || sending.value) return
  // 未选会话:自动创建一个会话(此时才真正入库)
  // 若用户已在「新建会话」处选择了知识库,则沿用该知识库(mode=rag);
  // 未选择知识库时才是纯 LLM 会话(createSession 内 kb 为 null 时 mode=chat)
  if (!currentSessionId.value) {
    try {
      const s = await chatApi.createSession(
        newKbId.value,
        newTitle.value.trim() || '新会话'
      )
      newTitle.value = ''
      await loadSessions()
      await selectSession(s.id)
    } catch {
      return
    }
    // selectSession 已设置 currentSessionId,继续往下发送
    if (!currentSessionId.value) return
  }
  const sid = currentSessionId.value
  // 记录是否为首条消息:用于发送后用前 8 字覆盖默认标题
  const isFirstMessage = messages.value.length === 0
  input.value = ''
  sending.value = true

  messages.value.push({
    id: `local-${Date.now()}`,
    role: 'user',
    content: text,
    sources: null,
    is_summary: false,
  })
  // 占位的 AI 气泡:流式增量会不断填充其 content(打字机效果)
  const assistantMsg = reactive({
    id: `local-a-${Date.now()}`,
    role: 'assistant',
    content: '',
    sources: null,
    is_summary: false,
  })
  messages.value.push(assistantMsg)
  scrollToBottom()

  let streamFailed = false
  try {
    await chatApi.sendStream(sid, text, {
      // 检索完成:先渲染引用标签
      onSources: (sources) => {
        assistantMsg.sources = sources
      },
      // 增量文本:逐段追加(打字机效果)
      onDelta: (chunk) => {
        assistantMsg.content += chunk
        scrollToBottom()
      },
      // 结束:回填消息 id 与最终引用
      onDone: (evt) => {
        if (evt.message_id) assistantMsg.id = evt.message_id
        assistantMsg.sources = evt.sources || assistantMsg.sources
        // 触发自动压缩时刷新消息列表以显示摘要
        if (evt.compressed) {
          ElMessage.info('对话历史已超过 30 轮,旧消息已自动压缩为摘要')
          chatApi
            .messages(sid)
            .then((list) => (messages.value = list))
            .catch(() => {})
        }
      },
      onError: (msg) => {
        streamFailed = true
        ElMessage.error(msg)
      },
    })
    // 首条消息:若标题仍是默认占位,则用消息前 8 字作为会话标题
    if (
      !streamFailed &&
      isFirstMessage &&
      currentSession.value &&
      (!currentSession.value.title || currentSession.value.title === '新会话')
    ) {
      const newTitle = text.slice(0, 8).trim() || '新会话'
      try {
        await chatApi.renameSession(sid, newTitle)
        currentSession.value.title = newTitle
      } catch {
        /* 重命名失败不阻塞对话 */
      }
    }
    // 刷新左侧列表顺序(刚发消息的会话排到最前,标题也同步更新)
    await loadSessions()
  } catch {
    // sendStream 内部已通过 onError 提示;此处恢复输入内容
    if (!streamFailed) ElMessage.error('发送失败,请重试')
    if (!assistantMsg.content) {
      // 一个字都没收到:移除占位气泡,还原输入
      messages.value = messages.value.filter((m) => m !== assistantMsg)
      input.value = text
    }
  } finally {
    sending.value = false
    scrollToBottom()
  }
}

function onEnter() {
  if (!sending.value) onSend()
}

async function clearMessages() {
  await ElMessageBox.confirm('清空当前会话的全部消息?', '清空确认', {
    type: 'warning',
    confirmButtonText: '清空',
    cancelButtonText: '取消',
  })
  await chatApi.clearSession(currentSessionId.value)
  messages.value = []
}

function scrollToBottom() {
  nextTick(() => {
    if (scrollRef.value) scrollRef.value.scrollTop = scrollRef.value.scrollHeight
  })
}

// ============================================================
// 消息操作:复制 / 重试 / 保存为提示词模版
// ============================================================
/** 引用元数据:去重后的文档名列表 */
function uniqueFileNames(sources) {
  const names = []
  for (const s of sources || []) {
    const n = (s.file_name || '').trim()
    if (n && !names.includes(n)) names.push(n)
  }
  return names
}

async function copyMessage(m) {
  const text = m.content || ''
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      // 非安全上下文(如 http)的降级方案
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败,请手动选择文本复制')
  }
}

/** 重试:向前找最近的用户提问,重新发送一轮 */
function retryMessage(idx) {
  if (sending.value) return
  for (let i = idx - 1; i >= 0; i--) {
    if (messages.value[i].role === 'user') {
      const text = messages.value[i].content
      if (text) {
        input.value = text
        onSend()
      }
      return
    }
  }
  ElMessage.warning('未找到该回复对应的提问')
}

async function saveAsPrompt(m) {
  const defaultTitle =
    (m.content || '').replace(/\s+/g, ' ').slice(0, 20).trim() || '新提示词'
  try {
    const { value } = await ElMessageBox.prompt(
      '为该提示词起个标题,保存后可在「提示词」页面管理',
      '保存为提示词模版',
      {
        inputValue: defaultTitle,
        confirmButtonText: '保存',
        cancelButtonText: '取消',
        inputValidator: (v) => (v && v.trim() ? true : '标题不能为空'),
      }
    )
    await promptApi.create({ title: value.trim(), content: m.content })
    ElMessage.success('已保存为提示词模版')
  } catch {
    /* 用户取消 */
  }
}

// ============================================================
// 从提示词管理页跳转:填入输入框
// ============================================================
function applyPendingPrompt() {
  if (!route.query.prompt) return
  const raw = sessionStorage.getItem('kb_rag_pending_prompt')
  sessionStorage.removeItem('kb_rag_pending_prompt')
  if (!raw) return
  try {
    const { content } = JSON.parse(raw)
    if (content) {
      input.value = content
      ElMessage.success('已填入提示词,可直接发送或编辑后发送')
    }
  } catch {
    /* sessionStorage 数据损坏则忽略 */
  }
}

onMounted(async () => {
  await Promise.all([loadKbs(), loadSessions()])
  applyPendingPrompt()
})
</script>

<style scoped>
.chat-page {
  display: flex;
  height: 100%;
  max-width: 1400px;
  margin: 0 auto;
}

/* 左侧栏 */
.side {
  width: 280px;
  flex-shrink: 0;
  background: #fff;
  border-right: 1px solid #e4e7ed;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  overflow: auto;
}

.side :deep(.el-select .el-select__wrapper) {
  border-radius: 8px;
}

.side :deep(.el-input__wrapper) {
  border-radius: 8px;
}

.side-block.sessions {
  flex: 1;
  min-height: 0;
}

.side-label {
  font-size: 13px;
  color: #606266;
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.hint-icon {
  color: #c0c4cc;
  cursor: help;
}

.option-sub {
  float: right;
  color: #909399;
  font-size: 12px;
}

.session-empty {
  color: #c0c4cc;
  font-size: 13px;
  text-align: center;
  padding: 20px 0;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border-radius: 6px;
  cursor: pointer;
  color: #303133;
  font-size: 13px;
  margin-bottom: 4px;
}

.session-item:hover {
  background: #f5f7fa;
}

.session-item.active {
  background: #ecf5ff;
  color: #409eff;
}

.session-meta {
  flex: 1;
  min-width: 0;
}

.session-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 6px;
}

.session-time {
  font-size: 11px;
  color: #c0c4cc;
  margin-top: 2px;
}

.session-del {
  color: #c0c4cc;
  display: none;
}

.session-item:hover .session-del {
  display: inline-flex;
}

.session-del:hover {
  color: #f56c6c;
}

/* 右侧消息区 */
.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.empty-center {
  margin: auto;
}

.chat-header {
  padding: 12px 24px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.chat-header-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 15px;
  color: #303133;
}

.chat-header-actions {
  display: flex;
  gap: 8px;
}

.messages {
  flex: 1;
  overflow: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.msg-row {
  display: flex;
  flex-direction: column;
  max-width: 86%;
}

.msg-row.user {
  align-self: flex-end;
  align-items: flex-end;
}

.msg-row.assistant {
  align-items: flex-start;
}

.bubble {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 12px;
  padding: 12px 14px;
  box-shadow: 0 2px 8px rgba(31, 45, 61, 0.04);
  min-width: 0;
}

/* 用户消息:主题蓝渐变,与整体色调一致 */
.msg-row.user .bubble {
  background: linear-gradient(135deg, #ecf5ff 0%, #dbeafe 100%);
  border-color: #d9ecff;
}

.bubble-summary {
  background: #fdf6ec;
  border: 1px dashed #e6a23c;
}

.summary-tag {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #e6a23c;
  margin-bottom: 4px;
}

.bubble-content {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 14px;
  line-height: 1.7;
  color: #303133;
}

/* AI 回复 markdown 渲染样式(v-html 内容无 scoped 属性,需 :deep 穿透) */
.markdown-body {
  white-space: normal; /* 覆盖 pre-wrap,块级元素自身控制换行,避免叠加空行 */
}

.markdown-body :deep(p) {
  margin: 0 0 8px;
}

.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4),
.markdown-body :deep(h5),
.markdown-body :deep(h6) {
  margin: 14px 0 8px;
  font-weight: 600;
  line-height: 1.4;
}

.markdown-body :deep(h1) {
  font-size: 18px;
}

.markdown-body :deep(h2) {
  font-size: 17px;
}

.markdown-body :deep(h3) {
  font-size: 15px;
}

.markdown-body :deep(h4),
.markdown-body :deep(h5),
.markdown-body :deep(h6) {
  font-size: 14px;
}

.markdown-body :deep(h1:first-child),
.markdown-body :deep(h2:first-child),
.markdown-body :deep(h3:first-child) {
  margin-top: 0;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0 0 8px;
  padding-left: 22px;
}

.markdown-body :deep(li) {
  margin: 2px 0;
}

.markdown-body :deep(code) {
  padding: 1px 5px;
  border-radius: 4px;
  background: #f0f2f5;
  color: #c7254e;
  font-size: 13px;
  font-family: 'JetBrains Mono', Consolas, Menlo, monospace;
}

.markdown-body :deep(pre) {
  margin: 8px 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: #282c34;
  overflow-x: auto;
}

.markdown-body :deep(pre code) {
  padding: 0;
  background: transparent;
  color: #abb2bf;
  font-size: 13px;
  line-height: 1.6;
}

.markdown-body :deep(blockquote) {
  margin: 8px 0;
  padding: 4px 12px;
  border-left: 3px solid #d9ecff;
  background: #f8f9fb;
  color: #606266;
}

.markdown-body :deep(table) {
  margin: 8px 0;
  border-collapse: collapse;
  width: 100%;
  font-size: 13px;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #e4e7ed;
  padding: 6px 10px;
  text-align: left;
}

.markdown-body :deep(th) {
  background: #f5f7fa;
  font-weight: 600;
}

.markdown-body :deep(a) {
  color: var(--el-color-primary, #409eff);
  text-decoration: none;
}

.markdown-body :deep(a:hover) {
  text-decoration: underline;
}

.markdown-body :deep(img) {
  max-width: 100%;
  border-radius: 6px;
}

.markdown-body :deep(hr) {
  border: none;
  border-top: 1px solid #e4e7ed;
  margin: 12px 0;
}

/* 打字动画 */
.typing {
  display: flex;
  gap: 5px;
  align-items: center;
  padding: 4px 0;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #c0c4cc;
  animation: blink 1.2s infinite ease-in-out;
}

.dot:nth-child(2) {
  animation-delay: 0.2s;
}

.dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes blink {
  0%, 80%, 100% { opacity: 0.25; }
  40% { opacity: 1; }
}

/* AI 消息底部操作按钮:简洁小按钮,悬浮提示文字 */
.msg-actions {
  display: flex;
  gap: 2px;
  margin-top: 6px;
}

.action-btn {
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #a8abb2;
  cursor: pointer;
  transition: all 0.15s ease;
}

.action-btn:hover {
  background: #f0f2f5;
  color: var(--el-color-primary, #409eff);
}

.action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* 引用元数据:文档名标签 */
.source-tags {
  margin-top: 10px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.source-tags-label {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  color: #a8abb2;
}

.source-tag {
  max-width: 220px;
}

.source-tag :deep(.el-tag__content) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 引用来源原文 */
.sources {
  margin-top: 10px;
  border-top: 1px dashed #e4e7ed;
  padding-top: 6px;
}

.sources :deep(.el-collapse) {
  border: none;
}

.sources :deep(.el-collapse-item__header) {
  font-size: 12px;
  color: #909399;
  height: 30px;
  line-height: 30px;
  background: transparent;
  border: none;
}

.sources :deep(.el-collapse-item__wrap) {
  border: none;
  background: transparent;
}

.sources :deep(.el-collapse-item__content) {
  padding-bottom: 4px;
}

.source-item {
  background: #f8f9fb;
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 6px;
}

.source-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.source-score {
  font-size: 12px;
  color: #909399;
}

.source-text {
  font-size: 12px;
  color: #606266;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 输入区 */
.input-bar {
  padding: 14px 24px 18px;
  background: #fff;
  border-top: 1px solid #e4e7ed;
}

.input-bar :deep(.el-textarea__inner) {
  border-radius: 12px;
  padding: 10px 14px;
  box-shadow: 0 0 0 1px #e4e7ed inset;
  transition: box-shadow 0.2s ease;
}

.input-bar :deep(.el-textarea__inner:focus) {
  box-shadow:
    0 0 0 1px var(--el-color-primary, #409eff) inset,
    0 4px 14px rgba(64, 158, 255, 0.12);
}

.input-actions {
  margin-top: 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.hint-text {
  font-size: 12px;
  color: #c0c4cc;
}
</style>
