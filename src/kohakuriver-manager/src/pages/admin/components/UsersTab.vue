<script setup>
/**
 * Users Tab
 *
 * User management table with role editing, enable/disable, and delete actions.
 */

import { ElMessage, ElMessageBox } from 'element-plus'
import { authAPI } from '@/utils/api/auth'

const props = defineProps({
  currentUserId: {
    type: Number,
    default: null,
  },
  isAdmin: {
    type: Boolean,
    default: false,
  },
})

// Users state
const users = ref([])
const usersLoading = ref(false)

// Role options
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

// Format date
function formatDate(dateStr) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString()
}

// Load data on mount
onMounted(() => {
  fetchUsers()
})

defineExpose({ fetchUsers })
</script>

<template>
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
            :disabled="row.id === currentUserId"
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
              v-if="row.id !== currentUserId"
              size="small"
              @click="toggleUserActive(row)">
              {{ row.is_active ? 'Disable' : 'Enable' }}
            </el-button>
            <el-button
              v-if="row.id !== currentUserId"
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
</template>
