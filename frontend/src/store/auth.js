/**
 * 轻量认证 store(基于 localStorage + ref)。
 *
 * 设计要点:登录态(isLoggedIn)用 ref 显式同步,
 * 不依赖 computed —— computed 在 router 守卫这类"非响应式 effect 上下文"中
 * 缓存不会自动失效,会拿到旧值导致守卫误判(已登录却跳登录页)。
 * 用 ref + 在 setAuth/logout 中手动同步,保证 .value 任何位置都拿最新值。
 *
 * tokenChecked:本地登录态是否已向后端校验过(/auth/me)。
 * 后端 JWT 密钥默认随服务重启更换,重启后 localStorage 里的旧 token 已失效,
 * 但本地仍有登录信息 —— 守卫据此判断是否需要先向后端确认,失效即登出,
 * 避免"不登录直接进入主页"。
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
  /** 本地登录态是否已经后端校验(登录成功即视为已校验) */
  tokenChecked: ref(false),

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
    // 登录接口本身就是校验,新签发的 token 无需再向 /auth/me 确认
    this.tokenChecked.value = true
  },

  logout() {
    clearAuth()
    this.user.value = null
    this.isLoggedIn.value = false
    this.tokenChecked.value = false
  },
}
