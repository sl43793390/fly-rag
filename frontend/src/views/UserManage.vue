<template>
  <div class="page">
    <div class="page-toolbar">
      <div>
        <h2 class="page-title">用户管理</h2>
        <p class="page-sub">管理系统用户、分配角色,基于 RBAC 控制访问</p>
      </div>
      <el-button
        v-if="auth.hasPermission('user:create')"
        type="primary"
        :icon="Plus"
        @click="openCreate"
      >
        新建用户
      </el-button>
    </div>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="users" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="用户名" min-width="140">
          <template #default="{ row }">
            <span class="user-name">{{ row.username }}</span>
            <el-tag v-if="row.remark" size="small" effect="plain" type="info" style="margin-left:8px">
              {{ row.remark }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="邮箱" min-width="180">
          <template #default="{ row }">{{ row.email || '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'danger'" effect="plain">
              {{ row.status === 'active' ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="角色" min-width="220">
          <template #default="{ row }">
            <el-tag
              v-for="r in row.roles"
              :key="r.id"
              size="small"
              effect="plain"
              style="margin-right: 6px"
            >
              {{ r.name }}
            </el-tag>
            <span v-if="!row.roles.length" class="muted">无</span>
          </template>
        </el-table-column>
        <el-table-column label="最近登录" width="160">
          <template #default="{ row }">{{ formatTime(row.last_login_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button
                v-if="auth.hasPermission('user:update')"
                link
                type="primary"
                :icon="Setting"
                @click="openRoles(row)"
              >
                分配角色
              </el-button>
              <el-button
                v-if="auth.hasPermission('user:update')"
                link
                :icon="Key"
                @click="openResetPwd(row)"
              >
                重置密码
              </el-button>
              <el-button
                v-if="auth.hasPermission('user:update')"
                link
                :icon="Edit"
                @click="openEdit(row)"
              >
                编辑
              </el-button>
              <el-button
                v-if="auth.hasPermission('user:delete')"
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
      </el-table>
    </el-card>

    <!-- 创建 / 编辑 -->
    <el-dialog
      v-model="dialog.visible"
      :title="dialog.isEdit ? '编辑用户' : '新建用户'"
      width="520px"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="dialog.isEdit" placeholder="登录名" maxlength="64" />
        </el-form-item>
        <el-form-item v-if="!dialog.isEdit" label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" placeholder="可选" maxlength="128" />
        </el-form-item>
        <el-form-item label="备注" prop="remark">
          <el-input v-model="form.remark" placeholder="可选" maxlength="255" />
        </el-form-item>
        <el-form-item v-if="dialog.isEdit" label="状态" prop="status">
          <el-radio-group v-model="form.status">
            <el-radio value="active">启用</el-radio>
            <el-radio value="disabled">禁用</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="角色" prop="role_ids">
          <el-select v-model="form.role_ids" multiple placeholder="选择角色" style="width: 100%">
            <el-option
              v-for="r in roles"
              :key="r.id"
              :value="r.id"
              :label="r.name"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- 分配角色 -->
    <el-dialog v-model="rolesDialog.visible" title="分配角色" width="460px" destroy-on-close>
      <p class="muted" style="margin: 0 0 12px">
        用户:{{ rolesDialog.username }}
      </p>
      <el-checkbox-group v-model="rolesDialog.role_ids">
        <div v-for="r in roles" :key="r.id" class="role-check">
          <el-checkbox :value="r.id">
            {{ r.name }} <span class="muted">({{ r.code }})</span>
          </el-checkbox>
          <div class="muted small">{{ r.description }}</div>
        </div>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="rolesDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="rolesDialog.saving" @click="onSaveRoles">保存</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码 -->
    <el-dialog v-model="pwdDialog.visible" title="重置密码" width="420px" destroy-on-close>
      <p class="muted">用户:{{ pwdDialog.username }}</p>
      <el-form :model="pwdForm" :rules="pwdRules" label-width="80px" ref="pwdFormRef">
        <el-form-item label="新密码" prop="password">
          <el-input v-model="pwdForm.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="pwdDialog.saving" @click="onSavePwd">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, Key, Plus, Setting } from '@element-plus/icons-vue'
import { userApi, roleApi } from '../api'
import { authStore as auth } from '../store/auth'
import { formatTime } from '../utils/format'

const loading = ref(false)
const users = ref([])
const roles = ref([])
const formRef = ref(null)
const pwdFormRef = ref(null)

const dialog = reactive({ visible: false, isEdit: false, saving: false, editId: null })
const form = reactive({
  username: '',
  password: '',
  email: '',
  remark: '',
  status: 'active',
  role_ids: [],
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '至少 6 位', trigger: 'blur' },
  ],
}

const rolesDialog = reactive({
  visible: false,
  saving: false,
  userId: null,
  username: '',
  role_ids: [],
})

const pwdDialog = reactive({ visible: false, saving: false, userId: null, username: '' })
const pwdForm = reactive({ password: '' })
const pwdRules = {
  password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '至少 6 位', trigger: 'blur' },
  ],
}

