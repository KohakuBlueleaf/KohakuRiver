/**
 * Tasks Store - Manages task state and operations.
 *
 * Provides:
 * - Task list with filtering by status
 * - Task submission and lifecycle operations (kill, pause, resume, restart)
 * - Task logs retrieval (stdout/stderr)
 * - Computed properties for running, pending, and completed tasks
 */

import { defineStore } from 'pinia'

import { useLoadingStore } from '@/stores/loading'

import { tasksAPI } from '@/utils/api'

export const useTasksStore = defineStore('tasks', () => {
  const loadingStore = useLoadingStore()
  // State
  const tasks = ref([])
  const currentTask = ref(null)
  const loading = ref(false)
  const submitting = ref(false)
  const error = ref(null)
  /** @type {import('vue').Ref<boolean>} */
  const initialized = ref(false)

  // Getters
  const runningTasks = computed(() => tasks.value.filter((t) => t.status === 'running'))

  const pendingTasks = computed(() => tasks.value.filter((t) => t.status === 'pending' || t.status === 'assigning'))

  const completedTasks = computed(() =>
    tasks.value.filter((t) => ['completed', 'failed', 'killed', 'killed_oom'].includes(t.status))
  )

  // Actions
  async function fetchTasks(params = {}) {
    if (!initialized.value) {
      loading.value = true
    }
    error.value = null
    try {
      const { data } = await tasksAPI.list(params)
      tasks.value = data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      console.error('Failed to fetch tasks:', e)
    } finally {
      loading.value = false
      initialized.value = true
    }
  }

  async function fetchTask(taskId) {
    loading.value = true
    error.value = null
    try {
      const { data } = await tasksAPI.get(taskId)
      currentTask.value = data
      return data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      console.error('Failed to fetch task:', e)
      return null
    } finally {
      loading.value = false
    }
  }

  async function submitTask(taskData) {
    submitting.value = true
    error.value = null
    const opId = `submit-task-${Date.now()}`
    loadingStore.startLoading(opId, 'Submitting task...')
    try {
      const { data } = await tasksAPI.submit(taskData)
      // Refresh task list after submission
      await fetchTasks()
      return data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      console.error('Failed to submit task:', e)
      throw e
    } finally {
      submitting.value = false
      loadingStore.stopLoading(opId)
    }
  }

  async function killTask(taskId) {
    try {
      await tasksAPI.kill(taskId)
      // Update task in list
      const task = tasks.value.find((t) => t.task_id === taskId)
      if (task) {
        task.status = 'killed'
      }
      return true
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      console.error('Failed to kill task:', e)
      throw e
    }
  }

  async function pauseTask(taskId) {
    try {
      await tasksAPI.command(taskId, 'pause')
      const task = tasks.value.find((t) => t.task_id === taskId)
      if (task) {
        task.status = 'paused'
      }
      return true
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    }
  }

  async function resumeTask(taskId) {
    try {
      await tasksAPI.command(taskId, 'resume')
      const task = tasks.value.find((t) => t.task_id === taskId)
      if (task) {
        task.status = 'running'
      }
      return true
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    }
  }

  async function restartTask(taskId) {
    try {
      await tasksAPI.command(taskId, 'restart')
      // Refresh task list to get updated status
      await fetchTasks()
      return true
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    }
  }

  async function deleteTask(taskId) {
    try {
      await tasksAPI.delete(taskId)
      // Remove task from list
      tasks.value = tasks.value.filter((t) => t.task_id !== taskId)
      return true
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    }
  }

  async function getTaskLogs(taskId, type = 'stdout', lines = 100) {
    try {
      const { data } =
        type === 'stdout' ? await tasksAPI.getStdout(taskId, lines) : await tasksAPI.getStderr(taskId, lines)
      return data
    } catch (e) {
      console.error(`Failed to fetch ${type}:`, e)
      return ''
    }
  }

  return {
    // State
    tasks,
    currentTask,
    loading,
    submitting,
    error,
    // Getters
    runningTasks,
    pendingTasks,
    completedTasks,
    // Actions
    fetchTasks,
    fetchTask,
    submitTask,
    killTask,
    pauseTask,
    resumeTask,
    restartTask,
    deleteTask,
    getTaskLogs,
  }
})
