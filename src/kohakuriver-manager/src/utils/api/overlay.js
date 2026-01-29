/**
 * Overlay Network API Module
 *
 * Provides functions to interact with the VXLAN overlay network endpoints.
 */

import apiClient from './client'

export const overlayAPI = {
  /**
   * Get overlay network status and allocations.
   * @returns {Promise<Object>} Overlay status with allocations
   */
  getStatus: () => apiClient.get('/overlay/status'),

  /**
   * Release overlay allocation for a runner.
   * WARNING: This will disconnect the runner from the overlay network.
   * @param {string} runnerName - Runner hostname
   * @returns {Promise<Object>} Release result
   */
  release: (runnerName) => apiClient.post(`/overlay/release/${encodeURIComponent(runnerName)}`),

  /**
   * Cleanup all inactive overlay allocations.
   * WARNING: This removes VXLAN tunnels for all inactive runners.
   * @returns {Promise<Object>} Cleanup result with cleaned_count
   */
  cleanup: () => apiClient.post('/overlay/cleanup'),

  // ==========================================================================
  // IP Reservation APIs
  // ==========================================================================

  /**
   * Get available IPs for reservation.
   * @param {string|null} runner - Optional runner hostname filter
   * @param {number} limit - Max IPs per runner (default 100)
   * @returns {Promise<Object>} Available IPs grouped by runner
   */
  getAvailableIps: (runner = null, limit = 100) => {
    const params = { limit }
    if (runner) params.runner = runner
    return apiClient.get('/nodes/overlay/ip/available', { params })
  },

  /**
   * Get IP info for a specific runner.
   * @param {string} runnerName - Runner hostname
   * @returns {Promise<Object>} IP allocation info (subnet, gateway, range, counts)
   */
  getRunnerIpInfo: (runnerName) => apiClient.get(`/nodes/overlay/ip/info/${encodeURIComponent(runnerName)}`),

  /**
   * Reserve an IP address on a runner.
   * @param {string} runner - Runner hostname
   * @param {string|null} ip - Specific IP to reserve (optional)
   * @param {number} ttl - Time-to-live in seconds (default 300)
   * @returns {Promise<Object>} Reservation result with token
   */
  reserveIp: (runner, ip = null, ttl = 300) => {
    const data = { runner, ttl }
    if (ip) data.ip = ip
    return apiClient.post('/nodes/overlay/ip/reserve', data)
  },

  /**
   * Release an IP reservation by token.
   * @param {string} token - Reservation token
   * @returns {Promise<Object>} Release result
   */
  releaseIpReservation: (token) => apiClient.post('/nodes/overlay/ip/release', { token }),

  /**
   * List active IP reservations.
   * @param {string|null} runner - Optional runner hostname filter
   * @returns {Promise<Object>} Active reservations
   */
  listIpReservations: (runner = null) => {
    const params = {}
    if (runner) params.runner = runner
    return apiClient.get('/nodes/overlay/ip/reservations', { params })
  },

  /**
   * Validate an IP reservation token.
   * @param {string} token - Reservation token
   * @param {string|null} runner - Expected runner hostname (optional)
   * @returns {Promise<Object>} Validation result
   */
  validateIpToken: (token, runner = null) => {
    const data = { token }
    if (runner) data.runner = runner
    return apiClient.post('/nodes/overlay/ip/validate', data)
  },
}

export default overlayAPI
