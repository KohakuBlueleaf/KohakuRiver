<script setup>
/**
 * Admin Page
 *
 * User and invitation management for administrators and operators.
 * - Admins: Full access to users, invitations, pending approvals, VM instances
 * - Operators: View users, create viewer invitations, approve/reject tasks
 */

import { useAuthStore } from '@/stores/auth'
import ApprovalsTab from './components/ApprovalsTab.vue'
import UsersTab from './components/UsersTab.vue'
import InvitationsTab from './components/InvitationsTab.vue'
import VmInstancesTab from './components/VmInstancesTab.vue'

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
        <ApprovalsTab />
      </el-tab-pane>

      <!-- Users Tab -->
      <el-tab-pane
        label="Users"
        name="users">
        <UsersTab
          :current-user-id="authStore.user?.id"
          :is-admin="authStore.isAdmin" />
      </el-tab-pane>

      <!-- Invitations Tab -->
      <el-tab-pane
        label="Invitations"
        name="invitations">
        <InvitationsTab :is-admin="authStore.isAdmin" />
      </el-tab-pane>

      <!-- VM Instances Tab (Admin only) -->
      <el-tab-pane
        v-if="authStore.isAdmin"
        label="VM Instances"
        name="vm-instances"
        lazy>
        <VmInstancesTab />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
