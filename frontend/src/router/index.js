import { createRouter, createWebHistory } from 'vue-router'
import { authStore } from '../store/auth'
import { authApi } from '../api'

const routes = [
  {
    path: '/',
    name: 'kb-list',
    component: () => import('../views/KnowledgeBase.vue'),
  },
  {
    path: '/kb/:id',
    name: 'kb-detail',
    component: () => import('../views/KbDetail.vue'),
  },
  {
    path: '/chat',
    name: 'chat',
    component: () => import('../views/ChatView.vue'),
  },
  {
    path: '/prompts',
    name: 'prompt-list',
    component: () => import('../views/PromptManage.vue'),
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/Login.vue'),
    meta: { public: true },
  },
  {
    path: '/users',
    name: 'user-list',
    component: () => import('../views/UserManage.vue'),
    meta: { requirePermission: 'user:read' },
  },
  {
    path: '/roles',
    name: 'role-list',
    component: () => import('../views/RoleManage.vue'),
    meta: { requirePermission: 'role:read' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  // 已登录访问登录页:直接回首页
  if (to.name === 'login') {
    return authStore.isLoggedIn.value ? { path: '/' } : true
  }
  // public 路由(如登录页)直接放行
  if (to.meta?.public) {
    return true
  }
  // 其余所有页面都需要登录:未登录跳登录页
  if (!authStore.isLoggedIn.value) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // 本地有登录态,但 token 尚未向后端校验过(典型场景:服务重启后刷新页面,
  // JWT 随机密钥已更换,旧 token 失效):先调 /auth/me 确认,失效即登出,
  // 避免"不登录直接进入主页"。
  if (!authStore.tokenChecked.value) {
    try {
      await authApi.me()
      authStore.tokenChecked.value = true
    } catch (err) {
      if (err?.response?.status === 401) {
        authStore.logout()
        return { path: '/login', query: { redirect: to.fullPath } }
      }
      // 非鉴权错误(如后端未启动的网络错误):不误杀登录态,
      // 放行进入页面,由页面内的请求提示"无法连接后端服务"。
    }
  }

  // 需要特定权限的路由:权限不足回首页
  const need = to.meta?.requirePermission
  if (need && !authStore.hasPermission(need)) {
    return { path: '/' }
  }
  return true
})

export default router
