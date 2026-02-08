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
import { formatRelativeTime, formatTaskId } from '@/utils/format'

import TaskSubmitDialog from './components/TaskSubmitDialog.vue'
import TaskDetailDialog from './components/TaskDetailDialog.vue'

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
  detailDialogVisible.value = true
}

function isActive(status) {
  return ACTIVE_STATUSES.includes(status)
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
              <th class="table-cell">Creator</th>
              <th class="table-cell">Approver</th>
              <th class="table-cell hidden lg:table-cell">Submitted</th>
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
              <td class="table-cell text-sm">
                <span v-if="task.owner_username">{{ task.owner_username }}</span>
                <span
                  v-else
                  class="text-muted">
                  -
                </span>
              </td>
              <td class="table-cell text-sm">
                <span v-if="task.approved_by_username">{{ task.approved_by_username }}</span>
                <span
                  v-else-if="task.status === 'pending_approval'"
                  class="text-yellow-500">
                  Pending
                </span>
                <span
                  v-else
                  class="text-muted">
                  -
                </span>
              </td>
              <td class="table-cell text-muted text-sm hidden lg:table-cell">
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
    <TaskSubmitDialog v-model:visible="submitDialogVisible" />

    <!-- Task Detail Dialog -->
    <TaskDetailDialog
      v-model:visible="detailDialogVisible"
      :task="selectedTask"
      @pause="handlePause"
      @resume="handleResume"
      @restart="handleRestart"
      @kill="handleKill"
      @delete="handleDelete" />
  </div>
</template>
