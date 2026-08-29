<template>
  <el-container class="app-shell">
    <el-header class="app-header">
      <div class="brand" @click="$router.push('/')">
        <el-icon :size="22"><Collection /></el-icon>
        <span>fly-RAG 平台</span>
      </div>
      <el-menu
        mode="horizontal"
        :default-active="activeMenu"
        :ellipsis="false"
        router
        class="nav-menu"
      >
        <el-menu-item index="/">知识库</el-menu-item>
        <el-menu-item index="/chat">对话</el-menu-item>
        <el-menu-item v-if="auth.isLoggedIn.value" index="/prompts">提示词</el-menu-item>
        <el-menu-item v-if="auth.isLoggedIn.value && auth.hasPermission('user:read')" index="/users">
          用户管理
        </el-menu-item>
        <el-menu-item v-if="auth.isLoggedIn.value && auth.hasPermission('role:read')" index="/roles">
          角色管理
        </el-menu-item>
      </el-menu>

      <div class="header-right">
        <template v-if="auth.isLoggedIn.value">
          <el-dropdown @command="onUserCommand">
            <span class="user-chip">
              <el-icon><User /></el-icon>
              <span>{{ auth.user.value?.username }}</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="changePwd">修改密码</el-dropdown-item>
                <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <!-- 用户名右侧:一键退出系统按钮 -->
          <el-tooltip content="退出系统" placement="bottom">
            <el-button
              class="logout-btn"
              :icon="SwitchButton"
              circle
              text
              type="danger"
              @click="onLogout"
            />
          </el-tooltip>
        </template>
        <el-button v-else type="primary" plain size="small" @click="$router.push('/login')">
          登录
        </el-button>
      </div>
    </el-header>

    <el-main class="app-main">
      <router-view />
    </el-main>

    <!-- 修改密码对话框 -->
    <el-dialog v-model="pwdDialog.visible" title="修改密码" width="420px" destroy-on-close>
      <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="80px">
        <el-form-item label="原密码" prop="old">
          <el-input v-model="pwdForm.old" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码" prop="new">
          <el-input v-model="pwdForm.new" type="password" show-password />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirm">
          <el-input v-model="pwdForm.confirm" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="pwdDialog.saving" @click="onSavePwd">确认</el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowDown, Collection, SwitchButton, User } from '@element-plus/icons-vue'
import { authStore as auth } from './store/auth'
import { authApi } from './api'

const route = useRoute()
const router = useRouter()

const activeMenu = computed(() => {
  if (route.path.startsWith('/chat')) return '/chat'
  if (route.path.startsWith('/prompts')) return '/prompts'
  if (route.path.startsWith('/users')) return '/users'
  if (route.path.startsWith('/roles')) return '/roles'
  return route.path
})

const pwdDialog = reactive({ visible: false, saving: false })
const pwdFormRef = ref(null)
const pwdForm = reactive({ old: '', new: '', confirm: '' })
const pwdRules = {
  old: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '至少 6 位', trigger: 'blur' },
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_, val, cb) => (val === pwdForm.new ? cb() : cb(new Error('两次密码不一致'))),
      trigger: 'blur',
    },
  ],
}

/** 退出登录:清登录态并回登录页(下拉菜单与用户名右侧按钮共用) */
function onLogout() {
  auth.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}

function onUserCommand(cmd) {
  if (cmd === 'logout') {
    onLogout()
  } else if (cmd === 'changePwd') {
    Object.assign(pwdForm, { old: '', new: '', confirm: '' })
    pwdDialog.visible = true
  }
}

async function onSavePwd() {
  await pwdFormRef.value.validate()
  pwdDialog.saving = true
  try {
    await authApi.changePassword(pwdForm.old, pwdForm.new)
    ElMessage.success('密码已修改,请重新登录')
    pwdDialog.visible = false
    auth.logout()
    router.push('/login')
  } finally {
    pwdDialog.saving = false
  }
}
</script>

<style>
html,
body,
#app {
  height: 100%;
  margin: 0;
  background: #f5f7fa;
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif;
}

.app-shell {
  height: 100%;
  background: linear-gradient(180deg, #f5f7fa 0%, #eef1f6 100%);
}

.app-header {
  display: flex;
  align-items: center;
  gap: 24px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid #e4e7ed;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.06);
  position: sticky;
  top: 0;
  z-index: 20;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 600;
  color: #409eff;
  cursor: pointer;
  white-space: nowrap;
}

.brand .el-icon {
  background: linear-gradient(135deg, #409eff 0%, #7c4dff 100%);
  color: #fff;
  border-radius: 8px;
  padding: 5px;
  box-shadow: 0 3px 8px rgba(64, 158, 255, 0.28);
}

.nav-menu {
  border-bottom: none;
  flex: 1;
}

.nav-menu .el-menu-item {
  transition: color 0.2s ease, background-color 0.2s ease;
  border-radius: 8px;
  margin: 0 2px;
}

.nav-menu .el-menu-item:hover {
  background: #f5f7fa;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* 用户名右侧退出按钮:与用户名保持小间距 */
.logout-btn {
  margin-left: 2px;
}

.user-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  color: #303133;
  font-size: 14px;
  padding: 4px 10px;
  border-radius: 8px;
  transition: background-color 0.2s ease;
}

.user-chip:hover {
  background: #f5f7fa;
}

.app-main {
  padding: 0;
  height: calc(100% - 60px);
  overflow: auto;
}

/* 全局:卡片与弹窗圆角、过渡更柔和 */
.el-card {
  border-radius: 12px;
  border: 1px solid #ebeef5;
}

.el-dialog {
  border-radius: 14px;
}

.el-message-box {
  border-radius: 12px;
}

/* 页面进入淡入 */
.fade-enter-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from {
  opacity: 0;
}
</style>
