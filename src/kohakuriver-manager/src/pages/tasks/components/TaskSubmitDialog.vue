<script setup>
/**
 * Task Submit Dialog Component
 *
 * Provides the task submission form with:
 * - Batch mode with multiple instance tabs
 * - Command and argument input (with drag-and-drop reordering)
 * - Environment variables, CPU/memory, image source
 * - GPU toggle + node/GPU selection (via shared GpuSelector)
 * - NUMA selection, IP reservation, privileged checkbox
 */

import { useClusterStore } from '@/stores/cluster'
import { useDockerStore } from '@/stores/docker'
import { useTasksStore } from '@/stores/tasks'

import { useNotification } from '@/composables/useNotification'

import GpuSelector from '@/components/common/GpuSelector.vue'
import IpReservation from '@/components/common/IpReservation.vue'

const props = defineProps({
  visible: {
    type: Boolean,
    required: true,
  },
})

const emit = defineEmits(['update:visible'])

const clusterStore = useClusterStore()
const dockerStore = useDockerStore()
const tasksStore = useTasksStore()
const notify = useNotification()

// Batch submission mode
const batchModeEnabled = ref(false)
const batchInstances = ref([])
const activeBatchIndex = ref(0)

// Submit form
const submitForm = ref({
  command: '',
  arguments: [], // Array of argument strings
  currentArg: '', // Current input for new argument
  env_vars: '',
  required_cores: 0,
  required_memory_bytes: null,
  imageSource: 'tarball', // 'tarball' or 'registry'
  container_name: null,
  registry_image: null,
  targets: null,
  required_gpus: null,
  privileged: false,
  gpuFeatureEnabled: false,
  selectedGpus: {}, // { hostname: [gpu_id1, gpu_id2], ... }
  ip_reservation_token: null, // Token from IP reservation
  target_numa_node_id: null, // NUMA node ID
})

// Expanded GPU node panels
const expandedGpuNodes = ref([])

// GPU Selector component ref
const gpuSelectorRef = ref(null)

// IP Reservation component ref
const ipReservationRef = ref(null)

// Argument list drag state
const draggedArgIndex = ref(null)

// Computed: selected runner (either from node selection or GPU selection)
const selectedRunner = computed(() => {
  if (submitForm.value.gpuFeatureEnabled) {
    const gpuInfo = getSelectedGpuInfo()
    return gpuInfo?.hostname || null
  }
  return submitForm.value.targets || null
})

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
  submitForm.value.target_numa_node_id = null
})

// Watch GPU feature toggle - clear appropriate selections
watch(
  () => submitForm.value.gpuFeatureEnabled,
  (enabled) => {
    if (enabled) {
      // Clear node selection when switching to GPU mode
      submitForm.value.targets = null
      initializeGpuSelections()
    } else {
      // Clear GPU selections when switching to node mode
      submitForm.value.selectedGpus = {}
      expandedGpuNodes.value = []
    }
  }
)

// Handle argument input keydown
function handleArgKeydown(event) {
  if (event.key === 'Enter') {
    if (event.ctrlKey || event.metaKey || event.shiftKey) {
      // Ctrl+Enter or Shift+Enter: insert newline in current arg
      event.preventDefault()
      const textarea = event.target
      const start = textarea.selectionStart
      const end = textarea.selectionEnd
      const value = submitForm.value.currentArg
      submitForm.value.currentArg = value.substring(0, start) + '\n' + value.substring(end)
      // Set cursor position after the newline
      nextTick(() => {
        textarea.selectionStart = textarea.selectionEnd = start + 1
      })
    } else {
      // Enter: add current arg to list
      event.preventDefault()
      addCurrentArg()
    }
  }
}

// Add current argument to the list
function addCurrentArg() {
  const arg = submitForm.value.currentArg.trim()
  if (arg) {
    submitForm.value.arguments.push(arg)
    submitForm.value.currentArg = ''
  }
}

// Remove argument at index
function removeArg(index) {
  submitForm.value.arguments.splice(index, 1)
}

