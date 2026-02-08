<script setup>
/**
 * Task Detail Dialog Component
 *
 * Displays task details with tabs:
 * - Info: status, basic info grid, command, resources, timing, env vars, error
 * - stdout: standard output log viewer
 * - stderr: standard error log viewer
 */

import { useTasksStore } from '@/stores/tasks'

import { ACTIVE_STATUSES } from '@/utils/constants'
import { formatBytes, formatDate, formatRequiredGpus } from '@/utils/format'

const props = defineProps({
  visible: {
    type: Boolean,
    required: true,
  },
  task: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['update:visible', 'pause', 'resume', 'restart', 'kill', 'delete'])

const tasksStore = useTasksStore()

// Detail tab state
const detailTab = ref('info')
const logContent = ref('')
const logLoading = ref(false)

// Reset state when dialog opens with a new task
watch(
  () => props.visible,
  (newVal) => {
    if (newVal) {
      detailTab.value = 'info'
      logContent.value = ''
    }
  }
)

// Load logs when switching tabs
async function loadLogs(type) {
  if (!props.task) return
  logLoading.value = true
  try {
    const content = await tasksStore.getTaskLogs(props.task.task_id, type, 1000)
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

function handleClose() {
  emit('update:visible', false)
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="`Task #${task?.task_id}`"
    width="90%"
    class="max-w-4xl"
    top="5vh"
    @update:model-value="$emit('update:visible', $event)">
    <template v-if="task">
      <el-tabs v-model="detailTab">
        <!-- Info Tab -->
        <el-tab-pane
          label="Info"
          name="info">
          <div class="space-y-6">
            <!-- Status Section -->
            <div class="flex items-center justify-between">
              <StatusBadge :status="task.status" />
              <div class="flex items-center gap-2">
                <template v-if="isActive(task.status)">
                  <el-button
                    v-if="task.status === 'running'"
                    size="small"
                    @click="$emit('pause', task.task_id)">
                    <span class="i-carbon-pause mr-1"></span>
                    Pause
                  </el-button>
                  <el-button
                    v-if="task.status === 'paused'"
                    size="small"
                    type="success"
                    @click="$emit('resume', task.task_id)">
                    <span class="i-carbon-play mr-1"></span>
                    Resume
                  </el-button>
                  <el-button
                    size="small"
                    type="warning"
                    @click="$emit('restart', task.task_id)">
                    <span class="i-carbon-restart mr-1"></span>
                    Restart
                  </el-button>
                  <el-button
                    size="small"
                    type="danger"
                    @click="$emit('kill', task.task_id)">
                    <span class="i-carbon-stop mr-1"></span>
                    Kill
                  </el-button>
                </template>
                <el-popconfirm
                  v-else
                  title="Delete this task?"
                  @confirm="$emit('delete', task.task_id)">
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
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              <div class="p-4 bg-app-surface rounded-lg">
                <div class="text-sm text-muted mb-1">Task ID</div>
                <div class="font-mono text-sm break-all">{{ task.task_id }}</div>
              </div>
              <div class="p-4 bg-app-surface rounded-lg">
                <div class="text-sm text-muted mb-1">Type</div>
                <div>{{ task.task_type || 'command' }}</div>
              </div>
              <div class="p-4 bg-app-surface rounded-lg">
                <div class="text-sm text-muted mb-1">Node</div>
                <div>{{ getNodeName(task.assigned_node) }}</div>
              </div>
              <div class="p-4 bg-app-surface rounded-lg">
                <div class="text-sm text-muted mb-1">Container</div>
                <div>{{ task.container_name || '-' }}</div>
              </div>
              <div class="p-4 bg-app-surface rounded-lg">
                <div class="text-sm text-muted mb-1">Creator</div>
                <div>{{ task.owner_username || '-' }}</div>
              </div>
              <div class="p-4 bg-app-surface rounded-lg">
                <div class="text-sm text-muted mb-1">Approver</div>
                <div v-if="task.approved_by_username">{{ task.approved_by_username }}</div>
                <div
                  v-else-if="task.status === 'pending_approval'"
                  class="text-yellow-500">
                  Pending
                </div>
                <div v-else>-</div>
              </div>
            </div>

            <!-- Command Section -->
            <div class="p-4 bg-app-surface rounded-lg">
              <div class="text-sm text-muted mb-2">Command</div>
              <pre
                class="font-mono text-sm bg-gray-900 text-gray-100 p-3 rounded overflow-x-auto whitespace-pre-wrap"
                >{{ formatFullCommand(task) }}</pre
              >
            </div>

            <!-- Resources Grid -->
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <div class="p-4 bg-app-surface rounded-lg text-center">
                <div class="text-2xl font-bold text-blue-500">{{ task.required_cores }}</div>
                <div class="text-sm text-muted">CPU Cores</div>
              </div>
              <div class="p-4 bg-app-surface rounded-lg text-center">
                <div class="text-2xl font-bold text-green-500">
                  {{ task.required_memory_bytes ? formatBytes(task.required_memory_bytes) : '-' }}
                </div>
                <div class="text-sm text-muted">Memory</div>
              </div>
              <div class="p-4 bg-app-surface rounded-lg text-center">
                <div class="text-2xl font-bold text-yellow-500">
                  {{ formatRequiredGpus(task.required_gpus) }}
                </div>
                <div class="text-sm text-muted">GPUs</div>
              </div>
              <div
                v-if="task.exit_code !== null && task.exit_code !== undefined"
                class="p-4 bg-app-surface rounded-lg text-center">
                <div
                  class="text-2xl font-bold"
                  :class="task.exit_code === 0 ? 'text-green-500' : 'text-red-500'">
                  {{ task.exit_code }}
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
                  <span class="ml-2">{{ formatDate(task.submitted_at) }}</span>
                </div>
                <div>
                  <span class="text-muted">Started:</span>
                  <span class="ml-2">{{ task.started_at ? formatDate(task.started_at) : '-' }}</span>
                </div>
                <div>
                  <span class="text-muted">Completed:</span>
                  <span class="ml-2">
                    {{ task.completed_at ? formatDate(task.completed_at) : '-' }}
                  </span>
                </div>
              </div>
            </div>

            <!-- Environment Variables -->
            <div
              v-if="task.env_vars && Object.keys(task.env_vars).length > 0"
              class="p-4 bg-app-surface rounded-lg">
              <div class="text-sm text-muted mb-2">Environment Variables</div>
              <div class="font-mono text-xs bg-gray-900 text-gray-100 p-3 rounded overflow-x-auto">
                <div
                  v-for="(value, key) in task.env_vars"
                  :key="key">
                  <span class="text-blue-400">{{ key }}</span>
                  =
                  <span class="text-green-400">{{ value }}</span>
                </div>
              </div>
            </div>

            <!-- Error Message -->
            <div
              v-if="task.error_message"
              class="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
              <div class="text-sm text-red-600 dark:text-red-400 mb-2">Error</div>
              <div class="font-mono text-sm text-red-700 dark:text-red-300">{{ task.error_message }}</div>
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
      <el-button @click="handleClose">Close</el-button>
    </template>
  </el-dialog>
</template>
