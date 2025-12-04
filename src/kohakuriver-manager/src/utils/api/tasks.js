import { apiClient, logClient } from './client'

export const tasksAPI = {
  /**
   * List tasks with optional filters
   * @param {Object} params - Query parameters
   * @param {string} params.status - Filter by status
   * @param {number} params.limit - Max results
   * @param {number} params.offset - Offset for pagination
   */
  list(params = {}) {
    return apiClient.get('/tasks', { params })
  },

  /**
   * Get task status by ID
   * @param {string|number} taskId
   */
  get(taskId) {
    return apiClient.get(`/status/${taskId}`)
  },

  /**
   * Submit new task(s)
   * @param {Object} data - Task submission data
   */
  submit(data) {
    return apiClient.post('/submit', data)
  },

  /**
   * Kill a running task
   * @param {string|number} taskId
   */
  kill(taskId) {
    return apiClient.post(`/kill/${taskId}`)
  },

  /**
   * Send command to task (pause/resume)
   * @param {string|number} taskId
   * @param {string} command - 'pause' or 'resume'
   */
  command(taskId, command) {
    return apiClient.post(`/command/${taskId}/${command}`)
  },

  /**
   * Get task stdout logs
   * @param {string|number} taskId
   * @param {number} lines - Number of lines to fetch
   */
  getStdout(taskId, lines = 100) {
    return logClient.get(`/tasks/${taskId}/stdout`, { params: { lines } })
  },

  /**
   * Get task stderr logs
   * @param {string|number} taskId
   * @param {number} lines - Number of lines to fetch
   */
  getStderr(taskId, lines = 100) {
    return logClient.get(`/tasks/${taskId}/stderr`, { params: { lines } })
  },

  /**
   * Delete a task (only non-running tasks)
   * @param {string|number} taskId
   */
  delete(taskId) {
    return apiClient.delete(`/tasks/${taskId}`)
  },
}

export default tasksAPI
