<script setup>
/**
 * Admin Page
 *
 * User and invitation management for administrators and operators.
 * - Admins: Full access to users, invitations, pending approvals
 * - Operators: View users, create viewer invitations, approve/reject tasks
 */

import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { authAPI } from '@/utils/api/auth'
import { tasksAPI } from '@/utils/api/tasks'

const router = useRouter()
const authStore = useAuthStore()

// Check operator+ access
watchEffect(() => {
  if (!authStore.isLoading && !authStore.isOperator) {
    router.push('/')
  }
})

// Tab state
const activeTab = ref('approvals')

// Pending approvals state
const pendingTasks = ref([])
const pendingLoading = ref(false)

// Users state
const users = ref([])
const usersLoading = ref(false)

// Invitations state
const invitations = ref([])
const invitationsLoading = ref(false)

// Create invitation dialog
const showCreateInvitation = ref(false)
const newInvitation = ref({
  role: 'viewer',
  maxUsage: 1,
  expiresHours: 72,
})
const createdInvitation = ref(null)

// Rejection dialog
const showRejectDialog = ref(false)
const rejectTaskId = ref(null)
const rejectReason = ref('')

// Role options - operators can only create viewer invitations
const roleOptions = computed(() => {
  if (authStore.isAdmin) {
    return [
      { value: 'viewer', label: 'Viewer' },
      { value: 'user', label: 'User' },
      { value: 'operator', label: 'Operator' },
      { value: 'admin', label: 'Admin' },
    ]
  }
  // Operators can only invite viewers
  return [{ value: 'viewer', label: 'Viewer' }]
})

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

// Fetch users
async function fetchUsers() {
  usersLoading.value = true
  try {
    const response = await authAPI.listUsers()
    users.value = response.data
  } catch (err) {
    ElMessage.error('Failed to fetch users')
    console.error(err)
  } finally {
    usersLoading.value = false
  }
}

// Fetch invitations
async function fetchInvitations() {
  invitationsLoading.value = true
  try {
    const response = await authAPI.listInvitations()
    invitations.value = response.data
  } catch (err) {
    ElMessage.error('Failed to fetch invitations')
    console.error(err)
  } finally {
    invitationsLoading.value = false
  }
}

// Update user role
async function updateUserRole(user, newRole) {
  try {
    await authAPI.updateUser(user.id, { role: newRole })
    user.role = newRole
    ElMessage.success(`Updated ${user.username}'s role to ${newRole}`)
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || 'Failed to update user')
  }
}

// Toggle user active status
async function toggleUserActive(user) {
  try {
    await authAPI.updateUser(user.id, { is_active: !user.is_active })
    user.is_active = !user.is_active
    ElMessage.success(`User ${user.username} ${user.is_active ? 'enabled' : 'disabled'}`)
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || 'Failed to update user')
  }
}

// Delete user
async function deleteUser(user) {
  try {
    await ElMessageBox.confirm(`Are you sure you want to delete user "${user.username}"?`, 'Delete User', {
      confirmButtonText: 'Delete',
      cancelButtonText: 'Cancel',
      type: 'warning',
    })
    await authAPI.deleteUser(user.id)
    users.value = users.value.filter((u) => u.id !== user.id)
    ElMessage.success(`User ${user.username} deleted`)
  } catch (err) {
    if (err !== 'cancel') {
      ElMessage.error(err.response?.data?.detail || 'Failed to delete user')
    }
  }
}

// Create invitation
async function createInvitation() {
  try {
    const response = await authAPI.createInvitation(
      newInvitation.value.role,
      newInvitation.value.maxUsage,
      newInvitation.value.expiresHours
    )
    createdInvitation.value = response.data
    await fetchInvitations()
    ElMessage.success('Invitation created')
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || 'Failed to create invitation')
  }
}

// Revoke invitation
async function revokeInvitation(invitation) {
  try {
    await ElMessageBox.confirm('Are you sure you want to revoke this invitation?', 'Revoke Invitation', {
      confirmButtonText: 'Revoke',
      cancelButtonText: 'Cancel',
      type: 'warning',
    })
    await authAPI.revokeInvitation(invitation.id)
    invitations.value = invitations.value.filter((i) => i.id !== invitation.id)
    ElMessage.success('Invitation revoked')
  } catch (err) {
    if (err !== 'cancel') {
      ElMessage.error(err.response?.data?.detail || 'Failed to revoke invitation')
    }
  }
}

// Copy invitation URL
function copyInvitationUrl(token) {
  const url = `${window.location.origin}/register?token=${token}`
  navigator.clipboard.writeText(url)
  ElMessage.success('Invitation URL copied to clipboard')
}