// Drag and drop handlers
function onDragStart(event, index) {
  draggedArgIndex.value = index
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', index)
}

function onDragOver(event, index) {
  event.preventDefault()
  event.dataTransfer.dropEffect = 'move'
}

function onDrop(event, targetIndex) {
  event.preventDefault()
  const sourceIndex = draggedArgIndex.value
  if (sourceIndex !== null && sourceIndex !== targetIndex) {
    const args = submitForm.value.arguments
    const [removed] = args.splice(sourceIndex, 1)
    args.splice(targetIndex, 0, removed)
  }
  draggedArgIndex.value = null
}

function onDragEnd() {
  draggedArgIndex.value = null
}

// Reset submit form
function resetSubmitForm() {
  submitForm.value = {
    command: '',
    arguments: [],
    currentArg: '',
    env_vars: '',
    required_cores: 0,
    required_memory_bytes: null,
    imageSource: 'tarball',
    container_name: null,
    registry_image: null,
    targets: null,
    required_gpus: null,
    privileged: false,
    gpuFeatureEnabled: false,
    selectedGpus: {},
    ip_reservation_token: null,
    target_numa_node_id: null,
  }
  expandedGpuNodes.value = []
}

// Handle IP token update from IpReservation component
function handleIpTokenUpdate(token) {
  submitForm.value.ip_reservation_token = token
}

// =============================================================================
// Batch Submission Functions
// =============================================================================

// Create a default batch instance from current form
function createBatchInstance() {
  return {
    command: submitForm.value.command,
    arguments: [...submitForm.value.arguments],
    env_vars: submitForm.value.env_vars,
    required_cores: submitForm.value.required_cores,
    required_memory_bytes: submitForm.value.required_memory_bytes,
    imageSource: submitForm.value.imageSource,
    container_name: submitForm.value.container_name,
    registry_image: submitForm.value.registry_image,
    targets: submitForm.value.targets,
    gpuFeatureEnabled: submitForm.value.gpuFeatureEnabled,
    selectedGpus: { ...submitForm.value.selectedGpus },
    privileged: submitForm.value.privileged,
    ip_reservation_token: null,
    target_numa_node_id: submitForm.value.target_numa_node_id,
  }
}

// Initialize batch mode with current form as first instance
function initBatchMode() {
  if (batchInstances.value.length === 0) {
    batchInstances.value = [createBatchInstance()]
  }
  activeBatchIndex.value = 0
}

// Add a new batch instance (copy from current active or template)
function addBatchInstance() {
  const newInstance = createBatchInstance()
  batchInstances.value.push(newInstance)
  activeBatchIndex.value = batchInstances.value.length - 1
  // Load into form
  loadBatchInstance(activeBatchIndex.value)
}

// Remove a batch instance
function removeBatchInstance(index) {
  if (batchInstances.value.length <= 1) return
  batchInstances.value.splice(index, 1)
  if (activeBatchIndex.value >= batchInstances.value.length) {
    activeBatchIndex.value = batchInstances.value.length - 1
  }
  loadBatchInstance(activeBatchIndex.value)
}

// Save current form state to batch instance
function saveBatchInstance(index) {
  if (index >= 0 && index < batchInstances.value.length) {
    batchInstances.value[index] = createBatchInstance()
  }
}

// Load batch instance into form
function loadBatchInstance(index) {
  if (index >= 0 && index < batchInstances.value.length) {
    const instance = batchInstances.value[index]
    submitForm.value.command = instance.command
    submitForm.value.arguments = [...instance.arguments]
    submitForm.value.env_vars = instance.env_vars
    submitForm.value.required_cores = instance.required_cores
    submitForm.value.required_memory_bytes = instance.required_memory_bytes
    submitForm.value.imageSource = instance.imageSource
    submitForm.value.container_name = instance.container_name
    submitForm.value.registry_image = instance.registry_image
    submitForm.value.targets = instance.targets
    submitForm.value.gpuFeatureEnabled = instance.gpuFeatureEnabled
    submitForm.value.selectedGpus = { ...instance.selectedGpus }
    submitForm.value.privileged = instance.privileged
    submitForm.value.ip_reservation_token = instance.ip_reservation_token
    submitForm.value.target_numa_node_id = instance.target_numa_node_id
    activeBatchIndex.value = index
  }
}

