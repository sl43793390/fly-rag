<template>
  <div class="page">
    <div class="page-toolbar">
      <div>
        <h2 class="page-title">提示词管理</h2>
        <p class="page-sub">沉淀高频提问模版,一键带入对话,持续复用</p>
      </div>
      <el-button type="primary" :icon="Plus" round @click="openCreate">
        新建提示词
      </el-button>
    </div>

    <!-- 搜索框 -->
    <div class="search-bar">
      <el-input
        v-model="keyword"
        size="large"
        clearable
        :prefix-icon="Search"
        placeholder="搜索提示词标题..."
        class="search-input"
        @input="onSearch"
        @clear="onSearch"
      />
      <span class="search-count">{{ prompts.length }} 个提示词</span>
    </div>

    <!-- 卡片网格 -->
    <div v-loading="loading" class="prompt-grid">
      <div v-for="p in prompts" :key="p.id" class="prompt-card">
        <div class="card-head">
          <div class="card-title" :title="p.title">{{ p.title }}</div>
          <el-dropdown trigger="hover" @command="(cmd) => onCommand(cmd, p)">
            <button class="more-btn" type="button" @click.stop>
              <el-icon :size="16"><MoreFilled /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="chat" :icon="ChatDotRound">
                  使用该提示词聊天
                </el-dropdown-item>
                <el-dropdown-item command="edit" :icon="Edit">编辑</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <div class="card-time">{{ formatTime(p.created_at) }}</div>
        <div class="card-content">{{ p.content }}</div>

        <div class="card-foot">
          <span class="card-foot-hint">点击右上角「···」快速使用</span>
          <el-tooltip content="删除该提示词" placement="top" :hide-after="0">
            <button class="del-btn" type="button" @click="onRemove(p)">
              <el-icon :size="14"><Delete /></el-icon>
            </button>
          </el-tooltip>
        </div>
      </div>

      <div v-if="!loading && !prompts.length" class="grid-empty">
        <el-empty
          :description="keyword ? '没有匹配的提示词,换个关键词试试' : '还没有提示词,点击右上角「新建提示词」或在对话中保存'"
        />
      </div>
    </div>

    <!-- 新建 / 编辑 -->
    <el-dialog
      v-model="dialog.visible"
      :title="dialog.isEdit ? '编辑提示词' : '新建提示词'"
      width="720px"
      destroy-on-close
      class="prompt-dialog"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="标题" prop="title">
          <el-input
            v-model="form.title"
            placeholder="给提示词起个好记的名字"
            maxlength="128"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="提示词内容" prop="content">
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="14"
            resize="vertical"
            placeholder="输入提示词内容,将在聊天页一键填入输入框"
            maxlength="16384"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button round @click="dialog.visible = false">取消</el-button>
        <el-button
          v-if="dialog.isEdit"
          type="success"
          round
          :loading="dialog.chatting"
          :disabled="dialog.saving"
          @click="saveAndChat"
        >
          保存并去聊天
        </el-button>
        <el-button type="primary" round :loading="dialog.saving" @click="onSave">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ChatDotRound, Delete, Edit, MoreFilled, Plus, Search } from '@element-plus/icons-vue'
import { promptApi } from '../api'
import { formatTime } from '../utils/format'

const router = useRouter()

const loading = ref(false)
const prompts = ref([])
const keyword = ref('')
const formRef = ref(null)
const searchTimer = ref(null)

const dialog = reactive({
  visible: false,
  isEdit: false,
  saving: false,
  chatting: false,
  editId: null,
})
const form = reactive({ title: '', content: '' })
const rules = {
  title: [{ required: true, message: '请输入标题', trigger: 'blur' }],
  content: [{ required: true, message: '请输入提示词内容', trigger: 'blur' }],
}

async function load() {
  loading.value = true
  try {
    prompts.value = await promptApi.list(keyword.value.trim() || undefined)
  } finally {
    loading.value = false
  }
}

/** 搜索防抖 */
function onSearch() {
  if (searchTimer.value) clearTimeout(searchTimer.value)
  searchTimer.value = setTimeout(load, 300)
}

function openCreate() {
  dialog.isEdit = false
  dialog.editId = null
  Object.assign(form, { title: '', content: '' })
  dialog.visible = true
}

