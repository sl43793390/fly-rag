<template>
  <div class="page">
    <!-- 顶栏 -->
    <div class="page-toolbar">
      <div class="toolbar-left">
        <el-button :icon="ArrowLeft" circle text @click="$router.push('/')" />
        <div>
          <h2 class="page-title">{{ kb.name || '知识库' }}</h2>
          <p class="page-sub">
            {{ kb.description || '暂无描述' }}
            <el-tag size="small" effect="plain" style="margin-left: 8px">
              {{ splitterLabel(kb.splitter) }} · {{ kb.chunk_size }}/{{ kb.chunk_overlap }}
            </el-tag>
          </p>
        </div>
      </div>
      <el-button type="success" :icon="ChatDotRound" @click="goChat">开始对话</el-button>
    </div>

    <!-- 上传区 -->
    <el-card shadow="never" class="upload-card">
      <template #header>
        <div class="card-header">
          <span>上传文档</span>
          <span class="card-header-sub">
            支持 {{ acceptExts }};解析在后台进行,上传后可在下方列表查看进度
          </span>
        </div>
      </template>

      <el-form :inline="true" class="upload-form">
        <el-form-item label="切分器">
          <el-select v-model="uploadParams.splitter" style="width: 220px">
            <el-option
              v-for="opt in SPLITTER_OPTIONS"
              :key="opt.value"
              :value="opt.value"
              :label="opt.label"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="块大小">
          <el-input-number v-model="uploadParams.chunk_size" :min="100" :max="8192" :step="128" />
        </el-form-item>
        <el-form-item label="重叠大小">
          <el-input-number v-model="uploadParams.chunk_overlap" :min="0" :max="2048" :step="50" />
        </el-form-item>
      </el-form>

      <el-upload
        ref="uploadRef"
        drag
        multiple
        :auto-upload="false"
        :accept="accept"
        :on-change="onFileChange"
        :on-remove="onFileChange"
        :show-file-list="true"
      >
        <el-icon :size="42" color="#c0c4cc"><UploadFilled /></el-icon>
        <div class="el-upload__text">将文件拖到此处,或<em>点击选择(支持多选批量上传)</em></div>
      </el-upload>

      <div class="upload-actions">
        <el-button
          type="primary"
          :icon="Upload"
          :disabled="!pendingFiles.length"
          :loading="uploading"
          @click="doUpload"
        >
          上传 {{ pendingFiles.length ? `(${pendingFiles.length} 个文件)` : '' }}
        </el-button>
        <el-button v-if="pendingFiles.length" @click="clearFiles">清空选择</el-button>
      </div>
    </el-card>

    <!-- 文档列表 -->
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>文档列表</span>
          <el-button link :icon="Refresh" @click="loadDocs">刷新</el-button>
        </div>
      </template>

      <el-table v-loading="docsLoading" :data="docs" stripe>
        <el-table-column prop="file_name" label="文件名" min-width="220" show-overflow-tooltip />
        <el-table-column label="类型" width="80" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.file_ext || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="100" align="right">
          <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="docStatus(row.status).type" size="small">
              <el-icon
                v-if="row.status === 'processing' || row.status === 'pending'"
                class="is-loading"
                style="vertical-align: -2px; margin-right: 2px"
              ><Loading /></el-icon>
              {{ docStatus(row.status).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="node_count" label="节点数" width="90" align="center" />
        <el-table-column label="切分配置" width="150">
          <template #default="{ row }">
            <span class="dim">{{ row.splitter }} · {{ row.chunk_size }}/{{ row.chunk_overlap }}</span>
          </template>
        </el-table-column>
        <el-table-column label="说明" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span :class="row.status === 'failed' ? 'err' : 'dim'">
              {{ row.error_msg || '-' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="上传时间" width="150">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'failed'"
              link
              type="warning"
              :icon="RefreshRight"
              @click="onRetry(row)"
            >重试</el-button>
            <el-button link type="danger" :icon="Delete" @click="onRemove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="尚未上传文档" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowLeft,
  ChatDotRound,
  Delete,
  Loading,
  Refresh,
  RefreshRight,
  Upload,
  UploadFilled,
} from '@element-plus/icons-vue'
import { docApi, kbApi } from '../api'
import { SPLITTER_OPTIONS, docStatus, formatSize, formatTime, splitterLabel } from '../utils/format'

const route = useRoute()
const router = useRouter()
const kbId = Number(route.params.id)

const kb = reactive({})
const docs = ref([])
const docsLoading = ref(false)
const uploading = ref(false)
const uploadRef = ref(null)
const fileList = ref([])

const uploadParams = reactive({
  splitter: 'auto',
  chunk_size: 1024,
  chunk_overlap: 200,
})

const acceptExts = 'docx/xlsx/xls/pdf/txt/md/html/json/doc/ppt/pptx/rtf/epub/csv 等'
const accept = [
  '.docx', '.xlsx', '.xls', '.pdf', '.txt', '.md', '.markdown',
  '.html', '.htm', '.json', '.doc', '.docm', '.ppt', '.pptx', '.pptm',
  '.pps', '.ppsx', '.xlsm', '.xlsb', '.odt', '.ods', '.odp', '.rtf', '.epub', '.csv',
].join(',')

const pendingFiles = computed(() => fileList.value.map((f) => f.raw).filter(Boolean))

let pollTimer = null

async function loadKb() {
  const data = await kbApi.get(kbId)
  Object.assign(kb, data)
  // 上传表单默认跟随知识库配置
  uploadParams.splitter = data.splitter
  uploadParams.chunk_size = data.chunk_size
  uploadParams.chunk_overlap = data.chunk_overlap
}

async function loadDocs() {
  docsLoading.value = true
  try {
    docs.value = await docApi.list(kbId)
    schedulePoll()
  } finally {
    docsLoading.value = false
  }
}

/** 存在处理中的文档时轮询刷新(3s) */
function schedulePoll() {
  const busy = docs.value.some((d) => d.status === 'pending' || d.status === 'processing')
  if (busy && !pollTimer) {
    pollTimer = setInterval(async () => {
      docs.value = await docApi.list(kbId)
      const still = docs.value.some((d) => d.status === 'pending' || d.status === 'processing')
      if (!still) stopPoll()
    }, 3000)
  } else if (!busy) {
    stopPoll()
  }
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function onFileChange(_file, files) {
  fileList.value = files
}

function clearFiles() {
  uploadRef.value?.clearFiles()
  fileList.value = []
}

async function doUpload() {
  if (!pendingFiles.value.length) return
  uploading.value = true
  try {
    const result = await docApi.upload(kbId, pendingFiles.value, { ...uploadParams })
    const { accepted, rejected } = result
    if (accepted > 0) {
      ElMessage.success(`已提交 ${accepted} 个文件到后台解析队列`)
    }
    if (rejected?.length) {
      ElMessage.warning(`${rejected.length} 个文件被拒绝:${rejected.map((r) => `${r.file_name}(${r.reason})`).join(';')}`)
    }
    clearFiles()
    await loadDocs()
  } finally {
    uploading.value = false
  }
}

async function onRetry(row) {
  await docApi.retry(row.id)
  ElMessage.success('已重新提交解析')
  await loadDocs()
}

async function onRemove(row) {
  await ElMessageBox.confirm(
    `删除文档「${row.file_name}」将同时删除其向量数据与源文件,确定删除?`,
    '删除确认',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
  )
  await docApi.remove(row.id)
  ElMessage.success('已删除')
  await loadDocs()
}

function goChat() {
  router.push({ path: '/chat', query: { kb: kbId } })
}

onMounted(async () => {
  await loadKb()
  await loadDocs()
})

onBeforeUnmount(stopPoll)
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
  margin-bottom: 16px;
}

.toolbar-left {
  display: flex;
  align-items: flex-start;
  gap: 8px;
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

.upload-card {
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-header-sub {
  color: #909399;
  font-size: 12px;
  font-weight: normal;
}

.upload-form {
  margin-bottom: 4px;
}

.upload-actions {
  margin-top: 14px;
  display: flex;
  gap: 10px;
}

.dim {
  color: #909399;
  font-size: 12px;
}

.err {
  color: #f56c6c;
  font-size: 12px;
}
</style>