async function load() {
  loading.value = true
  try {
    const [u, r] = await Promise.all([userApi.list(), roleApi.list()])
    users.value = u
    roles.value = r
  } finally {
    loading.value = false
  }
}

function openCreate() {
  dialog.isEdit = false
  dialog.editId = null
  Object.assign(form, {
    username: '',
    password: '',
    email: '',
    remark: '',
    status: 'active',
    role_ids: [],
  })
  dialog.visible = true
}

function openEdit(row) {
  dialog.isEdit = true
  dialog.editId = row.id
  Object.assign(form, {
    username: row.username,
    password: '',
    email: row.email || '',
    remark: row.remark || '',
    status: row.status,
    role_ids: row.roles.map((r) => r.id),
  })
  dialog.visible = true
}

async function onSave() {
  await formRef.value.validate()
  dialog.saving = true
  try {
    if (dialog.isEdit) {
      await userApi.update(dialog.editId, {
        email: form.email,
        remark: form.remark,
        status: form.status,
      })
      if (form.role_ids.length) {
        await userApi.assignRoles(dialog.editId, form.role_ids)
      }
      ElMessage.success('用户已更新')
    } else {
      await userApi.create({
        username: form.username,
        password: form.password,
        email: form.email,
        remark: form.remark,
        role_ids: form.role_ids,
      })
      ElMessage.success('用户已创建')
    }
    dialog.visible = false
    await load()
  } finally {
    dialog.saving = false
  }
}

function openRoles(row) {
  rolesDialog.userId = row.id
  rolesDialog.username = row.username
  rolesDialog.role_ids = row.roles.map((r) => r.id)
  rolesDialog.visible = true
}

async function onSaveRoles() {
  rolesDialog.saving = true
  try {
    await userApi.assignRoles(rolesDialog.userId, rolesDialog.role_ids)
    ElMessage.success('角色已更新')
    rolesDialog.visible = false
    await load()
  } finally {
    rolesDialog.saving = false
  }
}

function openResetPwd(row) {
  pwdDialog.userId = row.id
  pwdDialog.username = row.username
  pwdForm.password = ''
  pwdDialog.visible = true
}

async function onSavePwd() {
  await pwdFormRef.value.validate()
  pwdDialog.saving = true
  try {
    await userApi.resetPassword(pwdDialog.userId, pwdForm.password)
    ElMessage.success('密码已重置')
    pwdDialog.visible = false
  } finally {
    pwdDialog.saving = false
  }
}

async function onRemove(row) {
  await ElMessageBox.confirm(`删除用户「${row.username}」?该操作不可恢复。`, '删除确认', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await userApi.remove(row.id)
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

.user-name {
  font-weight: 600;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}

/* flex gap 已负责按钮间距,覆盖 Element Plus 默认的 margin-left: 12px,
   避免固定列内容超宽导致"删除"按钮被裁切 */
.row-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.muted {
  color: #909399;
  font-size: 13px;
}

.small {
  font-size: 12px;
}

.role-check {
  padding: 4px 0;
  border-bottom: 1px dashed #ebeef5;
}

.role-check:last-child {
  border-bottom: none;
}
</style>
