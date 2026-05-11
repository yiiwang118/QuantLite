import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, saveAuth, clearAuth, getCurrentAuthUsername } from '@/api/client'

export const useAuthStore = defineStore('auth', () => {
  const username = ref<string | null>(getCurrentAuthUsername())
  const showLogin = ref(false)

  async function login(u: string, p: string): Promise<boolean> {
    saveAuth({ username: u, password: p })
    try {
      const r = await api.get('/me')
      username.value = r.data.username
      showLogin.value = false
      return true
    } catch (e) {
      clearAuth()
      username.value = null
      throw e
    }
  }

  function logout() {
    clearAuth()
    username.value = null
  }

  function requireLogin() {
    showLogin.value = true
  }

  return { username, showLogin, login, logout, requireLogin }
})
