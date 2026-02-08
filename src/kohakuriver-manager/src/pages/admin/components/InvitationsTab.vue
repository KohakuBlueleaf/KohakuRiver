<script setup>
/**
 * Invitations Tab
 *
 * Invitation management with create dialog, token display, and revoke actions.
 */

import { ElMessage, ElMessageBox } from 'element-plus'
import { authAPI } from '@/utils/api/auth'

const props = defineProps({
  isAdmin: {
    type: Boolean,
    default: false,
  },
})

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

// Role options - operators can only create viewer invitations
const roleOptions = computed(() => {
  if (props.isAdmin) {
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

// Load data on mount
onMounted(() => {
  fetchInvitations()
})

defineExpose({ fetchInvitations })
</script>

<template>
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
  </div>
</template>
