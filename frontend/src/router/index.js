import { createRouter, createWebHistory } from 'vue-router'
import { authStore } from '../store/auth'

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

router.beforeEach((to) => {
  // 已登录访问登录页:直接回首页
  if (to.name === 'login' && authStore.isLoggedIn.value) {
    return { path: '/' }
  }
  // public 路由(如登录页)直接放行
  if (to.meta?.public) {
    return true
  }
  // 其余所有页面都需要登录:未登录跳登录页
  if (!authStore.isLoggedIn.value) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  // 需要特定权限的路由:权限不足回首页
  const need = to.meta?.requirePermission
  if (need && !authStore.hasPermission(need)) {
    return { path: '/' }
  }
  return true
})

export default router
