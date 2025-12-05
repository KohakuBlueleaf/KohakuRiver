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
}

export default overlayAPI