// Switch active batch instance
function switchBatchInstance(index) {
  // Save current before switching
  saveBatchInstance(activeBatchIndex.value)
  loadBatchInstance(index)
}

// Watch batch mode toggle
watch(batchModeEnabled, (enabled) => {
  if (enabled) {
    initBatchMode()
  } else {
    // Clear batch instances when disabling
    batchInstances.value = []
    activeBatchIndex.value = 0
  }
})

// Resolve target node and GPU IDs from an instance's settings.
// Returns { targets, requiredGpus } or null if GPU mode is enabled but no GPUs are selected.
function _resolveTargetAndGpus(instance) {
  if (instance.gpuFeatureEnabled) {
    for (const hostname in instance.selectedGpus) {
      if (instance.selectedGpus[hostname]?.length > 0) {
        return { targets: [hostname], requiredGpus: [instance.selectedGpus[hostname]] }
      }
    }
    return null // No GPUs selected
  }
  return { targets: instance.targets ? [instance.targets] : null, requiredGpus: null }
}

// Build the task submission payload from an instance and resolved target/GPU info.
function _buildTaskData(instance, targets, requiredGpus) {
  return {
    task_type: 'command',
    command: instance.command,
    arguments: instance.arguments,
    env_vars: instance.env_vars
      ? Object.fromEntries(
          instance.env_vars
            .split('\n')
            .filter(Boolean)
            .map((line) => line.split('=').map((s) => s.trim()))
        )
      : {},
    required_cores: instance.required_cores,
    required_memory_bytes: instance.required_memory_bytes,
    container_name: instance.imageSource === 'tarball' ? instance.container_name || null : null,
    registry_image: instance.imageSource === 'registry' ? instance.registry_image || null : null,
    targets: targets,
    required_gpus: requiredGpus,
    privileged: instance.privileged || null,
    ip_reservation_token: instance.ip_reservation_token || null,
    target_numa_node_id: instance.target_numa_node_id,
  }
}

async function handleSubmit() {
  try {
    // Add any pending argument in the input field
    if (submitForm.value.currentArg.trim()) {
      addCurrentArg()
    }

    const resolved = _resolveTargetAndGpus(submitForm.value)
    if (!resolved) {
      notify.warning('Please select at least one GPU')
      return
    }

    const data = _buildTaskData(submitForm.value, resolved.targets, resolved.requiredGpus)
    await tasksStore.submitTask(data)
    notify.success('Task submitted successfully')
    emit('update:visible', false)
    resetSubmitForm()
  } catch (e) {
    notify.error(e.response?.data?.detail || 'Failed to submit task')
  }
}

// Submit a single batch instance. Returns true on success, false on failure or skip.
async function _submitBatchInstance(instance, index) {
  const resolved = _resolveTargetAndGpus(instance)
  if (!resolved) return false // Skip instances with no GPUs selected

  const data = _buildTaskData(instance, resolved.targets, resolved.requiredGpus)
  await tasksStore.submitTask(data)
  return true
}

// Submit all batch instances
async function handleBatchSubmit() {
  // Save current form to active instance
  saveBatchInstance(activeBatchIndex.value)

  let successCount = 0
  let failCount = 0

  for (let i = 0; i < batchInstances.value.length; i++) {
    try {
      const submitted = await _submitBatchInstance(batchInstances.value[i], i)
      if (submitted) successCount++
    } catch (e) {
      failCount++
      console.error(`Failed to submit batch instance ${i + 1}:`, e)
    }
  }

  if (successCount > 0) {
    notify.success(`${successCount} task(s) submitted successfully`)
  }
  if (failCount > 0) {
    notify.error(`${failCount} task(s) failed to submit`)
  }

  if (successCount > 0) {
    emit('update:visible', false)
    resetSubmitForm()
    batchModeEnabled.value = false
    batchInstances.value = []
  }
}

