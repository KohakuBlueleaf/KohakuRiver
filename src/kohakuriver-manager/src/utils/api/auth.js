import apiClient from './client'

export const authAPI = {
  // Auth status
  getStatus() {
    return apiClient.get('/auth/status')
  },

  // Login/logout
  login(username, password) {
    return apiClient.post('/auth/login', { username, password })
  },

  logout() {
    return apiClient.post('/auth/logout')
  },

  // Current user
  getMe() {
    return apiClient.get('/auth/me')
  },

  // Registration
  register(username, password, displayName, token) {
    return apiClient.post(`/auth/register?token=${encodeURIComponent(token)}`, {
      username,
      password,
      display_name: displayName,
    })
  },

  // API Tokens
  listTokens() {
    return apiClient.get('/auth/tokens')
  },

  createToken(name) {
    return apiClient.post('/auth/tokens/create', { name })
  },

  revokeToken(tokenId) {
    return apiClient.delete(`/auth/tokens/${tokenId}`)
  },

  // Invitations (admin)
  listInvitations() {
    return apiClient.get('/auth/invitations')
  },

  createInvitation(role = 'user', maxUsage = 1, expiresHours = 72, groupId = null) {
    return apiClient.post('/auth/invitations', {
      role,
      max_usage: maxUsage,
      expires_hours: expiresHours,
      group_id: groupId,
    })
  },

  revokeInvitation(invitationId) {
    return apiClient.delete(`/auth/invitations/${invitationId}`)
  },

  // User management (admin)
  listUsers() {
    return apiClient.get('/auth/users')
  },

  updateUser(userId, updates) {
    return apiClient.patch(`/auth/users/${userId}`, updates)
  },

  deleteUser(userId) {
    return apiClient.delete(`/auth/users/${userId}`)
  },
}

export default authAPI
