<script setup>
/**
 * Task Management Page
 *
 * Provides interface for submitting and managing command tasks.
 * Features:
 * - Task submission with command, arguments, and resource requirements
 * - Real-time task status monitoring with polling
 * - Filtering by status and search
 * - Task detail view with logs (stdout/stderr)
 * - Task control (pause, resume, kill, restart, delete)
 */

import { useClusterStore } from '@/stores/cluster'
import { useDockerStore } from '@/stores/docker'
import { useTasksStore } from '@/stores/tasks'

import { useNotification } from '@/composables/useNotification'
import { usePolling } from '@/composables/usePolling'

import { ACTIVE_STATUSES } from '@/utils/constants'
import { formatBytes, formatDate, formatRelativeTime, formatRequiredGpus, formatTaskId } from '@/utils/format'

import IpReservation from '@/components/common/IpReservation.vue'

const tasksStore = useTasksStore()
const clusterStore = useClusterStore()
const dockerStore = useDockerStore()
const notify = useNotification()

// Filters
const statusFilter = ref('')
const searchQuery = ref('')

// Pagination
const currentPage = ref(1)
const pageSize = ref(20)

// Dialogs
const submitDialogVisible = ref(false)
const detailDialogVisible = ref(false)
const selectedTask = ref(null)
const detailTab = ref('info')
const logContent = ref('')
const logLoading = ref(false)

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
  container_name: null,
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

// IP Reservation component ref
const ipReservationRef = ref(null)

// Computed: selected runner (either from node selection or GPU selection)
const selectedRunner = computed(() => {
  if (submitForm.value.gpuFeatureEnabled) {
    const gpuInfo = getSelectedGpuInfo()
    return gpuInfo?.hostname || null
  }
  return submitForm.value.targets || null
})

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
  submitForm.value.target_numa_node_id = null
})

// Check if another GPU node is already selected (for disabling other nodes)
function isAnotherGpuNodeSelected(hostname) {
  const selectedNode = Object.keys(submitForm.value.selectedGpus).find(
    (h) => submitForm.value.selectedGpus[h] && submitForm.value.selectedGpus[h].length > 0
  )
  return selectedNode !== undefined && selectedNode !== hostname
}

// Get the selected GPU node hostname and GPU IDs
function getSelectedGpuInfo() {
  for (const hostname in submitForm.value.selectedGpus) {
    if (submitForm.value.selectedGpus[hostname] && submitForm.value.selectedGpus[hostname].length > 0) {
      return { hostname, gpuIds: submitForm.value.selectedGpus[hostname] }
    }
  }
  return null
}

// Initialize selectedGpus for nodes
function initializeGpuSelections() {
  submitForm.value.selectedGpus = {}
  for (const node of nodesWithGpus.value) {
    submitForm.value.selectedGpus[node.hostname] = []
  }
}

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

// Format MiB for GPU display
function formatGpuMemory(mib) {
  if (!mib) return ''
  if (mib >= 1024) {
    return `${(mib / 1024).toFixed(0)} GB`
  }
  return `${mib.toFixed(0)} MB`
}

// Argument list drag state
const draggedArgIndex = ref(null)

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

// Polling
const { start: startPolling } = usePolling(() => {
  fetchTasks()
}, 5000)

onMounted(async () => {
  await Promise.all([clusterStore.fetchNodes(), dockerStore.fetchTarballs()])
  startPolling()
})

async function fetchTasks() {
  const params = {
    limit: pageSize.value,
    offset: (currentPage.value - 1) * pageSize.value,
  }
  if (statusFilter.value) {
    params.status = statusFilter.value
  }
  await tasksStore.fetchTasks(params)
}

const filteredTasks = computed(() => {
  let tasks = tasksStore.tasks
  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    tasks = tasks.filter(
      (t) =>
        t.command?.toLowerCase().includes(query) ||
        t.task_id?.toString().includes(query) ||
        t.assigned_node?.toLowerCase().includes(query)
    )
  }
  return tasks
})

