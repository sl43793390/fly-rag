<template>
  <div class="login-page">
    <el-card class="login-card" shadow="always">
      <div class="login-title">
        <el-icon :size="26" color="#409eff"><Collection /></el-icon>
        <span>知识库 fly-RAG 平台</span>
      </div>
      <p class="login-sub">登录后即可使用对话并保留历史</p>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="0" @submit.prevent>
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            :prefix-icon="User"
            placeholder="用户名"
            size="large"
            autocomplete="username"
            @keyup.enter="onLogin"
          />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            :prefix-icon="Lock"
            type="password"
            show-password
            placeholder="密码"
            size="large"
            autocomplete="current-password"
            @keyup.enter="onLogin"
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          :loading="loading"
          style="width: 100%"
          @click="onLogin"
        >
          登录
        </el-button>
      </el-form>
      <p class="login-hint"></p>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Collection, Lock, User } from '@element-plus/icons-vue'
import { authApi } from '../api'
import { authStore } from '../store/auth'

const router = useRouter()
const route = useRoute()

const formRef = ref(null)
const loading = ref(false)
const form = reactive({ username: 'admin', password: '' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function onLogin() {
  await formRef.value.validate()
  loading.value = true
  try {
    const resp = await authApi.login(form.username, form.password)
    authStore.setAuth(resp.access_token, resp.user)
    ElMessage.success(`欢迎,${resp.user.username}`)
    const redirect = route.query.redirect || '/'
    router.push(redirect)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #eef2f8 0%, #d9e2f1 100%);
}

.login-card {
  width: 380px;
  padding: 24px 18px 16px;
}

.login-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 20px;
  font-weight: 600;
  color: #303133;
  justify-content: center;
}

.login-sub {
  text-align: center;
  color: #909399;
  font-size: 13px;
  margin: 8px 0 20px;
}

.login-hint {
  margin-top: 14px;
  font-size: 12px;
  color: #c0c4cc;
  text-align: center;
}
</style>