function handleClose() {
  emit('update:visible', false)
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="batchModeEnabled ? `Submit Tasks (${batchInstances.length} instances)` : 'Submit Task'"
    width="700px"
    destroy-on-close
    @update:model-value="$emit('update:visible', $event)">
    <!-- Batch Mode Header -->
    <div class="mb-4 pb-4 border-b border-gray-200 dark:border-gray-700">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <el-switch v-model="batchModeEnabled" />
          <span class="text-sm">Batch Mode</span>
          <el-tooltip
            content="Submit multiple similar tasks with different parameters"
            placement="top">
            <span class="i-carbon-information text-gray-400"></span>
          </el-tooltip>
        </div>
        <el-button
          v-if="batchModeEnabled"
          size="small"
          type="primary"
          @click="addBatchInstance">
          <span class="i-carbon-add mr-1"></span>
          Add Instance
        </el-button>
      </div>

      <!-- Batch Instance Tabs -->
      <div
        v-if="batchModeEnabled && batchInstances.length > 0"
        class="flex flex-wrap gap-2 mt-3">
        <div
          v-for="(instance, index) in batchInstances"
          :key="index"
          class="flex items-center gap-1 px-3 py-1.5 rounded-lg cursor-pointer transition-colors"
          :class="
            activeBatchIndex === index
              ? 'bg-blue-500 text-white'
              : 'bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700'
          "
          @click="switchBatchInstance(index)">
          <span class="text-sm font-medium">Instance {{ index + 1 }}</span>
          <button
            v-if="batchInstances.length > 1"
            type="button"
            class="ml-1 hover:text-red-500"
            :class="activeBatchIndex === index ? 'text-white/70 hover:text-red-200' : 'text-gray-400'"
            @click.stop="removeBatchInstance(index)">
            <span class="i-carbon-close text-xs"></span>
          </button>
        </div>
      </div>
    </div>

    <el-form
      :model="submitForm"
      label-position="top">
      <el-form-item
        label="Command"
        required>
        <el-input
          v-model="submitForm.command"
          placeholder="e.g., python script.py" />
      </el-form-item>

      <el-form-item label="Arguments">
        <!-- Argument input area -->
        <div class="w-full">
          <div class="flex gap-2">
            <el-input
              v-model="submitForm.currentArg"
              type="textarea"
              :rows="2"
              placeholder="Type argument and press Enter to add"
              @keydown="handleArgKeydown"
              class="flex-1" />
            <el-button
              type="primary"
              @click="addCurrentArg"
              :disabled="!submitForm.currentArg.trim()">
              <span class="i-carbon-add"></span>
            </el-button>
          </div>
          <div class="text-xs text-muted mt-1">
            Press
            <kbd class="px-1 py-0.5 bg-gray-200 dark:bg-gray-700 rounded text-xs">Enter</kbd>
            to add argument.
            <kbd class="px-1 py-0.5 bg-gray-200 dark:bg-gray-700 rounded text-xs">Shift+Enter</kbd>
            or
            <kbd class="px-1 py-0.5 bg-gray-200 dark:bg-gray-700 rounded text-xs">Ctrl+Enter</kbd>
            for newline.
          </div>

          <!-- Argument list with drag-and-drop -->
          <div
            v-if="submitForm.arguments.length > 0"
            class="mt-3 space-y-2">
            <div class="text-xs text-muted mb-1">Arguments (drag to reorder):</div>
            <div class="flex flex-wrap gap-2">
              <div
                v-for="(arg, index) in submitForm.arguments"
                :key="index"
                draggable="true"
                @dragstart="onDragStart($event, index)"
                @dragover="onDragOver($event, index)"
                @drop="onDrop($event, index)"
                @dragend="onDragEnd"
                class="group flex items-start gap-1 px-2 py-1 bg-blue-100 dark:bg-blue-900/40 border border-blue-300 dark:border-blue-700 rounded cursor-move hover:bg-blue-200 dark:hover:bg-blue-900/60 transition-colors"
                :class="{ 'opacity-50': draggedArgIndex === index }">
                <span class="i-carbon-draggable text-gray-400 mt-0.5 flex-shrink-0"></span>
                <span class="font-mono text-sm whitespace-pre-wrap break-all max-w-xs">{{ arg }}</span>
                <button
                  type="button"
                  @click="removeArg(index)"
                  class="ml-1 text-gray-400 hover:text-red-500 flex-shrink-0">
                  <span class="i-carbon-close text-xs"></span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </el-form-item>

      <el-form-item label="Environment Variables">
        <el-input
          v-model="submitForm.env_vars"
          type="textarea"
          :rows="3"
          placeholder="KEY=value (one per line)" />
      </el-form-item>

      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <el-form-item label="CPU Cores (0 = no limit)">
          <el-input-number
            v-model="submitForm.required_cores"
            :min="0"
            :max="128"
            class="w-full" />
        </el-form-item>

        <el-form-item label="Memory (bytes)">
          <el-input-number
            v-model="submitForm.required_memory_bytes"
            :min="0"
            placeholder="Optional"
            class="w-full" />
        </el-form-item>
      </div>

      <el-form-item label="Image Source">
        <el-radio-group
          v-model="submitForm.imageSource"
          class="mb-2">
          <el-radio value="tarball">Tarball</el-radio>
          <el-radio value="registry">Registry Image</el-radio>
        </el-radio-group>
        <el-select
          v-if="submitForm.imageSource === 'tarball'"
          v-model="submitForm.container_name"
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
          v-model="submitForm.registry_image"
          placeholder="e.g. ubuntu:22.04, nvidia/cuda:12.0-base" />
      </el-form-item>

      <!-- GPU Feature Toggle -->
      <el-form-item label="Enable GPU Selection">
        <el-switch v-model="submitForm.gpuFeatureEnabled" />
        <span class="text-muted text-xs ml-2">Toggle to select specific GPUs instead of a node</span>
      </el-form-item>

      <!-- Node Selection (when GPU feature is OFF) -->
      <el-form-item
        v-if="!submitForm.gpuFeatureEnabled"
        label="Target Node">
        <el-select
          v-model="submitForm.targets"
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
          v-model="submitForm.selectedGpus"
          v-model:expanded-nodes="expandedGpuNodes" />
      </el-form-item>

      <!-- NUMA Node Selection -->
      <el-form-item
        v-if="selectedRunner && availableNumaNodes.length > 0"
        label="NUMA Node">
        <el-select
          v-model="submitForm.target_numa_node_id"
          placeholder="No NUMA affinity (use any)"
          clearable
          class="w-full">
          <el-option
            v-for="numa in availableNumaNodes"
            :key="numa.id"
            :label="numa.label"
            :value="numa.id" />
        </el-select>
        <div class="text-xs text-muted mt-1">Pin task to a specific NUMA node for better memory locality</div>
      </el-form-item>

      <!-- IP Reservation -->
      <el-form-item label="IP Reservation">
        <IpReservation
          ref="ipReservationRef"
          :runner="selectedRunner"
          @update:token="handleIpTokenUpdate" />
      </el-form-item>

      <el-form-item>
        <el-checkbox v-model="submitForm.privileged">Run with privileged mode</el-checkbox>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="handleClose">Cancel</el-button>
      <el-button
        v-if="batchModeEnabled"
        type="primary"
        :loading="tasksStore.submitting"
        @click="handleBatchSubmit">
        Submit {{ batchInstances.length }} Task(s)
      </el-button>
      <el-button
        v-else
        type="primary"
        :loading="tasksStore.submitting"
        @click="handleSubmit">
        Submit
      </el-button>
    </template>
  </el-dialog>
</template>
