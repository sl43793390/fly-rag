/**
 * 轻量认证 store(基于 localStorage + ref)。
 *
 * 设计要点:登录态(isLoggedIn)用 ref 显式同步,
 * 不依赖 computed —— computed 在 router 守卫这类"非响应式 effect 上下文"中
 * 缓存不会自动失效,会拿到旧值导致守卫误判(已登录却跳登录页)。
 * 用 ref + 在 setAuth/logout 中手动同步,保证 .value 任何位置都拿最新值。
 */
import { ref } from 'vue'
import {
  clearAuth,
  getUser,
  setAuth,
  hasPermission as rawHasPermission,
} from '../api'

export const authStore = {
  /** 当前用户(ref,模板中用 auth.user,JS 中用 auth.user.value) */
  user: ref(getUser()),
  /** 是否已登录(ref,显式同步,确保守卫中 .value 拿到最新值) */
  isLoggedIn: ref(!!getUser()),

  hasPermission(code) {
    return rawHasPermission(code)
  },

  setUser(user) {
    const existingToken = localStorage.getItem('kb_rag_token')
    setAuth(existingToken, user)
    this.user.value = user
    this.isLoggedIn.value = !!user
  },

  setAuth(token, user) {
    setAuth(token, user)
    this.user.value = user
    this.isLoggedIn.value = !!user
  },

  logout() {
    clearAuth()
    this.user.value = null
    this.isLoggedIn.value = false
  },
}
