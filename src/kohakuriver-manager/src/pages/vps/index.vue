<script setup>
/**
 * VPS Management Page
 *
 * Provides interface for creating, managing, and connecting to VPS instances.
 * Features include:
 * - VPS creation with SSH key modes and GPU selection
 * - Real-time status monitoring via polling
 * - IDE integration for terminal and file access
 * - SSH connection info and command copying
 */

import { useClusterStore } from '@/stores/cluster'
import { useDockerStore } from '@/stores/docker'
import { useVpsStore } from '@/stores/vps'

import { useNotification } from '@/composables/useNotification'
import { usePolling } from '@/composables/usePolling'

import apiClient from '@/utils/api/client'
import { formatBytes, formatRelativeTime } from '@/utils/format'
import { generateRandomName } from '@/utils/randomName'

import IdeContent from '@/components/ide/IdeContent.vue'
import IdeOverlay from '@/components/ide/IdeOverlay.vue'
import PortForwardDialog from '@/components/vps/PortForwardDialog.vue'
import IpReservation from '@/components/common/IpReservation.vue'

const vpsStore = useVpsStore()
const clusterStore = useClusterStore()
const dockerStore = useDockerStore()
const notify = useNotification()

// Filter
const showAll = ref(false)

// IDE Modal state
const ideModalVisible = ref(false)
const ideTaskId = ref(null)

// Dialogs
const createDialogVisible = ref(false)
const sshInfoDialogVisible = ref(false)
const portForwardDialogVisible = ref(false)
const selectedVps = ref(null)

// Create form
const createForm = ref({
  name: '',
  vps_backend: 'docker', // 'docker' or 'qemu'
  required_cores: 0,
  required_memory_bytes: null,
  imageSource: 'tarball', // 'tarball' or 'registry'
  container_name: null,
  registry_image: null,
  target_hostname: null,
  target_numa_node_id: null,
  ssh_key_mode: 'disabled', // Default to TTY-only mode (no SSH)
  ssh_public_key: '',
  privileged: false,
  gpuFeatureEnabled: false,
  selectedGpus: {}, // { hostname: [gpu_id1, gpu_id2], ... }
  ip_reservation_token: null, // Token from IP reservation
  // VM-specific options (qemu backend)
  vm_image: 'ubuntu-24.04',
  vm_disk_size: '500G',
  vm_memory_mb: 4096,
})

// Expanded GPU node panels
const expandedGpuNodes = ref([])

// IP Reservation component ref
const ipReservationRef = ref(null)

// Computed: selected runner (either from node selection or GPU selection)
const selectedRunner = computed(() => {
  if (createForm.value.gpuFeatureEnabled) {
    const gpuInfo = getSelectedGpuInfo()
    return gpuInfo?.hostname || null
  }
  return createForm.value.target_hostname || null
})

// VM image dropdown
const vmImages = ref([])
const vmImagesLoading = ref(false)

async function fetchVmImages(hostname) {
  if (!hostname) {
    vmImages.value = []
    return
  }
  vmImagesLoading.value = true
  try {
    const { data } = await apiClient.get(`/vm/images/${hostname}`)
    vmImages.value = data.images || []
  } catch {
    vmImages.value = []
  } finally {
    vmImagesLoading.value = false
  }
}

// Fetch VM images when runner selection changes and backend is qemu
watch([selectedRunner, () => createForm.value.vps_backend], ([runner, backend]) => {
  if (backend === 'qemu' && runner) {
    fetchVmImages(runner)
  } else {
    vmImages.value = []
  }
})

// Handle IP token update from IpReservation component
function handleIpTokenUpdate(token) {
  createForm.value.ip_reservation_token = token
}

// Get nodes with GPU info
const nodesWithGpus = computed(() => {
  return clusterStore.onlineNodes.filter((n) => n.gpu_info && n.gpu_info.length > 0)
})

// Get available NUMA nodes for the selected runner
const availableNumaNodes = computed(() => {
  if (!selectedRunner.value) return []
  const node = clusterStore.onlineNodes.find((n) => n.hostname === selectedRunner.value)
  if (!node || !node.numa_topology || !node.numa_topology.numa_nodes) return []
  return node.numa_topology.numa_nodes.map((n) => ({
    id: n.id,
    label: `NUMA ${n.id} (${n.cpu_count} CPUs, ${formatNumaMemory(n.memory_total_mb)})`,
  }))
})

