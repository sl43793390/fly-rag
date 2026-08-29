<template>
  <div class="page">
    <div class="page-toolbar">
      <div>
        <h2 class="page-title">知识库管理</h2>
        <p class="page-sub">创建知识库,上传文档并指定切分参数,之后即可开启 RAG 对话</p>
      </div>
      <el-button
        v-if="auth.hasPermission('kb:create')"
        type="primary"
        :icon="Plus"
        @click="openCreate"
      >
        新建知识库
      </el-button>
    </div>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="kbs" stripe>
        <el-table-column label="名称" min-width="160">
          <template #default="{ row }">
            <span class="kb-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || '-' }}</template>
        </el-table-column>
        <el-table-column label="切分配置" width="200">
          <template #default="{ row }">
            <el-tooltip :content="`块大小 ${row.chunk_size} / 重叠 ${row.chunk_overlap}`" placement="top">
              <el-tag size="small" effect="plain">{{ splitterLabel(row.splitter) }}</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="检索方式" width="130">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.retrieval_mode === 'hybrid' && row.hybrid_ranker"
              :content="`融合排序: ${hybridRankerLabel(row.hybrid_ranker)}`"
              placement="top"
            >
              <el-tag size="small" :type="retrievalModeTag(row.retrieval_mode)">
                {{ retrievalModeShort(row.retrieval_mode) }}
              </el-tag>
            </el-tooltip>
            <el-tag v-else size="small" :type="retrievalModeTag(row.retrieval_mode)">
              {{ retrievalModeShort(row.retrieval_mode) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="文档" width="100" align="center">
          <template #default="{ row }">{{ row.doc_count }} 份</template>
        </el-table-column>
        <el-table-column label="节点" width="100" align="center">
          <template #default="{ row }">{{ row.node_count }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="150">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button link type="primary" :icon="FolderOpened" @click="goDetail(row.id)">文档</el-button>
              <el-button link type="success" :icon="ChatDotRound" @click="goChat(row.id)">对话</el-button>
              <el-button link :icon="Edit" @click="openEdit(row)">编辑</el-button>
              <el-button
                v-if="auth.hasPermission('kb:delete')"
                link
                type="danger"
                :icon="Delete"
                @click="onRemove(row)"
              >
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="还没有知识库,点击右上角「新建知识库」开始" />
        </template>
      </el-table>
    </el-card>

    <!-- 创建 / 编辑对话框 -->
    <el-dialog
      v-model="dialog.visible"
      :title="dialog.isEdit ? '编辑知识库' : '新建知识库'"
      width="520px"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="如:Oracle 运维知识库" maxlength="128" show-word-limit />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="2"
            placeholder="可选,简单介绍该知识库的用途"
            maxlength="512"
          />
        </el-form-item>
        <el-form-item label="切分器" prop="splitter">
          <el-select v-model="form.splitter" style="width: 100%">
            <el-option
              v-for="opt in SPLITTER_OPTIONS"
              :key="opt.value"
              :value="opt.value"
              :label="opt.label"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="块大小" prop="chunk_size">
          <el-input-number v-model="form.chunk_size" :min="100" :max="8192" :step="128" />
          <span class="form-tip">单个文本块的目标大小</span>
        </el-form-item>
        <el-form-item label="重叠大小" prop="chunk_overlap">
          <el-input-number v-model="form.chunk_overlap" :min="0" :max="2048" :step="50" />
          <span class="form-tip">相邻块之间的重叠</span>
        </el-form-item>
        <el-form-item label="检索方式" prop="retrieval_mode">
          <el-select v-model="form.retrieval_mode" style="width: 100%">
            <el-option
              v-for="opt in RETRIEVAL_MODE_OPTIONS"
              :key="opt.value"
              :value="opt.value"
              :label="opt.label"
            />
          </el-select>
          <div v-if="dialog.isEdit" class="form-tip-block">
            注意:已有文档的知识库从向量检索切换到全文/混合检索时,
            稀疏全文索引只对之后新上传的文档生效,建议重新上传文档。
          </div>
        </el-form-item>
        <template v-if="form.retrieval_mode === 'hybrid'">
          <el-form-item label="融合排序" prop="hybrid_ranker">
            <el-select v-model="form.hybrid_ranker" style="width: 100%">
              <el-option
                v-for="opt in HYBRID_RANKER_OPTIONS"
                :key="opt.value"
                :value="opt.value"
                :label="opt.label"
              />
            </el-select>
          </el-form-item>
          <el-form-item v-if="form.hybrid_ranker === 'RRFRanker'" label="RRF k">
            <el-input-number v-model="form.rrf_k" :min="1" :max="1000" :step="10" />
            <span class="form-tip">平滑因子,越大各路排名差异越平滑,默认 60</span>
          </el-form-item>
          <el-form-item v-else label="融合权重">
            <el-input-number v-model="form.weight_dense" :min="0" :max="10" :step="0.1" />
            <span class="form-tip">向量</span>
            <el-input-number
              v-model="form.weight_sparse"
              :min="0"
              :max="10"
              :step="0.1"
              style="margin-left: 8px"
            />
            <span class="form-tip">BM25</span>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatDotRound,
  Delete,
  Edit,
  FolderOpened,
  Plus,
} from '@element-plus/icons-vue'
import { kbApi } from '../api'
import { authStore as auth } from '../store/auth'
import {
  HYBRID_RANKER_OPTIONS,
  RETRIEVAL_MODE_OPTIONS,
  SPLITTER_OPTIONS,
  formatTime,
  hybridRankerLabel,
  retrievalModeShort,
  retrievalModeTag,
  splitterLabel,
} from '../utils/format'

const router = useRouter()
const loading = ref(false)
const kbs = ref([])
const formRef = ref(null)

const dialog = reactive({ visible: false, isEdit: false, saving: false, editId: null })

const form = reactive({
  name: '',
  description: '',
  splitter: 'auto',
  chunk_size: 1024,
  chunk_overlap: 200,
  retrieval_mode: 'dense',
  hybrid_ranker: 'RRFRanker',
  rrf_k: 60,
  weight_dense: 1.0,
  weight_sparse: 1.0,
})

const rules = {
  name: [{ required: true, message: '请输入知识库名称', trigger: 'blur' }],
  chunk_size: [{ required: true, message: '请输入块大小', trigger: 'blur' }],
}

/** 把表单状态转成后端 KbCreate / KbUpdate 结构(分离排序器参数) */
function buildPayload() {
  const payload = {
    name: form.name,
    description: form.description,
    splitter: form.splitter,
    chunk_size: form.chunk_size,
    chunk_overlap: form.chunk_overlap,
    retrieval_mode: form.retrieval_mode,
    hybrid_ranker: null,
    hybrid_ranker_params: null,
  }
  if (form.retrieval_mode === 'hybrid') {
    payload.hybrid_ranker = form.hybrid_ranker
    payload.hybrid_ranker_params =
      form.hybrid_ranker === 'RRFRanker'
        ? { k: form.rrf_k }
        : { weights: [form.weight_dense, form.weight_sparse] }
  }
  return payload
}

async function load() {
  loading.value = true
  try {
    kbs.value = await kbApi.list()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  dialog.isEdit = false
  dialog.editId = null
  Object.assign(form, {
    name: '',
    description: '',
    splitter: 'auto',
    chunk_size: 1024,
    chunk_overlap: 200,
    retrieval_mode: 'dense',
    hybrid_ranker: 'RRFRanker',
    rrf_k: 60,
    weight_dense: 1.0,
    weight_sparse: 1.0,
  })
  dialog.visible = true
}

function openEdit(row) {
  dialog.isEdit = true
  dialog.editId = row.id
  const params = row.hybrid_ranker_params || {}
  Object.assign(form, {
    name: row.name,
    description: row.description || '',
    splitter: row.splitter,
    chunk_size: row.chunk_size,
    chunk_overlap: row.chunk_overlap,
    retrieval_mode: row.retrieval_mode || 'dense',
    hybrid_ranker: row.hybrid_ranker || 'RRFRanker',
    rrf_k: params.k ?? 60,
    weight_dense: params.weights?.[0] ?? 1.0,
    weight_sparse: params.weights?.[1] ?? 1.0,
  })
  dialog.visible = true
}

async function onSave() {
  await formRef.value.validate()
  dialog.saving = true
  try {
    const payload = buildPayload()
    if (dialog.isEdit) {
      await kbApi.update(dialog.editId, payload)
      ElMessage.success('知识库已更新')
    } else {
      await kbApi.create(payload)
      ElMessage.success('知识库创建成功,可进入「文档」上传资料')
    }
    dialog.visible = false
    await load()
  } finally {
    dialog.saving = false
  }
}

async function onRemove(row) {
  await ElMessageBox.confirm(
    `删除知识库「${row.name}」将同时删除其全部文档、Milvus 向量数据与对话记录,且不可恢复。确定删除?`,
    '删除确认',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
  )
  await kbApi.remove(row.id)
  ElMessage.success('已删除')
  await load()
}

function goDetail(id) {
  router.push(`/kb/${id}`)
}

function goChat(kbId) {
  router.push({ path: '/chat', query: { kb: kbId } })
}

onMounted(load)
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

.page-title {
  margin: 0 0 4px;
  font-size: 20px;
}

.page-sub {
  margin: 0;
  color: #909399;
  font-size: 13px;
}

.kb-name {
  font-weight: 600;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}

.form-tip {
  margin-left: 10px;
  color: #909399;
  font-size: 12px;
}

.form-tip-block {
  width: 100%;
  margin-top: 4px;
  line-height: 1.5;
  color: #e6a23c;
  font-size: 12px;
}
</style>
