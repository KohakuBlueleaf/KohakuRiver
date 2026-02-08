<script setup>
/**
 * Pending Approvals Tab
 *
 * Displays tasks awaiting admin/operator approval with approve/reject actions.
 */

import { ElMessage } from 'element-plus'
import { tasksAPI } from '@/utils/api/tasks'

// Pending approvals state
const pendingTasks = ref([])
const pendingLoading = ref(false)

// Rejection dialog
const showRejectDialog = ref(false)
const rejectTaskId = ref(null)
const rejectReason = ref('')

// Fetch pending approval tasks
async function fetchPendingTasks() {
  pendingLoading.value = true
  try {
    const response = await tasksAPI.listPendingApproval()
    pendingTasks.value = response.data
  } catch (err) {
    ElMessage.error('Failed to fetch pending tasks')
    console.error(err)
  } finally {
    pendingLoading.value = false
  }
}

// Approve task
async function approveTask(taskId) {
  try {
    await tasksAPI.approve(taskId)
    ElMessage.success('Task approved')
    fetchPendingTasks()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || 'Failed to approve task')
  }
}

// Open reject dialog
function openRejectDialog(taskId) {
  rejectTaskId.value = taskId
  rejectReason.value = ''
  showRejectDialog.value = true
}

// Reject task
async function rejectTask() {
  try {
    await tasksAPI.reject(rejectTaskId.value, rejectReason.value || null)
    ElMessage.success('Task rejected')
    showRejectDialog.value = false
    fetchPendingTasks()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || 'Failed to reject task')
  }
}

// Format date
function formatDate(dateStr) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString()
}

// Format command for display (truncate)
function formatCommand(task) {
  const cmd = task.command || ''
  return cmd.length > 50 ? cmd.substring(0, 50) + '...' : cmd
}

// Load data on mount
onMounted(() => {
  fetchPendingTasks()
})

defineExpose({ fetchPendingTasks })
</script>

<template>
  <div class="space-y-4">
    <div class="flex justify-end">
      <el-button
        @click="fetchPendingTasks"
        :loading="pendingLoading">
        <span class="i-carbon-renew mr-1"></span>
        Refresh
      </el-button>
    </div>

    <el-table
      :data="pendingTasks"
      v-loading="pendingLoading"
      stripe
      style="width: 100%">
      <el-table-column
        prop="task_id"
        label="Task ID"
        width="180">
        <template #default="{ row }">
          <code class="text-xs">{{ row.task_id }}</code>
        </template>
      </el-table-column>
      <el-table-column
        label="Requester"
        width="120">
        <template #default="{ row }">
          {{ row.owner_username || '-' }}
        </template>
      </el-table-column>
      <el-table-column
        prop="task_type"
        label="Type"
        width="90" />
      <el-table-column
        label="Command"
        min-width="200">
        <template #default="{ row }">
          <span
            class="font-mono text-xs"
            :title="row.command">
            {{ formatCommand(row) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column
        label="Resources"
        width="120">
        <template #default="{ row }">{{ row.required_cores }} cores</template>
      </el-table-column>
      <el-table-column
        label="Submitted"
        width="150">
        <template #default="{ row }">
          {{ formatDate(row.submitted_at) }}
        </template>
      </el-table-column>
      <el-table-column
        label="Actions"
        width="160"
        fixed="right">
        <template #default="{ row }">
          <div class="flex gap-1">
            <el-button
              size="small"
              type="success"
              @click="approveTask(row.task_id)">
              Approve
            </el-button>
            <el-button
              size="small"
              type="danger"
              @click="openRejectDialog(row.task_id)">
              Reject
            </el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <div
      v-if="pendingTasks.length === 0 && !pendingLoading"
      class="text-center py-8 text-muted">
      No pending approvals
    </div>

    <!-- Reject Task Dialog -->
    <el-dialog
      v-model="showRejectDialog"
      title="Reject Task"
      width="400">
      <el-form>
        <el-form-item label="Reason (optional)">
          <el-input
            v-model="rejectReason"
            type="textarea"
            :rows="3"
            placeholder="Enter rejection reason..." />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRejectDialog = false">Cancel</el-button>
        <el-button
          type="danger"
          @click="rejectTask">
          Reject
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>