// Format memory for NUMA display
function formatNumaMemory(mb) {
  if (!mb) return '0 MB'
  if (mb >= 1024) {
    return `${(mb / 1024).toFixed(1)} GB`
  }
  return `${mb} MB`
}

// Clear NUMA selection when runner changes
watch(selectedRunner, () => {
  createForm.value.target_numa_node_id = null
})

// Check if another GPU node is already selected (for disabling other nodes)
function isAnotherGpuNodeSelected(hostname) {
  const selectedNode = Object.keys(createForm.value.selectedGpus).find(
    (h) => createForm.value.selectedGpus[h] && createForm.value.selectedGpus[h].length > 0
  )
  return selectedNode !== undefined && selectedNode !== hostname
}

// Get the selected GPU node hostname and GPU IDs
function getSelectedGpuInfo() {
  for (const hostname in createForm.value.selectedGpus) {
    if (createForm.value.selectedGpus[hostname] && createForm.value.selectedGpus[hostname].length > 0) {
      return { hostname, gpuIds: createForm.value.selectedGpus[hostname] }
    }
  }
  return null
}

// Initialize selectedGpus for nodes
function initializeGpuSelections() {
  createForm.value.selectedGpus = {}
  for (const node of nodesWithGpus.value) {
    createForm.value.selectedGpus[node.hostname] = []
  }
}

// Watch GPU feature toggle - clear appropriate selections
watch(
  () => createForm.value.gpuFeatureEnabled,
  (enabled) => {
    if (enabled) {
      // Clear node selection when switching to GPU mode
      createForm.value.target_hostname = null
      initializeGpuSelections()
    } else {
      // Clear GPU selections when switching to node mode
      createForm.value.selectedGpus = {}
      expandedGpuNodes.value = []
    }
  }
)

// Generated key result
const generatedKeyResult = ref(null)

// Polling
const { start: startPolling } = usePolling(() => {
  vpsStore.fetchVpsList(!showAll.value)
}, 5000)

onMounted(async () => {
  await Promise.all([clusterStore.fetchNodes(), dockerStore.fetchTarballs()])
  startPolling()
})

watch(showAll, () => {
  vpsStore.fetchVpsList(!showAll.value)
})

async function handleCreate() {
  try {
    // Determine target and GPUs based on mode
    let targetHostname = null
    let requiredGpus = null

    if (createForm.value.gpuFeatureEnabled) {
      // GPU mode - get selected GPU info
      const gpuInfo = getSelectedGpuInfo()
      if (!gpuInfo) {
        notify.warning('Please select at least one GPU')
        return
      }
      targetHostname = gpuInfo.hostname
      requiredGpus = gpuInfo.gpuIds
    } else {
      // Node mode
      targetHostname = createForm.value.target_hostname || null
    }

    const isVm = createForm.value.vps_backend === 'qemu'

    const data = {
      name: createForm.value.name || null,
      vps_backend: createForm.value.vps_backend,
      required_cores: createForm.value.required_cores,
      required_memory_bytes: createForm.value.required_memory_bytes || null,
      container_name:
        !isVm && createForm.value.imageSource === 'tarball' ? createForm.value.container_name || null : null,
      registry_image:
        !isVm && createForm.value.imageSource === 'registry' ? createForm.value.registry_image || null : null,
      target_hostname: targetHostname,
      target_numa_node_id: createForm.value.target_numa_node_id,
      ssh_key_mode: createForm.value.ssh_key_mode,
      ssh_public_key: createForm.value.ssh_key_mode === 'upload' ? createForm.value.ssh_public_key : null,
      privileged: !isVm ? createForm.value.privileged || null : null,
      required_gpus: requiredGpus,
      ip_reservation_token: createForm.value.ip_reservation_token || null,
      // VM-specific fields
      vm_image: isVm ? createForm.value.vm_image : null,
      vm_disk_size: isVm ? createForm.value.vm_disk_size : null,
      memory_mb: isVm ? createForm.value.vm_memory_mb : null,
    }

    const result = await vpsStore.createVps(data)
    notify.success('VPS created successfully')

    // If key was generated, show it
    if (result.ssh_private_key) {
      generatedKeyResult.value = result
    }

    createDialogVisible.value = false
    resetCreateForm()
  } catch (e) {
    notify.error(e.response?.data?.detail || 'Failed to create VPS')
  }
}

