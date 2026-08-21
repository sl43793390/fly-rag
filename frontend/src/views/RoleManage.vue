<template>
  <div class="page">
    <div class="page-toolbar">
      <div>
        <h2 class="page-title">角色管理</h2>
        <p class="page-sub">基于 RBAC 的角色与权限配置,角色绑定权限,用户绑定角色</p>
      </div>
      <el-button
        v-if="auth.hasPermission('role:create')"
        type="primary"
        :icon="Plus"
        @click="openCreate"
      >
        新建角色
      </el-button>
    </div>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="roles" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="角色" min-width="160">
          <template #default="{ row }">
            <span class="role-name">{{ row.name }}</span>
            <span class="muted"> ({{ row.code }})</span>
            <el-tag v-if="isBuiltin(row.code)" size="small" type="warning" style="margin-left:8px">
              内置
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="180">
          <template #default="{ row }">{{ row.description || '-' }}</template>
        </el-table-column>
        <el-table-column label="权限" min-width="280">
          <template #default="{ row }">
            <el-tag
              v-for="p in row.permissions"
              :key="p.id"
              size="small"
              effect="plain"
              style="margin-right: 6px; margin-bottom: 4px"
            >
              {{ p.code }}
            </el-tag>
            <span v-if="!row.permissions.length" class="muted">无</span>
          </template>
        </el-table-column>
        <el-table-column label="用户数" width="90" align="center">
          <template #default="{ row }">{{ row.user_count }}</template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="auth.hasPermission('role:update')"
              link
              type="primary"
              :icon="Setting"
              @click="openPerms(row)"
            >
              分配权限
            </el-button>
            <el-button
              v-if="auth.hasPermission('role:update')"
              link
              :icon="Edit"
              @click="openEdit(row)"
            >
              编辑
            </el-button>
            <el-button
              v-if="auth.hasPermission('role:delete')"
              link
              type="danger"
              :icon="Delete"
              :disabled="isBuiltin(row.code)"
              @click="onRemove(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 创建 / 编辑 -->
    <el-dialog
      v-model="dialog.visible"
      :title="dialog.isEdit ? '编辑角色' : '新建角色'"
      width="500px"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" maxlength="64" placeholder="如:对话用户" />
        </el-form-item>
        <el-form-item v-if="!dialog.isEdit" label="编码" prop="code">
          <el-input v-model="form.code" maxlength="64" placeholder="如:chat_user" />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input v-model="form.description" type="textarea" :rows="2" maxlength="255" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- 分配权限 -->
    <el-dialog v-model="permsDialog.visible" title="分配权限" width="560px" destroy-on-close>
      <p class="muted" style="margin: 0 0 12px">
        角色:{{ permsDialog.roleName }}({{ permsDialog.roleCode }})
      </p>
      <div class="perm-grid">
        <div v-for="p in permissions" :key="p.id" class="perm-card">
          <el-checkbox :model-value="permsDialog.perm_ids.includes(p.id)" @change="(v) => togglePerm(p.id, v)">
            <div>
              <span class="perm-code">{{ p.code }}</span>
              <div class="muted small">{{ p.name }}{{ p.description ? ' · ' + p.description : '' }}</div>
            </div>
          </el-checkbox>
        </div>
      </div>
      <template #footer>
        <el-button @click="permsDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="permsDialog.saving" @click="onSavePerms">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, Plus, Setting } from '@element-plus/icons-vue'
import { roleApi, permApi } from '../api'
import { authStore as auth } from '../store/auth'

const BUILTIN_CODES = ['admin', 'kb_manager', 'chat_user']

const loading = ref(false)
const roles = ref([])
const permissions = ref([])
const formRef = ref(null)

const dialog = reactive({ visible: false, isEdit: false, saving: false, editId: null })
const form = reactive({ name: '', code: '', description: '' })
const rules = {
  name: [{ required: true, message: '请输入角色名称', trigger: 'blur' }],
  code: [{ required: true, message: '请输入角色编码', trigger: 'blur' }],
}

const permsDialog = reactive({
  visible: false,
  saving: false,
  roleId: null,
  roleName: '',
  roleCode: '',
  perm_ids: [],
})

function isBuiltin(code) {
  return BUILTIN_CODES.includes(code)
}

async function load() {
  loading.value = true
  try {
    const [r, p] = await Promise.all([roleApi.list(), permApi.list()])
    roles.value = r
    permissions.value = p
  } finally {
    loading.value = false
  }
}

function openCreate() {
  dialog.isEdit = false
  dialog.editId = null
  Object.assign(form, { name: '', code: '', description: '' })
  dialog.visible = true
}

function openEdit(row) {
  dialog.isEdit = true
  dialog.editId = row.id
  Object.assign(form, {
    name: row.name,
    code: row.code,
    description: row.description || '',
  })
  dialog.visible = true
}

async function onSave() {
  await formRef.value.validate()
  dialog.saving = true
  try {
    if (dialog.isEdit) {
      await roleApi.update(dialog.editId, { name: form.name, description: form.description })
      ElMessage.success('角色已更新')
    } else {
      await roleApi.create({ ...form })
      ElMessage.success('角色已创建')
    }
    dialog.visible = false
    await load()
  } finally {
    dialog.saving = false
  }
}

function openPerms(row) {
  permsDialog.roleId = row.id
  permsDialog.roleName = row.name
  permsDialog.roleCode = row.code
  permsDialog.perm_ids = row.permissions.map((p) => p.id)
  permsDialog.visible = true
}

function togglePerm(id, checked) {
  if (checked) {
    if (!permsDialog.perm_ids.includes(id)) permsDialog.perm_ids.push(id)
  } else {
    permsDialog.perm_ids = permsDialog.perm_ids.filter((x) => x !== id)
  }
}

async function onSavePerms() {
  permsDialog.saving = true
  try {
    await roleApi.assignPermissions(permsDialog.roleId, permsDialog.perm_ids)
    ElMessage.success('权限已更新')
    permsDialog.visible = false
    await load()
  } finally {
    permsDialog.saving = false
  }
}

async function onRemove(row) {
  await ElMessageBox.confirm(`删除角色「${row.name}」?该操作不可恢复。`, '删除确认', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await roleApi.remove(row.id)
  ElMessage.success('已删除')
  await load()
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

.role-name {
  font-weight: 600;
}

.muted {
  color: #909399;
  font-size: 13px;
}

.small {
  font-size: 12px;
}

.perm-grid {
  max-height: 420px;
  overflow: auto;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.perm-card {
  padding: 8px 10px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
}

.perm-code {
  font-weight: 600;
  color: #409eff;
}
</style>