async function handleSubmit() {
  try {
    // Add any pending argument in the input field
    if (submitForm.value.currentArg.trim()) {
      addCurrentArg()
    }

    // Determine target and GPUs based on mode
    let targets = null
    let requiredGpus = null

    if (submitForm.value.gpuFeatureEnabled) {
      // GPU mode - get selected GPU info
      const gpuInfo = getSelectedGpuInfo()
      if (!gpuInfo) {
        notify.warning('Please select at least one GPU')
        return
      }
      targets = [gpuInfo.hostname]
      requiredGpus = [gpuInfo.gpuIds]
    } else {
      // Node mode
      targets = submitForm.value.targets ? [submitForm.value.targets] : null
    }

    const data = {
      task_type: 'command',
      command: submitForm.value.command,
      arguments: submitForm.value.arguments,
      env_vars: submitForm.value.env_vars
        ? Object.fromEntries(
            submitForm.value.env_vars
              .split('\n')
              .filter(Boolean)
              .map((line) => line.split('=').map((s) => s.trim()))
          )
        : {},
      required_cores: submitForm.value.required_cores,
      required_memory_bytes: submitForm.value.required_memory_bytes,
      container_name: submitForm.value.container_name || null,
      targets: targets,
      required_gpus: requiredGpus,
      privileged: submitForm.value.privileged || null,
      ip_reservation_token: submitForm.value.ip_reservation_token || null,
      target_numa_node_id: submitForm.value.target_numa_node_id,
    }

    await tasksStore.submitTask(data)
    notify.success('Task submitted successfully')
    submitDialogVisible.value = false
    resetSubmitForm()
  } catch (e) {
    notify.error(e.response?.data?.detail || 'Failed to submit task')
  }
}

