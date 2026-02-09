/**
 * VPS Store - Manages VPS instance state and lifecycle operations.
 *
 * Provides:
 * - VPS list with active/running filters
 * - VPS lifecycle operations (create, stop, restart, pause, resume)
 * - Loading state tracking with global loading indicator
 */

import { defineStore } from 'pinia'

import { useLoadingStore } from '@/stores/loading'

import { vpsAPI } from '@/utils/api'

export const useVpsStore = defineStore('vps', () => {
  const loadingStore = useLoadingStore()
  // State
  const vpsList = ref([])
  const currentVps = ref(null)
  const loading = ref(false)
  const creating = ref(false)
  const error = ref(null)
  /** @type {import('vue').Ref<boolean>} */
  const initialized = ref(false)

  // Getters
  const activeVps = computed(() =>
    vpsList.value.filter((v) => ['pending', 'assigning', 'running', 'paused'].includes(v.status))
  )

  const runningVps = computed(() => vpsList.value.filter((v) => v.status === 'running'))

  // Actions
  async function fetchVpsList(activeOnly = false) {
    if (!initialized.value) {
      loading.value = true
    }
    error.value = null
    try {
      const { data } = activeOnly ? await vpsAPI.listActive() : await vpsAPI.list()
      vpsList.value = data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      console.error('Failed to fetch VPS list:', e)
    } finally {
      loading.value = false
      initialized.value = true
    }
  }

  async function createVps(vpsData) {
    creating.value = true
    error.value = null
    const opId = `create-vps-${Date.now()}`
    loadingStore.startLoading(opId, 'Creating VPS instance...')
    try {
      const { data } = await vpsAPI.create(vpsData)
      // Refresh list after creation
      await fetchVpsList()
      return data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      console.error('Failed to create VPS:', e)
      throw e
    } finally {
      creating.value = false
      loadingStore.stopLoading(opId)
    }
  }

  async function stopVps(taskId) {
    try {
      await vpsAPI.stop(taskId)
      // Update in list
      const vps = vpsList.value.find((v) => v.task_id === taskId)
      if (vps) {
        vps.status = 'stopped'
      }
      return true
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    }
  }

  async function restartVps(taskId) {
    try {
      const { data } = await vpsAPI.restart(taskId)
      // Refresh list after restart
      await fetchVpsList()
      return data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    }
  }

  async function pauseVps(taskId) {
    try {
      await vpsAPI.pause(taskId)
      const vps = vpsList.value.find((v) => v.task_id === taskId)
      if (vps) {
        vps.status = 'paused'
      }
      return true
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    }
  }

  async function resumeVps(taskId) {
    try {
      await vpsAPI.resume(taskId)
      const vps = vpsList.value.find((v) => v.task_id === taskId)
      if (vps) {
        vps.status = 'running'
      }
      return true
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    }
  }

  return {
    // State
    vpsList,
    currentVps,
    loading,
    creating,
    error,
    // Getters
    activeVps,
    runningVps,
    // Actions
    fetchVpsList,
    createVps,
    stopVps,
    restartVps,
    pauseVps,
    resumeVps,
  }
})