function openEdit(p) {
  dialog.isEdit = true
  dialog.editId = p.id
  Object.assign(form, { title: p.title, content: p.content })
  dialog.visible = true
}

async function onSave() {
  await formRef.value.validate()
  dialog.saving = true
  try {
    if (dialog.isEdit) {
      await promptApi.update(dialog.editId, { ...form })
      ElMessage.success('提示词已更新')
    } else {
      await promptApi.create({ ...form })
      ElMessage.success('提示词已创建')
    }
    dialog.visible = false
    await load()
  } finally {
    dialog.saving = false
  }
}

/** 编辑态:保存后直接带着提示词去聊天 */
async function saveAndChat() {
  await formRef.value.validate()
  dialog.chatting = true
  try {
    await promptApi.update(dialog.editId, { ...form })
    ElMessage.success('提示词已更新')
    dialog.visible = false
    goChat({ title: form.title, content: form.content })
  } finally {
    dialog.chatting = false
  }
}

function onCommand(cmd, p) {
  if (cmd === 'chat') goChat(p)
  else if (cmd === 'edit') openEdit(p)
}

/** 携带提示词跳转聊天页:内容放 sessionStorage,避免 URL 超长 */
function goChat(p) {
  sessionStorage.setItem(
    'kb_rag_pending_prompt',
    JSON.stringify({ title: p.title, content: p.content })
  )
  router.push({ path: '/chat', query: { prompt: '1' } })
}

async function onRemove(p) {
  try {
    await ElMessageBox.confirm(`删除提示词「${p.title}」?该操作不可恢复。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await promptApi.remove(p.id)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
onBeforeUnmount(() => {
  if (searchTimer.value) clearTimeout(searchTimer.value)
})
</script>

<style scoped>
.page {
  max-width: 1280px;
  margin: 0 auto;
  padding: 24px;
}

.page-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}

.page-title {
  margin: 0 0 4px;
  font-size: 20px;
}

.page-sub {
  margin: 0;
  color: #909399;
  font-size: 13px;
}

/* 搜索区 */
.search-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 20px;
}

.search-input {
  max-width: 420px;
}

.search-input :deep(.el-input__wrapper) {
  border-radius: 999px;
  padding: 4px 8px 4px 18px;
  box-shadow: 0 0 0 1px #e4e7ed inset;
  transition: box-shadow 0.2s ease;
}

.search-input :deep(.el-input__wrapper.is-focus) {
  box-shadow:
    0 0 0 1px var(--el-color-primary) inset,
    0 4px 14px rgba(64, 158, 255, 0.15);
}

.search-count {
  color: #a8abb2;
  font-size: 13px;
}

/* 卡片网格 */
.prompt-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
  min-height: 200px;
  align-content: start;
}

.prompt-card {
  position: relative;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 12px;
  padding: 16px 16px 12px;
  display: flex;
  flex-direction: column;
  transition:
    transform 0.2s ease,
    box-shadow 0.2s ease,
    border-color 0.2s ease;
}

.prompt-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 10px 24px rgba(31, 45, 61, 0.08);
  border-color: #d9ecff;
}

.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-time {
  margin-top: 4px;
  font-size: 12px;
  color: #c0c4cc;
}

.card-content {
  margin-top: 10px;
  font-size: 13px;
  line-height: 1.7;
  color: #606266;
  white-space: pre-wrap;
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  flex: 1;
}

.card-foot {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed #f0f2f5;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-foot-hint {
  font-size: 12px;
  color: #d3d6db;
}

/* 右上角三个点(浅色) */
.more-btn {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #c0c4cc;
  cursor: pointer;
  transition: all 0.2s ease;
}

.more-btn:hover {
  background: #ecf5ff;
  color: var(--el-color-primary);
}

/* 右下角浅红色小垃圾桶 */
.del-btn {
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 8px;
  background: #fef0f0;
  color: #f89898;
  cursor: pointer;
  transition: all 0.2s ease;
}

.del-btn:hover {
  background: #fde2e2;
  color: #f56c6c;
}

.grid-empty {
  grid-column: 1 / -1;
}
</style>
