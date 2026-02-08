<script setup>
/**
 * VPS Create Dialog Component
 *
 * Form dialog for creating new VPS instances with support for Docker and QEMU backends,
 * GPU selection, NUMA pinning, IP reservation, and SSH key modes.
 */

import { useClusterStore } from '@/stores/cluster'
import { useDockerStore } from '@/stores/docker'
import { useVpsStore } from '@/stores/vps'

import { useNotification } from '@/composables/useNotification'

import apiClient from '@/utils/api/client'
import { formatBytes } from '@/utils/format'
import { generateRandomName } from '@/utils/randomName'

const props = defineProps({
  visible: {
    type: Boolean,
    required: true,
  },
})

const emit = defineEmits(['update:visible', 'created'])

const clusterStore = useClusterStore()
const dockerStore = useDockerStore()
const vpsStore = useVpsStore()
const notify = useNotification()

// Dialog visibility (two-way binding)
const dialogVisible = computed({
  get: () => props.visible,
  set: (val) => emit('update:visible', val),
})

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
  vm_cores: 0,
})

// Expanded GPU node panels
const expandedGpuNodes = ref([])

// GPU Selector component ref
const gpuSelectorRef = ref(null)

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

// Fetch VM images and compute defaults when runner selection changes and backend is qemu
watch([selectedRunner, () => createForm.value.vps_backend], ([runner, backend]) => {
  if (backend === 'qemu' && runner) {
    fetchVmImages(runner)
    // Compute 25% defaults from selected node
    const node = clusterStore.onlineNodes.find((n) => n.hostname === runner)
    if (node) {
      if (node.total_cores) {
        createForm.value.vm_cores = Math.max(1, Math.floor(node.total_cores * 0.25))
      }
      if (node.memory_total_bytes) {
        // 25% of total, rounded down to nearest GB
        createForm.value.vm_memory_mb = Math.max(
          1024,
          Math.floor(((node.memory_total_bytes / 1024 / 1024) * 0.25) / 1024) * 1024
        )
      }
    }
  } else {
    vmImages.value = []
  }
})

// Handle IP token update from IpReservation component
function handleIpTokenUpdate(token) {
  createForm.value.ip_reservation_token = token
}

// Delegate GPU info queries to the GpuSelector component
function getSelectedGpuInfo() {
  return gpuSelectorRef.value?.getSelectedGpuInfo() ?? null
}

function initializeGpuSelections() {
  gpuSelectorRef.value?.initializeGpuSelections()
}

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

/**
 * Build the data object for the VPS create API request.
 *
 * @param {object} form - The create form state
 * @param {string|null} targetHostname - Resolved target node hostname
 * @param {string[]|null} requiredGpus - Selected GPU IDs, or null
 * @returns {object} The API request payload
 */
function buildVpsCreateData(form, targetHostname, requiredGpus) {
  const isVm = form.vps_backend === 'qemu'

  const data = {
    name: form.name || null,
    vps_backend: form.vps_backend,
    target_hostname: targetHostname,
    target_numa_node_id: form.target_numa_node_id,
    ssh_key_mode: form.ssh_key_mode,
    required_gpus: requiredGpus,
    ip_reservation_token: form.ip_reservation_token || null,
    // Fields that differ by backend, set below
    required_cores: 0,
    required_memory_bytes: null,
    container_name: null,
    registry_image: null,
    ssh_public_key: null,
    privileged: null,
    vm_image: null,
    vm_disk_size: null,
    memory_mb: null,
  }

  // Cores: VM uses vm_cores, Docker uses required_cores
  if (isVm) {
    data.required_cores = form.vm_cores
  } else {
    data.required_cores = form.required_cores
  }

  // Memory limit: only applicable for Docker backend
  if (!isVm && form.required_memory_bytes) {
    data.required_memory_bytes = form.required_memory_bytes
  }

  // Container image fields: only for Docker backend
  if (!isVm && form.imageSource === 'tarball' && form.container_name) {
    data.container_name = form.container_name
  }
  if (!isVm && form.imageSource === 'registry' && form.registry_image) {
    data.registry_image = form.registry_image
  }

  // SSH public key: only when uploading a key
  if (form.ssh_key_mode === 'upload') {
    data.ssh_public_key = form.ssh_public_key
  }

  // Privileged mode: only for Docker backend
  if (!isVm && form.privileged) {
    data.privileged = form.privileged
  }

  // VM-specific fields: only for qemu backend
  if (isVm) {
    data.vm_image = form.vm_image
    data.vm_disk_size = form.vm_disk_size
    data.memory_mb = form.vm_memory_mb
  }

  return data
}

async function handleCreate() {
  try {
    // Determine target and GPUs based on mode
    let targetHostname = null
    let requiredGpus = null

    if (createForm.value.gpuFeatureEnabled) {
      const gpuInfo = getSelectedGpuInfo()
      if (!gpuInfo) {
        notify.warning('Please select at least one GPU')
        return
      }
      targetHostname = gpuInfo.hostname
      requiredGpus = gpuInfo.gpuIds
    } else {
      targetHostname = createForm.value.target_hostname || null
    }

    const data = buildVpsCreateData(createForm.value, targetHostname, requiredGpus)
    const result = await vpsStore.createVps(data)
    notify.success('VPS created successfully')

    // Emit created event with result (for generated key handling)
    emit('created', result)

    dialogVisible.value = false
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
    vm_cores: 0,
  }
  expandedGpuNodes.value = []
}
</script>

<template>
  <el-dialog
    v-model="dialogVisible"
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

      <div
        v-if="createForm.vps_backend !== 'qemu'"
        class="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <el-form-item label="VM CPU Cores">
            <el-input-number
              v-model="createForm.vm_cores"
              :min="1"
              :max="256"
              class="w-full" />
          </el-form-item>
          <el-form-item label="VM Memory (MB)">
            <el-input-number
              v-model="createForm.vm_memory_mb"
              :min="512"
              :step="1024"
              class="w-full" />
          </el-form-item>
          <el-form-item label="Max Disk Size">
            <el-input
              v-model="createForm.vm_disk_size"
              placeholder="e.g. 500G" />
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
        <GpuSelector
          ref="gpuSelectorRef"
          :online-nodes="clusterStore.onlineNodes"
          v-model="createForm.selectedGpus"
          v-model:expanded-nodes="expandedGpuNodes" />
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
          <span v-else-if="createForm.ssh_key_mode === 'upload'">Use your own SSH public key for authentication.</span>
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
          @click="dialogVisible = false"
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
</template>
