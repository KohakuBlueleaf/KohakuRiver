import { defineStore } from 'pinia'
import { authAPI } from '@/utils/api/auth'

export const useAuthStore = defineStore('auth', () => {
  // State
  const user = ref(null)
  const isAuthenticated = ref(false)
  const authEnabled = ref(false)
  const isLoading = ref(true)
  const error = ref(null)

  // Computed
  const isAdmin = computed(() => user.value?.role === 'admin')
  const isOperator = computed(() => ['operator', 'admin'].includes(user.value?.role))
  const isUser = computed(() => ['user', 'operator', 'admin'].includes(user.value?.role))
  const isViewer = computed(() => ['viewer', 'user', 'operator', 'admin'].includes(user.value?.role))

  const username = computed(() => user.value?.username || '')
  const displayName = computed(() => user.value?.display_name || user.value?.username || '')
  const role = computed(() => user.value?.role || 'anony')

  // Actions
  async function checkAuthStatus() {
    try {
      const response = await authAPI.getStatus()
      authEnabled.value = response.data.auth_enabled
      return response.data
    } catch (err) {
      console.error('Failed to check auth status:', err)
      authEnabled.value = false
      return { auth_enabled: false }
    }
  }

  async function fetchUser() {
    if (!authEnabled.value) {
      // Auth disabled - treat as admin
      user.value = {
        id: 0,
        username: '_system',
        display_name: 'System (Auth Disabled)',
        role: 'admin',
        is_active: true,
      }
      isAuthenticated.value = true
      isLoading.value = false
      return true
    }

    try {
      const response = await authAPI.getMe()
      user.value = response.data
      // Anonymous users are not considered "authenticated" - they can visit login/register
      isAuthenticated.value = response.data.role !== 'anony'
      error.value = null
      return true
    } catch (err) {
      user.value = null
      isAuthenticated.value = false
      if (err.response?.status !== 401) {
        error.value = err.message
      }
      return false
    } finally {
      isLoading.value = false
    }
  }

  async function login(username, password) {
    try {
      isLoading.value = true
      error.value = null
      const response = await authAPI.login(username, password)
      user.value = response.data.user
      isAuthenticated.value = true
      return { success: true, user: response.data.user }
    } catch (err) {
      const message = err.response?.data?.detail || err.message
      error.value = message
      return { success: false, error: message }
    } finally {
      isLoading.value = false
    }
  }

  async function logout() {
    try {
      await authAPI.logout()
    } catch (err) {
      console.error('Logout error:', err)
    } finally {
      user.value = null
      isAuthenticated.value = false
    }
  }

  async function register(username, password, displayName, invitationToken) {
    try {
      isLoading.value = true
      error.value = null
      const response = await authAPI.register(username, password, displayName, invitationToken)
      user.value = response.data.user
      isAuthenticated.value = true
      return { success: true, user: response.data.user }
    } catch (err) {
      const message = err.response?.data?.detail || err.message
      error.value = message
      return { success: false, error: message }
    } finally {
      isLoading.value = false
    }
  }

  async function init() {
    isLoading.value = true
    await checkAuthStatus()
    await fetchUser()
  }

  function hasRole(requiredRole) {
    const roleHierarchy = ['anony', 'viewer', 'user', 'operator', 'admin']
    const userLevel = roleHierarchy.indexOf(role.value)
    const requiredLevel = roleHierarchy.indexOf(requiredRole)
    return userLevel >= requiredLevel
  }

  return {
    // State
    user,
    isAuthenticated,
    authEnabled,
    isLoading,
    error,
    // Getters
    isAdmin,
    isOperator,
    isUser,
    isViewer,
    username,
    displayName,
    role,
    // Actions
    checkAuthStatus,
    fetchUser,
    login,
    logout,
    register,
    init,
    hasRole,
  }
})
