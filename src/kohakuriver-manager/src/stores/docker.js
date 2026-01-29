/**
 * Docker Store - Manages Docker containers and tarballs state.
 *
 * Provides:
 * - Container CRUD operations (create, start, stop, delete)
 * - Tarball management for environment distribution
 * - Image listing
 * - Loading state tracking with global loading indicator
 */

import { defineStore } from 'pinia'

import { useLoadingStore } from '@/stores/loading'

import { dockerAPI } from '@/utils/api'

export const useDockerStore = defineStore('docker', () => {
  const loadingStore = useLoadingStore()
  // State
  const containers = ref([])
  const tarballs = ref([])
  const images = ref([])
  const loading = ref(false)
  const error = ref(null)

  // Getters
  const runningContainers = computed(() => containers.value.filter((c) => c.status === 'running'))

  const stoppedContainers = computed(() => containers.value.filter((c) => c.status !== 'running'))

  // Actions
  async function fetchContainers() {
    const isInitialLoad = containers.value.length === 0
    if (isInitialLoad) {
      loading.value = true
    }
    error.value = null
    try {
      const { data } = await dockerAPI.listContainers()
      containers.value = data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      console.error('Failed to fetch containers:', e)
    } finally {
      if (isInitialLoad) {
        loading.value = false
      }
    }
  }

  async function fetchTarballs() {
    try {
      const { data } = await dockerAPI.listTarballs()
      // Transform object format to array for easier rendering
      // Backend returns: { name: { latest_timestamp, latest_tarball, all_versions: [{timestamp, tarball, size_bytes}] } }
      // Transform to: [{ name, versions, size, created }]
      tarballs.value = Object.entries(data || {}).map(([name, info]) => ({
        name,
        versions: info.all_versions || [],
        size: info.all_versions?.[0]?.size_bytes || 0,
        created: info.latest_timestamp ? new Date(info.latest_timestamp * 1000).toISOString() : null,
        latest_tarball: info.latest_tarball,
      }))
    } catch (e) {
      console.error('Failed to fetch tarballs:', e)
    }
  }

  async function fetchImages() {
    try {
      const { data } = await dockerAPI.listImages()
      images.value = data
    } catch (e) {
      console.error('Failed to fetch images:', e)
    }
  }

  async function createContainer(data) {
    const opId = `create-container-${Date.now()}`
    loadingStore.startLoading(opId, `Creating container "${data.container_name}"...`)
    try {
      await dockerAPI.createContainer(data)
      await fetchContainers()
      return true
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loadingStore.stopLoading(opId)
    }
  }

  async function deleteContainer(envName) {
    try {
      await dockerAPI.deleteContainer(envName)
      containers.value = containers.value.filter((c) => c.name !== envName)
      return true
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    }
  }

  async function startContainer(envName) {
    try {
      await dockerAPI.startContainer(envName)
      const container = containers.value.find((c) => c.name === envName)
      if (container) {
        container.status = 'running'
      }
      return true
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    }
  }

  async function stopContainer(envName) {
    try {
      await dockerAPI.stopContainer(envName)
      const container = containers.value.find((c) => c.name === envName)
      if (container) {
        container.status = 'exited'
      }
      return true
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    }
  }

  async function createTarball(envName) {
    const opId = `create-tarball-${Date.now()}`
    loadingStore.startLoading(opId, `Creating tarball from "${envName}"...`)
    try {
      await dockerAPI.createTarball(envName)
      await fetchTarballs()
      return true
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loadingStore.stopLoading(opId)
    }
  }

  async function deleteTarball(name) {
    try {
      await dockerAPI.deleteTarball(name)
      await fetchTarballs()
      return true
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    }
  }

  return {
    // State
    containers,
    tarballs,
    images,
    loading,
    error,
    // Getters
    runningContainers,
    stoppedContainers,
    // Actions
    fetchContainers,
    fetchTarballs,
    fetchImages,
    createContainer,
    deleteContainer,
    startContainer,
    stopContainer,
    createTarball,
    deleteTarball,
  }
})