function resetCreateForm() {
  createForm.value = {
    name: '',
    vps_backend: 'docker',
    required_cores: 0,
    required_memory_bytes: null,
    imageSource: 'tarball',
    container_name: null,
    registry_image: null,
    target_hostname: null,
    target_numa_node_id: null,
    ssh_key_mode: 'disabled', // Default to TTY-only mode
    ssh_public_key: '',
    privileged: false,
    gpuFeatureEnabled: false,
    selectedGpus: {},
    ip_reservation_token: null,
    vm_image: 'ubuntu-24.04',
    vm_disk_size: '500G',
    vm_memory_mb: 4096,
  }
  expandedGpuNodes.value = []
}

// Format MiB for GPU display
function formatGpuMemory(mib) {
  if (!mib) return ''
  if (mib >= 1024) {
    return `${(mib / 1024).toFixed(0)} GB`
  }
  return `${mib.toFixed(0)} MB`
}

async function handleStop(taskId) {
  try {
    await vpsStore.stopVps(taskId)
    notify.success('VPS stop requested')
  } catch (e) {
    notify.error('Failed to stop VPS')
  }
}

async function handleRestart(taskId) {
  try {
    await vpsStore.restartVps(taskId)
    notify.success('VPS restart requested')
  } catch (e) {
    notify.error('Failed to restart VPS')
  }
}

async function handlePause(taskId) {
  try {
    await vpsStore.pauseVps(taskId)
    notify.success('VPS paused')
  } catch (e) {
    notify.error('Failed to pause VPS')
  }
}

async function handleResume(taskId) {
  try {
    await vpsStore.resumeVps(taskId)
    notify.success('VPS resumed')
  } catch (e) {
    notify.error('Failed to resume VPS')
  }
}

function openIde(taskId) {
  ideTaskId.value = taskId
  ideModalVisible.value = true
}

function closeIde() {
  console.log('VPS page: closeIde called')
  ideModalVisible.value = false
  ideTaskId.value = null
}

function showSshInfo(vps) {
  selectedVps.value = vps
  sshInfoDialogVisible.value = true
}

function showPortForward(vps) {
  selectedVps.value = vps
  portForwardDialogVisible.value = true
}

async function copyToClipboard(text, successMsg) {
  try {
    await navigator.clipboard.writeText(text)
    notify.success(successMsg)
  } catch (err) {
    // Fallback for non-secure contexts
    const textarea = document.createElement('textarea')
    textarea.value = text
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    notify.success(successMsg)
  }
}

function copySshCommand(vps) {
  const cmd = `kohakuriver ssh connect ${vps.task_id}`
  copyToClipboard(cmd, 'SSH command copied')
}

function copyTerminalCommand(vps) {
  const cmd = `kohakuriver connect ${vps.task_id}`
  copyToClipboard(cmd, 'Terminal command copied')
}

