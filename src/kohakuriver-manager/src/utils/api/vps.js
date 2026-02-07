import { apiClient } from './client'

export const vpsAPI = {
  /**
   * List all VPS instances
   */
  list() {
    return apiClient.get('/vps')
  },

  /**
   * List only active VPS instances
   */
  listActive() {
    return apiClient.get('/vps/status')
  },

  /**
   * Create a new VPS instance
   * @param {Object} data - VPS creation data
   * @param {number} data.required_cores - CPU cores
   * @param {number|null} data.required_memory_bytes - Memory limit
   * @param {string|null} data.target_hostname - Target node
   * @param {number|null} data.target_numa_node_id - Target NUMA node
   * @param {string|null} data.container_name - Container environment
   * @param {string} data.ssh_key_mode - 'none', 'upload', or 'generate'
   * @param {string|null} data.ssh_public_key - Public key for 'upload' mode
   * @param {boolean|null} data.privileged - Run with --privileged
   * @param {string[]|null} data.additional_mounts - Additional mounts
   * @param {number[]|null} data.required_gpus - GPU IDs
   */
  create(data) {
    return apiClient.post('/vps/create', data)
  },

  /**
   * Stop a VPS instance
   * @param {string|number} taskId
   */
  stop(taskId) {
    return apiClient.post(`/vps/stop/${taskId}`)
  },

  /**
   * Restart a VPS instance
   * @param {string|number} taskId
   */
  restart(taskId) {
    return apiClient.post(`/vps/restart/${taskId}`)
  },

  /**
   * Pause a VPS instance
   * @param {string|number} taskId
   */
  pause(taskId) {
    return apiClient.post(`/command/${taskId}/pause`)
  },

  /**
   * Resume a paused VPS instance
   * @param {string|number} taskId
   */
  resume(taskId) {
    return apiClient.post(`/command/${taskId}/resume`)
  },

  /**
   * List VM instances across all nodes (admin only)
   */
  listVmInstances() {
    return apiClient.get('/vps/vm-instances')
  },

  /**
   * Delete a VM instance directory (admin only)
   * @param {string|number} taskId
   * @param {string} hostname - Runner hostname (required for orphaned instances)
   * @param {boolean} force - Force delete even if QEMU is running
   */
  deleteVmInstance(taskId, hostname, force = false) {
    return apiClient.delete(`/vps/vm-instances/${taskId}`, {
      params: { hostname, force },
    })
  },
}

export default vpsAPI