function resetSubmitForm() {
  submitForm.value = {
    command: '',
    arguments: [],
    currentArg: '',
    env_vars: '',
    required_cores: 0,
    required_memory_bytes: null,
    container_name: null,
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
    container_name: submitForm.value.container_name,
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
    submitForm.value.container_name = instance.container_name
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

// Submit all batch instances
async function handleBatchSubmit() {
  // Save current form to active instance
  saveBatchInstance(activeBatchIndex.value)

  let successCount = 0
  let failCount = 0

  for (let i = 0; i < batchInstances.value.length; i++) {
    const instance = batchInstances.value[i]

    try {
      // Determine target and GPUs based on mode
      let targets = null
      let requiredGpus = null

      if (instance.gpuFeatureEnabled) {
        for (const hostname in instance.selectedGpus) {
          if (instance.selectedGpus[hostname]?.length > 0) {
            targets = [hostname]
            requiredGpus = [instance.selectedGpus[hostname]]
            break
          }
        }
        if (!targets) continue // Skip instances with no GPUs selected
      } else {
        targets = instance.targets ? [instance.targets] : null
      }

      const data = {
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
        container_name: instance.container_name || null,
        targets: targets,
        required_gpus: requiredGpus,
        privileged: instance.privileged || null,
        ip_reservation_token: instance.ip_reservation_token || null,
        target_numa_node_id: instance.target_numa_node_id,
      }

      await tasksStore.submitTask(data)
      successCount++
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
    submitDialogVisible.value = false
    resetSubmitForm()
    batchModeEnabled.value = false
    batchInstances.value = []
  }
}

async function handleKill(taskId) {
  try {
    await tasksStore.killTask(taskId)
    notify.success('Task kill requested')
  } catch (e) {
    notify.error('Failed to kill task')
  }
}

async function handleRestart(taskId) {
  try {
    await tasksStore.restartTask(taskId)
    notify.success('Task restart requested')
  } catch (e) {
    notify.error('Failed to restart task')
  }
}

async function handlePause(taskId) {
  try {
    await tasksStore.pauseTask(taskId)
    notify.success('Task paused')
  } catch (e) {
    notify.error('Failed to pause task')
  }
}

async function handleResume(taskId) {
  try {
    await tasksStore.resumeTask(taskId)
    notify.success('Task resumed')
  } catch (e) {
    notify.error('Failed to resume task')
  }
}

async function handleDelete(taskId) {
  try {
    await tasksStore.deleteTask(taskId)
    notify.success('Task deleted')
    if (selectedTask.value?.task_id === taskId) {
      detailDialogVisible.value = false
    }
  } catch (e) {
    notify.error('Failed to delete task')
  }
}

async function openDetail(task) {
  selectedTask.value = task
  detailTab.value = 'info'
  logContent.value = ''
  detailDialogVisible.value = true
}

async function loadLogs(type) {
  if (!selectedTask.value) return
  logLoading.value = true
  try {
    const content = await tasksStore.getTaskLogs(selectedTask.value.task_id, type, 1000)
    logContent.value = content || '(empty)'
  } catch (e) {
    logContent.value = 'Failed to load logs'
  } finally {
    logLoading.value = false
  }
}

watch(detailTab, (newTab) => {
  if (newTab === 'stdout') {
    loadLogs('stdout')
  } else if (newTab === 'stderr') {
    loadLogs('stderr')
  }
})

function isActive(status) {
  return ACTIVE_STATUSES.includes(status)
}

// Format argument for shell display (quote if needed)
function shellQuote(arg) {
  // If arg contains spaces, newlines, quotes, or special chars, quote it
  if (/[\s"'`$\\!*?#~<>|;&(){}[\]]/.test(arg) || arg.includes('\n')) {
    // Use single quotes, escape any existing single quotes
    return "'" + arg.replace(/'/g, "'\\''") + "'"
  }
  return arg
}

// Format full command with arguments for display
function formatFullCommand(task) {
  if (!task) return ''
  let cmd = task.command || ''
  if (task.arguments?.length) {
    cmd += ' ' + task.arguments.map(shellQuote).join(' ')
  }
  return cmd
}

function getNodeName(node) {
  if (!node) return '-'
  return typeof node === 'object' ? node.hostname : node
}
</script>

<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div>
        <h2 class="page-title mb-0">Tasks</h2>
        <p class="text-muted">
          {{ tasksStore.runningTasks.length }} running, {{ tasksStore.pendingTasks.length }} pending
        </p>
      </div>
      <el-button
        type="primary"
        @click="submitDialogVisible = true">
        <span class="i-carbon-add mr-2"></span>
        Submit Task
      </el-button>
    </div>

    <!-- Filters -->
    <div class="card">
      <div class="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
        <el-input
          v-model="searchQuery"
          placeholder="Search tasks..."
          clearable
          class="w-full sm:w-64">
          <template #prefix>
            <span class="i-carbon-search"></span>
          </template>
        </el-input>

        <el-select
          v-model="statusFilter"
          placeholder="All statuses"
          clearable
          class="w-full sm:w-40"
          @change="fetchTasks">
          <el-option
            label="All"
            value="" />
          <el-option
            label="Running"
            value="running" />
          <el-option
            label="Pending"
            value="pending" />
          <el-option
            label="Completed"
            value="completed" />
          <el-option
            label="Failed"
            value="failed" />
          <el-option
            label="Killed"
            value="killed" />
        </el-select>

        <el-button
          @click="fetchTasks"
          class="w-full sm:w-auto">
          <span class="i-carbon-renew mr-2"></span>
          Refresh
        </el-button>
      </div>
    </div>

    <!-- Tasks Table -->
    <div class="card p-0">
      <div
        v-if="tasksStore.loading && tasksStore.tasks.length === 0"
        class="text-center py-12">
        <el-icon class="is-loading text-4xl text-blue-500"><i class="i-carbon-renew"></i></el-icon>
      </div>

      <EmptyState
        v-else-if="filteredTasks.length === 0"
        icon="i-carbon-task"
        title="No tasks found"
        description="Submit a new task to get started.">
        <template #action>
          <el-button
            type="primary"
            @click="submitDialogVisible = true">
            Submit Task
          </el-button>
        </template>
      </EmptyState>

      <div
        v-else
        class="overflow-x-auto">
        <table class="table">
          <thead class="table-header">
            <tr>
              <th class="table-cell">Task ID</th>
              <th class="table-cell">Command</th>
              <th class="table-cell">Status</th>
              <th class="table-cell">Node</th>
              <th class="table-cell hidden sm:table-cell">Resources</th>
              <th class="table-cell hidden md:table-cell">Submitted</th>
              <th class="table-cell">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="task in filteredTasks"
              :key="task.task_id"
              class="table-row cursor-pointer hover:bg-blue-50 dark:hover:bg-blue-900/20"
              @click="openDetail(task)">
              <td class="table-cell font-mono text-sm">
                <span :title="String(task.task_id)">{{ formatTaskId(task.task_id) }}</span>
              </td>
              <td class="table-cell">
                <div
                  class="max-w-32 sm:max-w-xs truncate"
                  :title="task.command">
                  {{ task.command }}
                </div>
              </td>
              <td class="table-cell">
                <StatusBadge :status="task.status" />
              </td>
              <td class="table-cell">
                <span
                  v-if="task.assigned_node"
                  class="text-sm">
                  {{ getNodeName(task.assigned_node) }}
                </span>
                <span
                  v-else
                  class="text-muted">
                  -
                </span>
              </td>
              <td class="table-cell text-sm hidden sm:table-cell">
                <div>{{ task.required_cores }} cores</div>
              </td>
              <td class="table-cell text-muted text-sm hidden md:table-cell">
                {{ formatRelativeTime(task.submitted_at) }}
              </td>
              <td
                class="table-cell"
                @click.stop>
                <div class="flex items-center gap-1 flex-wrap">
                  <!-- Control buttons for active tasks -->
                  <template v-if="isActive(task.status)">
                    <el-tooltip
                      v-if="task.status === 'running'"
                      content="Pause">
                      <el-button
                        size="small"
                        @click="handlePause(task.task_id)">
                        <span class="i-carbon-pause"></span>
                      </el-button>
                    </el-tooltip>
                    <el-tooltip
                      v-if="task.status === 'paused'"
                      content="Resume">
                      <el-button
                        size="small"
                        type="success"
                        @click="handleResume(task.task_id)">
                        <span class="i-carbon-play"></span>
                      </el-button>
                    </el-tooltip>
                    <el-tooltip content="Restart">
                      <el-button
                        size="small"
                        type="warning"
                        @click="handleRestart(task.task_id)">
                        <span class="i-carbon-restart"></span>
                      </el-button>
                    </el-tooltip>
                    <el-tooltip content="Kill">
                      <el-button
                        size="small"
                        type="danger"
                        @click="handleKill(task.task_id)">
                        <span class="i-carbon-stop"></span>
                      </el-button>
                    </el-tooltip>
                  </template>

                  <!-- Delete button for inactive tasks -->
                  <el-popconfirm
                    v-else
                    title="Delete this task?"
                    @confirm="handleDelete(task.task_id)">
                    <template #reference>
                      <el-button
                        size="small"
                        type="danger">
                        <span class="i-carbon-trash-can"></span>
                      </el-button>
                    </template>
                  </el-popconfirm>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div
        v-if="filteredTasks.length > 0"
        class="p-4 border-t border-gray-200 dark:border-gray-700">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="tasksStore.tasks.length"
          layout="prev, pager, next"
          @current-change="fetchTasks" />
      </div>
    </div>

    <!-- Submit Dialog -->
    <el-dialog
      v-model="submitDialogVisible"
      :title="batchModeEnabled ? `Submit Tasks (${batchInstances.length} instances)` : 'Submit Task'"
      width="700px"
      destroy-on-close>
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

        <el-form-item label="Container Environment">
          <el-select
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
                  v-model="submitForm.selectedGpus[node.hostname]"
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
        <el-button @click="submitDialogVisible = false">Cancel</el-button>
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

    <!-- Task Detail Dialog -->
    <el-dialog
      v-model="detailDialogVisible"
      :title="`Task #${selectedTask?.task_id}`"
      width="90%"
      class="max-w-4xl"
      top="5vh">
      <template v-if="selectedTask">
        <el-tabs v-model="detailTab">
          <!-- Info Tab -->
          <el-tab-pane
            label="Info"
            name="info">
            <div class="space-y-6">
              <!-- Status Section -->
              <div class="flex items-center justify-between">
                <StatusBadge :status="selectedTask.status" />
                <div class="flex items-center gap-2">
                  <template v-if="isActive(selectedTask.status)">
                    <el-button
                      v-if="selectedTask.status === 'running'"
                      size="small"
                      @click="handlePause(selectedTask.task_id)">
                      <span class="i-carbon-pause mr-1"></span>
                      Pause
                    </el-button>
                    <el-button
                      v-if="selectedTask.status === 'paused'"
                      size="small"
                      type="success"
                      @click="handleResume(selectedTask.task_id)">
                      <span class="i-carbon-play mr-1"></span>
                      Resume
                    </el-button>
                    <el-button
                      size="small"
                      type="warning"
                      @click="handleRestart(selectedTask.task_id)">
                      <span class="i-carbon-restart mr-1"></span>
                      Restart
                    </el-button>
                    <el-button
                      size="small"
                      type="danger"
                      @click="handleKill(selectedTask.task_id)">
                      <span class="i-carbon-stop mr-1"></span>
                      Kill
                    </el-button>
                  </template>
                  <el-popconfirm
                    v-else
                    title="Delete this task?"
                    @confirm="handleDelete(selectedTask.task_id)">
                    <template #reference>
                      <el-button
                        size="small"
                        type="danger">
                        <span class="i-carbon-trash-can mr-1"></span>
                        Delete
                      </el-button>
                    </template>
                  </el-popconfirm>
                </div>
              </div>

              <!-- Basic Info Grid -->
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div class="p-4 bg-app-surface rounded-lg">
                  <div class="text-sm text-muted mb-1">Task ID</div>
                  <div class="font-mono text-sm break-all">{{ selectedTask.task_id }}</div>
                </div>
                <div class="p-4 bg-app-surface rounded-lg">
                  <div class="text-sm text-muted mb-1">Type</div>
                  <div>{{ selectedTask.task_type || 'command' }}</div>
                </div>
                <div class="p-4 bg-app-surface rounded-lg">
                  <div class="text-sm text-muted mb-1">Node</div>
                  <div>{{ getNodeName(selectedTask.assigned_node) }}</div>
                </div>
                <div class="p-4 bg-app-surface rounded-lg">
                  <div class="text-sm text-muted mb-1">Container</div>
                  <div>{{ selectedTask.container_name || '-' }}</div>
                </div>
              </div>

              <!-- Command Section -->
              <div class="p-4 bg-app-surface rounded-lg">
                <div class="text-sm text-muted mb-2">Command</div>
                <pre
                  class="font-mono text-sm bg-gray-900 text-gray-100 p-3 rounded overflow-x-auto whitespace-pre-wrap"
                  >{{ formatFullCommand(selectedTask) }}</pre
                >
              </div>

              <!-- Resources Grid -->
              <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
                <div class="p-4 bg-app-surface rounded-lg text-center">
                  <div class="text-2xl font-bold text-blue-500">{{ selectedTask.required_cores }}</div>
                  <div class="text-sm text-muted">CPU Cores</div>
                </div>
                <div class="p-4 bg-app-surface rounded-lg text-center">
                  <div class="text-2xl font-bold text-green-500">
                    {{ selectedTask.required_memory_bytes ? formatBytes(selectedTask.required_memory_bytes) : '-' }}
                  </div>
                  <div class="text-sm text-muted">Memory</div>
                </div>
                <div class="p-4 bg-app-surface rounded-lg text-center">
                  <div class="text-2xl font-bold text-yellow-500">
                    {{ formatRequiredGpus(selectedTask.required_gpus) }}
                  </div>
                  <div class="text-sm text-muted">GPUs</div>
                </div>
                <div
                  v-if="selectedTask.exit_code !== null && selectedTask.exit_code !== undefined"
                  class="p-4 bg-app-surface rounded-lg text-center">
                  <div
                    class="text-2xl font-bold"
                    :class="selectedTask.exit_code === 0 ? 'text-green-500' : 'text-red-500'">
                    {{ selectedTask.exit_code }}
                  </div>
                  <div class="text-sm text-muted">Exit Code</div>
                </div>
              </div>

              <!-- Timing Section -->
              <div class="p-4 bg-app-surface rounded-lg">
                <div class="text-sm text-muted mb-3">Timing</div>
                <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
                  <div>
                    <span class="text-muted">Submitted:</span>
                    <span class="ml-2">{{ formatDate(selectedTask.submitted_at) }}</span>
                  </div>
                  <div>
                    <span class="text-muted">Started:</span>
                    <span class="ml-2">{{ selectedTask.started_at ? formatDate(selectedTask.started_at) : '-' }}</span>
                  </div>
                  <div>
                    <span class="text-muted">Completed:</span>
                    <span class="ml-2">
                      {{ selectedTask.completed_at ? formatDate(selectedTask.completed_at) : '-' }}
                    </span>
                  </div>
                </div>
              </div>

              <!-- Environment Variables -->
              <div
                v-if="selectedTask.env_vars && Object.keys(selectedTask.env_vars).length > 0"
                class="p-4 bg-app-surface rounded-lg">
                <div class="text-sm text-muted mb-2">Environment Variables</div>
                <div class="font-mono text-xs bg-gray-900 text-gray-100 p-3 rounded overflow-x-auto">
                  <div
                    v-for="(value, key) in selectedTask.env_vars"
                    :key="key">
                    <span class="text-blue-400">{{ key }}</span>
                    =
                    <span class="text-green-400">{{ value }}</span>
                  </div>
                </div>
              </div>

              <!-- Error Message -->
              <div
                v-if="selectedTask.error_message"
                class="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
                <div class="text-sm text-red-600 dark:text-red-400 mb-2">Error</div>
                <div class="font-mono text-sm text-red-700 dark:text-red-300">{{ selectedTask.error_message }}</div>
              </div>
            </div>
          </el-tab-pane>

          <!-- Stdout Tab -->
          <el-tab-pane
            label="stdout"
            name="stdout">
            <div class="relative">
              <div
                v-if="logLoading"
                class="absolute inset-0 flex items-center justify-center bg-gray-900/50 z-10 rounded-lg">
                <el-icon class="is-loading text-3xl text-white"><i class="i-carbon-renew"></i></el-icon>
              </div>
              <div
                class="bg-gray-900 text-gray-100 p-4 rounded-lg font-mono text-sm max-h-[60vh] overflow-auto whitespace-pre-wrap">
                {{ logContent }}
              </div>
              <div class="mt-2 flex justify-end">
                <el-button
                  size="small"
                  @click="loadLogs('stdout')">
                  <span class="i-carbon-renew mr-1"></span>
                  Refresh
                </el-button>
              </div>
            </div>
          </el-tab-pane>

          <!-- Stderr Tab -->
          <el-tab-pane
            label="stderr"
            name="stderr">
            <div class="relative">
              <div
                v-if="logLoading"
                class="absolute inset-0 flex items-center justify-center bg-gray-900/50 z-10 rounded-lg">
                <el-icon class="is-loading text-3xl text-white"><i class="i-carbon-renew"></i></el-icon>
              </div>
              <div
                class="bg-gray-900 text-red-300 p-4 rounded-lg font-mono text-sm max-h-[60vh] overflow-auto whitespace-pre-wrap">
                {{ logContent }}
              </div>
              <div class="mt-2 flex justify-end">
                <el-button
                  size="small"
                  @click="loadLogs('stderr')">
                  <span class="i-carbon-renew mr-1"></span>
                  Refresh
                </el-button>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </template>

      <template #footer>
        <el-button @click="detailDialogVisible = false">Close</el-button>
      </template>
    </el-dialog>
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
</style>
