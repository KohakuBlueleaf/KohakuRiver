/**
 * Cluster Store - Manages cluster node state and aggregated metrics.
 *
 * Provides:
 * - Node list with status, resources, and GPU info
 * - Aggregated cluster metrics (total cores, memory, GPUs)
 * - Health monitoring
 */

import { defineStore } from 'pinia'

import { nodesAPI } from '@/utils/api'

export const useClusterStore = defineStore('cluster', () => {
  // State
  const nodes = ref([])
  const health = ref(null)
  const loading = ref(false)
  const error = ref(null)

  // Getters
  const onlineNodes = computed(() => nodes.value.filter((n) => n.status === 'online'))

  const offlineNodes = computed(() => nodes.value.filter((n) => n.status === 'offline'))

  const totalCores = computed(() => onlineNodes.value.reduce((sum, n) => sum + (n.total_cores || 0), 0))

  const totalMemory = computed(() => onlineNodes.value.reduce((sum, n) => sum + (n.memory_total_bytes || 0), 0))

  const usedMemory = computed(() => onlineNodes.value.reduce((sum, n) => sum + (n.memory_used_bytes || 0), 0))

  const totalGpus = computed(() => onlineNodes.value.reduce((sum, n) => sum + (n.gpu_info?.length || 0), 0))

  const avgCpuPercent = computed(() => {
    const online = onlineNodes.value.filter((n) => n.cpu_percent !== null)
    if (online.length === 0) return 0
    return online.reduce((sum, n) => sum + n.cpu_percent, 0) / online.length
  })

  const avgMemoryPercent = computed(() => {
    const online = onlineNodes.value.filter((n) => n.memory_percent !== null)
    if (online.length === 0) return 0
    return online.reduce((sum, n) => sum + n.memory_percent, 0) / online.length
  })

  // Actions
  async function fetchNodes() {
    const isInitialLoad = nodes.value.length === 0
    if (isInitialLoad) {
      loading.value = true
    }
    error.value = null
    try {
      const { data } = await nodesAPI.getAll()
      nodes.value = data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      console.error('Failed to fetch nodes:', e)
    } finally {
      if (isInitialLoad) {
        loading.value = false
      }
    }
  }

  async function fetchHealth(hostname = null) {
    try {
      const { data } = await nodesAPI.getHealth(hostname)
      health.value = data
    } catch (e) {
      console.error('Failed to fetch health:', e)
    }
  }

  return {
    // State
    nodes,
    health,
    loading,
    error,
    // Getters
    onlineNodes,
    offlineNodes,
    totalCores,
    totalMemory,
    usedMemory,
    totalGpus,
    avgCpuPercent,
    avgMemoryPercent,
    // Actions
    fetchNodes,
    fetchHealth,
  }
})