// Reset create invitation dialog
function resetCreateDialog() {
  showCreateInvitation.value = false
  createdInvitation.value = null
  newInvitation.value = { role: 'viewer', maxUsage: 1, expiresHours: 72 }
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
  fetchUsers()
  fetchInvitations()
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="text-2xl font-bold">{{ authStore.isAdmin ? 'Admin Portal' : 'Operator Portal' }}</h1>
    </div>

    <!-- Tabs -->
    <el-tabs v-model="activeTab">
      <!-- Pending Approvals Tab -->
      <el-tab-pane
        label="Pending Approvals"
        name="approvals">
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
        </div>
      </el-tab-pane>

      <!-- Users Tab -->
      <el-tab-pane
        label="Users"
        name="users">
        <div class="space-y-4">
          <el-table
            :data="users"
            v-loading="usersLoading"
            stripe
            style="width: 100%">
            <el-table-column
              prop="id"
              label="ID"
              width="60" />
            <el-table-column
              prop="username"
              label="Username"
              min-width="120" />
            <el-table-column
              prop="display_name"
              label="Display Name"
              min-width="120" />
            <el-table-column
              label="Role"
              width="130">
              <template #default="{ row }">
                <el-select
                  :model-value="row.role"
                  size="small"
                  :disabled="row.id === authStore.user?.id"
                  @change="(val) => updateUserRole(row, val)">
                  <el-option
                    v-for="opt in roleOptions"
                    :key="opt.value"
                    :value="opt.value"
                    :label="opt.label" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column
              label="Status"
              width="90">
              <template #default="{ row }">
                <el-tag
                  :type="row.is_active ? 'success' : 'danger'"
                  size="small">
                  {{ row.is_active ? 'Active' : 'Disabled' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column
              prop="created_at"
              label="Created"
              min-width="150">
              <template #default="{ row }">
                {{ formatDate(row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column
              label="Actions"
              width="180"
              fixed="right">
              <template #default="{ row }">
                <div class="flex gap-1">
                  <el-button
                    v-if="row.id !== authStore.user?.id"
                    size="small"
                    @click="toggleUserActive(row)">
                    {{ row.is_active ? 'Disable' : 'Enable' }}
                  </el-button>
                  <el-button
                    v-if="row.id !== authStore.user?.id"
                    size="small"
                    type="danger"
                    @click="deleteUser(row)">
                    Delete
                  </el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- Invitations Tab -->
      <el-tab-pane
        label="Invitations"
        name="invitations">
        <div class="space-y-4">
          <div class="flex justify-end">
            <el-button
              type="primary"
              @click="showCreateInvitation = true">
              Create Invitation
            </el-button>
          </div>

          <el-table
            :data="invitations"
            v-loading="invitationsLoading"
            stripe
            style="width: 100%">
            <el-table-column
              prop="id"
              label="ID"
              width="60" />
            <el-table-column
              label="Token"
              min-width="180">
              <template #default="{ row }">
                <div class="flex items-center gap-2">
                  <code class="text-xs">{{ row.token.substring(0, 16) }}...</code>
                  <el-button
                    size="small"
                    link
                    @click="copyInvitationUrl(row.token)">
                    Copy URL
                  </el-button>
                </div>
              </template>
            </el-table-column>
            <el-table-column
              prop="role"
              label="Role"
              width="90" />
            <el-table-column
              label="Usage"
              width="80">
              <template #default="{ row }">{{ row.usage_count }} / {{ row.max_usage }}</template>
            </el-table-column>
            <el-table-column
              label="Status"
              width="80">
              <template #default="{ row }">
                <el-tag
                  :type="row.is_valid ? 'success' : 'info'"
                  size="small">
                  {{ row.is_valid ? 'Valid' : 'Expired' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column
              label="Expires"
              min-width="150">
              <template #default="{ row }">
                {{ formatDate(row.expires_at) }}
              </template>
            </el-table-column>
            <el-table-column
              label="Actions"
              width="90"
              fixed="right">
              <template #default="{ row }">
                <el-button
                  size="small"
                  type="danger"
                  @click="revokeInvitation(row)">
                  Revoke
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- Create Invitation Dialog -->
    <el-dialog
      v-model="showCreateInvitation"
      title="Create Invitation"
      width="500"
      @close="resetCreateDialog">
      <template v-if="!createdInvitation">
        <el-form label-width="120px">
          <el-form-item label="Role">
            <el-select v-model="newInvitation.role">
              <el-option
                v-for="opt in roleOptions"
                :key="opt.value"
                :value="opt.value"
                :label="opt.label" />
            </el-select>
          </el-form-item>
          <el-form-item label="Max Usage">
            <el-input-number
              v-model="newInvitation.maxUsage"
              :min="1"
              :max="100" />
          </el-form-item>
          <el-form-item label="Expires In">
            <el-select v-model="newInvitation.expiresHours">
              <el-option
                :value="24"
                label="1 day" />
              <el-option
                :value="72"
                label="3 days" />
              <el-option
                :value="168"
                label="1 week" />
              <el-option
                :value="720"
                label="30 days" />
            </el-select>
          </el-form-item>
        </el-form>
      </template>
      <template v-else>
        <div class="space-y-4">
          <p class="text-green-500">Invitation created successfully!</p>
          <div class="p-4 bg-gray-800 rounded">
            <p class="text-sm text-gray-400 mb-2">Registration URL:</p>
            <code class="text-sm break-all">
              {{ `${window.location.origin}/register?token=${createdInvitation.token}` }}
            </code>
          </div>
          <el-button
            type="primary"
            @click="copyInvitationUrl(createdInvitation.token)">
            Copy URL
          </el-button>
        </div>
      </template>
      <template #footer>
        <span
          v-if="!createdInvitation"
          class="dialog-footer">
          <el-button @click="showCreateInvitation = false">Cancel</el-button>
          <el-button
            type="primary"
            @click="createInvitation">
            Create
          </el-button>
        </span>
        <span
          v-else
          class="dialog-footer">
          <el-button
            type="primary"
            @click="resetCreateDialog">
            Done
          </el-button>
        </span>
      </template>
    </el-dialog>

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