function downloadPrivateKey() {
  if (!generatedKeyResult.value?.ssh_private_key) return

  const blob = new Blob([generatedKeyResult.value.ssh_private_key], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `vps-${generatedKeyResult.value.task_id}-key`
  a.click()
  URL.revokeObjectURL(url)
}

function getNodeHostname(node) {
  if (!node) return '-'
  return typeof node === 'object' ? node.hostname : node
}

function copyVpsId(taskId) {
  copyToClipboard(taskId, 'VPS ID copied')
}
</script>

<template>
  <div class="vps-page">
    <!-- Main Content -->
    <div class="vps-content space-y-6">
      <!-- Header -->
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 class="page-title mb-0">VPS Instances</h2>
          <p class="text-muted">{{ vpsStore.runningVps.length }} running, {{ vpsStore.activeVps.length }} active</p>
        </div>
        <div class="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
          <el-switch
            v-model="showAll"
            active-text="Show all"
            inactive-text="Active only" />
          <el-button
            type="primary"
            @click="createDialogVisible = true"
            class="w-full sm:w-auto">
            <span class="i-carbon-add mr-2"></span>
            Create VPS
          </el-button>
        </div>
      </div>

      <!-- VPS Cards -->
      <div
        v-if="vpsStore.loading && vpsStore.vpsList.length === 0"
        class="text-center py-12">
        <el-icon class="is-loading text-4xl text-blue-500"><i class="i-carbon-renew"></i></el-icon>
      </div>

      <EmptyState
        v-else-if="vpsStore.vpsList.length === 0"
        icon="i-carbon-virtual-machine"
        title="No VPS instances"
        description="Create a new VPS to get started.">
        <template #action>
          <el-button
            type="primary"
            @click="createDialogVisible = true">
            Create VPS
          </el-button>
        </template>
      </EmptyState>

      <div
        v-else
        class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        <div
          v-for="vps in vpsStore.vpsList"
          :key="vps.task_id"
          class="card flex flex-col">
          <!-- Header with name and ID -->
          <div class="flex items-start justify-between gap-2 mb-4">
            <div class="flex items-center gap-2 min-w-0 flex-1">
              <span class="i-carbon-virtual-machine text-2xl text-blue-500 flex-shrink-0"></span>
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <h3
                    class="font-semibold truncate"
                    :title="vps.name || vps.task_id">
                    {{ vps.name || `VPS #${vps.task_id.substring(0, 8)}` }}
                  </h3>
                  <el-tooltip
                    content="Copy VPS ID"
                    placement="top">
                    <button
                      @click="copyVpsId(vps.task_id)"
                      class="text-gray-400 hover:text-blue-500 transition-colors flex-shrink-0">
                      <span class="i-carbon-copy text-sm"></span>
                    </button>
                  </el-tooltip>
                </div>
                <p class="text-xs text-muted font-mono truncate">{{ vps.task_id }}</p>
              </div>
            </div>
            <StatusBadge
              :status="vps.status"
              class="flex-shrink-0" />
          </div>

          <!-- Info -->
          <div class="space-y-2 text-sm flex-1">
            <div class="flex justify-between">
              <span class="text-muted">Backend</span>
              <el-tag
                :type="vps.vps_backend === 'qemu' ? 'warning' : 'info'"
                size="small">
                {{ vps.vps_backend === 'qemu' ? 'VM (QEMU)' : 'Docker' }}
              </el-tag>
            </div>
            <div class="flex justify-between">
              <span class="text-muted">Node</span>
              <span>{{ getNodeHostname(vps.assigned_node) }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-muted">CPU Cores</span>
              <span>{{ vps.required_cores }}</span>
            </div>
            <div
              v-if="vps.vps_backend === 'qemu' && vps.vm_ip"
              class="flex justify-between">
              <span class="text-muted">VM IP</span>
              <span class="font-mono">{{ vps.vm_ip }}</span>
            </div>
            <div
              v-if="vps.vps_backend === 'qemu' && vps.vm_image"
              class="flex justify-between">
              <span class="text-muted">VM Image</span>
              <span>{{ vps.vm_image }}</span>
            </div>
            <div
              v-if="vps.required_memory_bytes"
              class="flex justify-between">
              <span class="text-muted">Memory</span>
              <span>{{ formatBytes(vps.required_memory_bytes) }}</span>
            </div>
            <div
              v-if="vps.ssh_port"
              class="flex justify-between">
              <span class="text-muted">SSH Port</span>
              <span class="font-mono">{{ vps.ssh_port }}</span>
            </div>
            <div
              v-if="vps.container_name"
              class="flex justify-between gap-2">
              <span class="text-muted flex-shrink-0">Container</span>
              <span
                class="truncate"
                :title="vps.container_name">
                {{ vps.container_name }}
              </span>
            </div>
            <div
              v-if="vps.owner_username"
              class="flex justify-between">
              <span class="text-muted">Creator</span>
              <span>{{ vps.owner_username }}</span>
            </div>
            <div
              v-if="vps.assignees && vps.assignees.length > 0"
              class="flex justify-between gap-2">
              <span class="text-muted flex-shrink-0">Assignees</span>
              <span
                class="truncate text-right"
                :title="vps.assignees.map((a) => a.username).join(', ')">
                {{ vps.assignees.map((a) => a.username).join(', ') }}
              </span>
            </div>
            <div class="flex justify-between">
              <span class="text-muted">Created</span>
              <span>{{ formatRelativeTime(vps.submitted_at) }}</span>
            </div>
          </div>

          <!-- Actions - Aligned grid layout -->
          <div class="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
            <!-- Running state buttons -->
            <div
              v-if="vps.status === 'running'"
              class="flex flex-col gap-2">
              <!-- Primary actions row -->
              <div class="flex gap-2">
                <el-tooltip
                  content="Open IDE (Terminal + Files)"
                  placement="top">
                  <el-button
                    size="small"
                    type="primary"
                    @click="openIde(vps.task_id)"
                    class="flex-1">
                    <span class="i-carbon-terminal mr-1"></span>
                    IDE
                  </el-button>
                </el-tooltip>
                <el-tooltip
                  v-if="vps.ssh_port"
                  content="SSH Connection Info"
                  placement="top">
                  <el-button
                    size="small"
                    type="info"
                    @click="showSshInfo(vps)"
                    class="flex-1">
                    <span class="i-carbon-connect mr-1"></span>
                    SSH Info
                  </el-button>
                </el-tooltip>
                <el-tooltip
                  v-else
                  content="Copy Terminal Command"
                  placement="top">
                  <el-button
                    size="small"
                    type="info"
                    @click="copyTerminalCommand(vps)"
                    class="flex-1">
                    <span class="i-carbon-copy mr-1"></span>
                    Copy CMD
                  </el-button>
                </el-tooltip>
              </div>

              <!-- Copy commands row (only when SSH is enabled) -->
              <div
                v-if="vps.ssh_port"
                class="flex gap-2">
                <el-tooltip
                  content="Copy SSH Command"
                  placement="top">
                  <el-button
                    size="small"
                    type="info"
                    @click="copySshCommand(vps)"
                    class="flex-1">
                    <span class="i-carbon-terminal mr-1"></span>
                    SSH
                  </el-button>
                </el-tooltip>
                <el-tooltip
                  content="Copy Terminal Command"
                  placement="top">
                  <el-button
                    size="small"
                    type="info"
                    @click="copyTerminalCommand(vps)"
                    class="flex-1">
                    <span class="i-carbon-copy mr-1"></span>
                    Terminal
                  </el-button>
                </el-tooltip>
              </div>

              <!-- Port forwarding row -->
              <div class="flex gap-2">
                <el-tooltip
                  content="Forward container ports to local machine"
                  placement="top">
                  <el-button
                    size="small"
                    type="success"
                    @click="showPortForward(vps)"
                    class="flex-1">
                    <span class="i-carbon-arrows-horizontal mr-1"></span>
                    Port Forward
                  </el-button>
                </el-tooltip>
              </div>

              <!-- Control buttons row -->
              <div class="flex gap-2">
                <el-tooltip
                  content="Pause"
                  placement="top">
                  <el-button
                    size="small"
                    type="info"
                    @click="handlePause(vps.task_id)"
                    class="flex-1">
                    <span class="i-carbon-pause"></span>
                  </el-button>
                </el-tooltip>
                <el-tooltip
                  content="Restart"
                  placement="top">
                  <el-button
                    size="small"
                    type="warning"
                    @click="handleRestart(vps.task_id)"
                    class="flex-1">
                    <span class="i-carbon-restart"></span>
                  </el-button>
                </el-tooltip>
                <el-tooltip
                  content="Stop"
                  placement="top">
                  <el-button
                    size="small"
                    type="danger"
                    @click="handleStop(vps.task_id)"
                    class="flex-1">
                    <span class="i-carbon-stop"></span>
                  </el-button>
                </el-tooltip>
              </div>
            </div>

            <!-- Paused state buttons -->
            <div
              v-else-if="vps.status === 'paused'"
              class="grid grid-cols-2 gap-2">
              <el-tooltip
                content="Resume VPS"
                placement="top">
                <el-button
                  size="small"
                  type="success"
                  @click="handleResume(vps.task_id)"
                  class="w-full">
                  <span class="i-carbon-play mr-1"></span>
                  Resume
                </el-button>
              </el-tooltip>
              <el-tooltip
                content="Stop VPS"
                placement="top">
                <el-button
                  size="small"
                  type="danger"
                  @click="handleStop(vps.task_id)"
                  class="w-full">
                  <span class="i-carbon-stop mr-1"></span>
                  Stop
                </el-button>
              </el-tooltip>
            </div>

            <!-- Assigning state (provisioning) -->
            <div
              v-else-if="vps.status === 'assigning'"
              class="text-center text-sm py-2">
              <div class="text-blue-500 dark:text-blue-400 animate-pulse">
                {{ vps.error_message || 'Provisioning VM...' }}
              </div>
            </div>

            <!-- Pending/Other states -->
            <div
              v-else-if="vps.status === 'pending'"
              class="text-center text-muted text-sm py-2">
              Waiting for assignment...
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- IDE Modal -->
    <IdeOverlay
      :visible="ideModalVisible"
      @close="closeIde">
      <IdeContent
        v-if="ideTaskId"
        :task-id="ideTaskId"
        type="task"
        @close="closeIde" />
    </IdeOverlay>

    <!-- Create Dialog -->
    <el-dialog
      v-model="createDialogVisible"
      title="Create VPS"
      width="600px"
      destroy-on-close>
      <el-form
        :model="createForm"
        label-position="top">
        <el-form-item label="Name">
          <div class="flex gap-2 w-full">
            <el-input
              v-model="createForm.name"
              placeholder="Optional friendly name for this VPS"
              class="flex-1" />
            <el-button @click="createForm.name = generateRandomName()">
              <span class="i-carbon-shuffle mr-1"></span>
              Random
            </el-button>
          </div>
        </el-form-item>

        <el-form-item label="Backend">
          <el-radio-group v-model="createForm.vps_backend">
            <el-radio value="docker">
              <span>Docker Container</span>
              <span class="text-xs text-gray-400 ml-1">(default)</span>
            </el-radio>
            <el-radio value="qemu">
              <span>QEMU VM</span>
              <span class="text-xs text-gray-400 ml-1">(full GPU passthrough)</span>
            </el-radio>
          </el-radio-group>
        </el-form-item>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <el-form-item label="CPU Cores (0 = no limit)">
            <el-input-number
              v-model="createForm.required_cores"
              :min="0"
              :max="128"
              class="w-full" />
          </el-form-item>

          <el-form-item label="Memory">
            <el-input-number
              v-model="createForm.required_memory_bytes"
              :min="0"
              placeholder="Bytes"
              class="w-full" />
          </el-form-item>
        </div>

        <!-- Docker Image Source (docker backend only) -->
        <el-form-item
          v-if="createForm.vps_backend === 'docker'"
          label="Image Source">
          <el-radio-group
            v-model="createForm.imageSource"
            class="mb-2">
            <el-radio value="tarball">Tarball</el-radio>
            <el-radio value="registry">Registry Image</el-radio>
          </el-radio-group>
          <el-select
            v-if="createForm.imageSource === 'tarball'"
            v-model="createForm.container_name"
            placeholder="Select container"
            clearable
            class="w-full">
            <el-option
              v-for="tarball in dockerStore.tarballs"
              :key="tarball.name"
              :label="tarball.name"
              :value="tarball.name" />
          </el-select>
          <el-input
            v-else
            v-model="createForm.registry_image"
            placeholder="e.g. ubuntu:22.04, nvidia/cuda:12.0-base" />
        </el-form-item>

        <!-- VM Options (qemu backend only) -->
        <template v-if="createForm.vps_backend === 'qemu'">
          <el-form-item label="VM Image">
            <el-select
              v-model="createForm.vm_image"
              placeholder="Select VM image"
              :loading="vmImagesLoading"
              filterable
              allow-create
              class="w-full">
              <el-option
                v-for="img in vmImages"
                :key="img.name"
                :label="img.name"
                :value="img.name">
                <span>{{ img.name }}</span>
                <span class="text-xs text-gray-400 ml-2">({{ formatBytes(img.size_bytes) }})</span>
              </el-option>
            </el-select>
            <p
              v-if="!selectedRunner"
              class="text-xs text-gray-400 mt-1">
              Select a node or GPU first to load available images
            </p>
          </el-form-item>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <el-form-item label="Max Disk Size (thin-provisioned)">
              <el-input
                v-model="createForm.vm_disk_size"
                placeholder="e.g. 500G" />
            </el-form-item>
            <el-form-item label="VM Memory (MB)">
              <el-input-number
                v-model="createForm.vm_memory_mb"
                :min="512"
                :step="1024"
                class="w-full" />
            </el-form-item>
          </div>
        </template>

        <!-- GPU Feature Toggle -->
        <el-form-item label="Enable GPU Selection">
          <el-switch v-model="createForm.gpuFeatureEnabled" />
          <span class="text-muted text-xs ml-2">Toggle to select specific GPUs instead of a node</span>
        </el-form-item>

        <!-- Node Selection (when GPU feature is OFF) -->
        <el-form-item
          v-if="!createForm.gpuFeatureEnabled"
          label="Target Node">
          <el-select
            v-model="createForm.target_hostname"
            placeholder="Auto-select"
            clearable
            class="w-full">
            <el-option
              v-for="node in clusterStore.onlineNodes"
              :key="node.hostname"
              :label="node.hostname"
              :value="node.hostname" />
          </el-select>
        </el-form-item>

        <!-- GPU Selection (when GPU feature is ON) -->
        <el-form-item
          v-else
          label="Select Target GPUs">
          <div class="gpu-selection-container">
            <el-empty
              v-if="nodesWithGpus.length === 0"
              description="No online nodes with GPUs"
              :image-size="60" />
            <el-collapse
              v-else
              v-model="expandedGpuNodes">
              <el-collapse-item
                v-for="node in nodesWithGpus"
                :key="node.hostname"
                :name="node.hostname">
                <template #title>
                  <span class="font-medium">{{ node.hostname }}</span>
                  <span class="text-muted text-xs ml-2">({{ node.gpu_info.length }} GPUs)</span>
                </template>
                <el-checkbox-group
                  v-model="createForm.selectedGpus[node.hostname]"
                  :disabled="isAnotherGpuNodeSelected(node.hostname)"
                  class="gpu-checkbox-grid">
                  <el-checkbox
                    v-for="gpu in node.gpu_info"
                    :key="gpu.gpu_id"
                    :value="gpu.gpu_id"
                    border
                    class="gpu-checkbox">
                    <div class="gpu-checkbox-content">
                      <span class="font-medium">GPU {{ gpu.gpu_id }}: {{ gpu.name || 'Unknown' }}</span>
                      <span class="gpu-stats">
                        {{ formatGpuMemory(gpu.memory_total_mib) }} | Util: {{ gpu.gpu_utilization ?? '-' }}% | Temp:
                        {{ gpu.temperature ?? '-' }}°C
                      </span>
                    </div>
                  </el-checkbox>
                </el-checkbox-group>
              </el-collapse-item>
            </el-collapse>
          </div>
          <el-alert
            v-if="!getSelectedGpuInfo()"
            title="Select at least one GPU on a single node"
            type="info"
            show-icon
            :closable="false"
            class="mt-2" />
        </el-form-item>

        <el-form-item label="SSH Mode">
          <el-radio-group
            v-model="createForm.ssh_key_mode"
            class="flex flex-wrap gap-x-4 gap-y-2">
            <el-radio value="disabled">
              <span>Disabled</span>
              <span class="text-xs text-gray-400 ml-1">(TTY only)</span>
            </el-radio>
            <el-radio value="generate">Generate key</el-radio>
            <el-radio value="upload">Upload key</el-radio>
            <el-radio value="none">No key (passwordless)</el-radio>
          </el-radio-group>
          <div class="text-xs text-gray-500 mt-1">
            <span v-if="createForm.ssh_key_mode === 'disabled'">
              No SSH server. Access via web terminal only (faster startup).
            </span>
            <span v-else-if="createForm.ssh_key_mode === 'generate'">
              Generate an SSH key pair. You'll download the private key after creation.
            </span>
            <span v-else-if="createForm.ssh_key_mode === 'upload'">
              Use your own SSH public key for authentication.
            </span>
            <span v-else-if="createForm.ssh_key_mode === 'none'">
              SSH with empty password (less secure, use for testing only).
            </span>
          </div>
        </el-form-item>

        <el-form-item
          v-if="createForm.ssh_key_mode === 'upload'"
          label="Public Key">
          <el-input
            v-model="createForm.ssh_public_key"
            type="textarea"
            :rows="3"
            placeholder="ssh-ed25519 AAAA... user@host" />
        </el-form-item>

        <!-- NUMA Node Selection -->
        <el-form-item
          v-if="selectedRunner && availableNumaNodes.length > 0"
          label="NUMA Node">
          <el-select
            v-model="createForm.target_numa_node_id"
            placeholder="No NUMA affinity (use any)"
            clearable
            class="w-full">
            <el-option
              v-for="numa in availableNumaNodes"
              :key="numa.id"
              :label="numa.label"
              :value="numa.id" />
          </el-select>
          <div class="text-xs text-muted mt-1">Pin VPS to a specific NUMA node for better memory locality</div>
        </el-form-item>

        <!-- IP Reservation -->
        <el-form-item label="IP Reservation">
          <IpReservation
            ref="ipReservationRef"
            :runner="selectedRunner"
            @update:token="handleIpTokenUpdate" />
        </el-form-item>

        <el-form-item v-if="createForm.vps_backend === 'docker'">
          <el-checkbox v-model="createForm.privileged">Run with privileged mode</el-checkbox>
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="flex flex-col sm:flex-row gap-2 sm:justify-end">
          <el-button
            @click="createDialogVisible = false"
            class="w-full sm:w-auto">
            Cancel
          </el-button>
          <el-button
            type="primary"
            :loading="vpsStore.creating"
            @click="handleCreate"
            class="w-full sm:w-auto">
            Create
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- SSH Info Dialog -->
    <el-dialog
      v-model="sshInfoDialogVisible"
      title="Connection Info"
      width="500px">
      <div
        v-if="selectedVps"
        class="space-y-4">
        <div class="p-4 bg-app-surface rounded-lg">
          <p class="text-sm text-muted mb-2">SSH Command (via proxy):</p>
          <code class="text-sm font-mono break-all">kohakuriver ssh connect {{ selectedVps.task_id }}</code>
        </div>
        <div class="p-4 bg-app-surface rounded-lg">
          <p class="text-sm text-muted mb-2">Terminal Command:</p>
          <code class="text-sm font-mono break-all">kohakuriver connect {{ selectedVps.task_id }}</code>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          <div>
            <span class="text-muted">Task ID:</span>
            <span class="ml-2 font-mono">{{ selectedVps.task_id }}</span>
          </div>
          <div>
            <span class="text-muted">Node:</span>
            <span class="ml-2 break-all">{{ getNodeHostname(selectedVps.assigned_node) }}</span>
          </div>
        </div>
      </div>
      <template #footer>
        <div class="flex flex-col sm:flex-row gap-2 sm:justify-end">
          <el-button
            @click="copySshCommand(selectedVps)"
            class="w-full sm:w-auto">
            <span class="i-carbon-terminal mr-1"></span>
            Copy SSH
          </el-button>
          <el-button
            @click="copyTerminalCommand(selectedVps)"
            class="w-full sm:w-auto">
            <span class="i-carbon-copy mr-1"></span>
            Copy Terminal
          </el-button>
          <el-button
            type="primary"
            @click="sshInfoDialogVisible = false"
            class="w-full sm:w-auto">
            Close
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- Generated Key Dialog -->
    <el-dialog
      v-model="generatedKeyResult"
      title="SSH Key Generated"
      width="600px"
      :close-on-click-modal="false">
      <div class="space-y-4">
        <el-alert
          type="warning"
          :closable="false">
          Save this private key now. It will not be shown again.
        </el-alert>

        <div>
          <p class="text-sm font-medium mb-2">Private Key:</p>
          <div
            class="p-3 bg-gray-900 text-gray-100 rounded-lg font-mono text-xs max-h-48 overflow-auto whitespace-pre break-all">
            {{ generatedKeyResult?.ssh_private_key }}
          </div>
        </div>

        <div v-if="generatedKeyResult?.ssh_public_key">
          <p class="text-sm font-medium mb-2">Public Key:</p>
          <div class="p-3 bg-app-surface rounded-lg font-mono text-xs overflow-auto break-all">
            {{ generatedKeyResult?.ssh_public_key }}
          </div>
        </div>
      </div>

      <template #footer>
        <div class="flex flex-col sm:flex-row gap-2 sm:justify-end">
          <el-button
            @click="downloadPrivateKey"
            class="w-full sm:w-auto">
            <span class="i-carbon-download mr-1"></span>
            Download Key
          </el-button>
          <el-button
            type="primary"
            @click="generatedKeyResult = null"
            class="w-full sm:w-auto">
            Done
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- Port Forward Dialog -->
    <PortForwardDialog
      v-if="selectedVps"
      v-model:visible="portForwardDialogVisible"
      :task-id="selectedVps.task_id"
      :status="selectedVps.status" />
  </div>
</template>

<style scoped>
/* GPU Selection Styles */
.gpu-selection-container {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  padding: 8px;
  min-height: 80px;
  max-height: 300px;
  overflow-y: auto;
  width: 100%;
}

.gpu-checkbox-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.gpu-checkbox {
  margin: 0 !important;
  width: 100%;
}

.gpu-checkbox-content {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  font-size: 0.85em;
  line-height: 1.4;
}

.gpu-stats {
  font-size: 0.75em;
  color: var(--el-text-color-secondary);
}

:deep(.el-collapse) {
  border: none;
}

:deep(.el-collapse-item__header) {
  font-size: 0.9em;
  padding: 0 8px;
  background: transparent;
}

:deep(.el-collapse-item__content) {
  padding: 12px 8px;
}

:deep(.el-checkbox.is-bordered) {
  padding: 8px 10px !important;
  height: auto !important;
}

/* =============================================================================
 * VPS Page Layout
 * ============================================================================= */

.vps-page {
  height: 100%;
  overflow: auto;
}

.vps-content {
  padding: 0;
}
</style>
