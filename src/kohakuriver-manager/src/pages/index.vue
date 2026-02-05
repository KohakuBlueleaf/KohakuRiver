<script setup>
/**
 * Dashboard Page (Home)
 *
 * Provides overview of the KohakuRiver cluster status.
 * Features:
 * - Stats overview (nodes, cores, memory, GPUs)
 * - Resource usage (CPU and memory averages)
 * - Running tasks preview
 * - Active VPS instances preview
 * - Node list with resource bars
 */

import { useClusterStore } from '@/stores/cluster'
import { useTasksStore } from '@/stores/tasks'
import { useVpsStore } from '@/stores/vps'
import { useAuthStore } from '@/stores/auth'

import { usePolling } from '@/composables/usePolling'

import { formatBytes, formatPercent } from '@/utils/format'

const clusterStore = useClusterStore()
const tasksStore = useTasksStore()
const vpsStore = useVpsStore()
const authStore = useAuthStore()

// Check if user has viewer role (can see tasks/VPS)
const canViewTasks = computed(() => authStore.hasRole('viewer'))

// Polling for real-time updates
const { start: startPolling } = usePolling(async () => {
  // Always fetch nodes and health (accessible to anony)
  await Promise.all([clusterStore.fetchNodes(), clusterStore.fetchHealth()])
  // Only fetch tasks/VPS if user has viewer role
  if (canViewTasks.value) {
    await Promise.all([tasksStore.fetchTasks({ limit: 10 }), vpsStore.fetchVpsList(true)])
  }
}, 5000)

onMounted(() => {
  startPolling()
})

const stats = computed(() => [
  {
    label: 'Online Nodes',
    value: clusterStore.onlineNodes.length,
    total: clusterStore.nodes.length,
    icon: 'i-carbon-bare-metal-server',
    color: 'text-green-500',
  },
  {
    label: 'Total Cores',
    value: clusterStore.totalCores,
    icon: 'i-carbon-chip',
    color: 'text-blue-500',
  },
  {
    label: 'Total Memory',
    value: formatBytes(clusterStore.totalMemory),
    icon: 'i-carbon-data-base',
    color: 'text-purple-500',
  },
  {
    label: 'Total GPUs',
    value: clusterStore.totalGpus,
    icon: 'i-carbon-cube',
    color: 'text-yellow-500',
  },
])
</script>

<template>
  <div class="space-y-6">
    <!-- Stats Overview -->
    <div class="grid-stats">
      <div
        v-for="stat in stats"
        :key="stat.label"
        class="stat-card">
        <span
          :class="[stat.icon, stat.color]"
          class="text-4xl mb-3 block"></span>
        <div class="stat-value">
          {{ stat.value }}
          <span
            v-if="stat.total"
            class="text-lg text-gray-500 dark:text-gray-400">
            / {{ stat.total }}
          </span>
        </div>
        <div class="stat-label">{{ stat.label }}</div>
      </div>
    </div>

    <!-- Resource Usage -->
    <div class="grid-2">
      <!-- CPU Usage -->
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">CPU Usage</h3>
          <span
            class="text-2xl font-bold"
            :class="clusterStore.avgCpuPercent > 80 ? 'text-red-500' : 'text-green-500'">
            {{ formatPercent(clusterStore.avgCpuPercent) }}
          </span>
        </div>
        <ResourceBar
          :value="clusterStore.avgCpuPercent"
          :max="100"
          color="auto"
          size="lg"
          :show-percent="false" />
        <p class="text-sm text-muted mt-2">Average across {{ clusterStore.onlineNodes.length }} online nodes</p>
      </div>

      <!-- Memory Usage -->
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">Memory Usage</h3>
          <span
            class="text-2xl font-bold"
            :class="clusterStore.avgMemoryPercent > 80 ? 'text-red-500' : 'text-green-500'">
            {{ formatPercent(clusterStore.avgMemoryPercent) }}
          </span>
        </div>
        <ResourceBar
          :value="clusterStore.usedMemory"
          :max="clusterStore.totalMemory"
          color="auto"
          size="lg"
          :show-percent="false" />
        <p class="text-sm text-muted mt-2">
          {{ formatBytes(clusterStore.usedMemory) }} / {{ formatBytes(clusterStore.totalMemory) }}
        </p>
      </div>
    </div>

    <!-- Running Tasks & VPS -->
    <div class="grid-2">
      <!-- Running Tasks -->
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">Running Tasks</h3>
          <router-link
            to="/tasks"
            class="text-blue-500 hover:text-blue-600 text-sm">
            View all
          </router-link>
        </div>

        <div
          v-if="tasksStore.runningTasks.length === 0"
          class="text-center py-8 text-muted">
          <span class="i-carbon-task text-4xl block mb-2"></span>
          No running tasks
        </div>

        <div
          v-else
          class="space-y-3">
          <div
            v-for="task in tasksStore.runningTasks.slice(0, 5)"
            :key="task.task_id"
            class="flex items-center justify-between p-3 bg-app-surface rounded-lg">
            <div class="min-w-0 flex-1">
              <div class="font-medium text-sm truncate">{{ task.command }}</div>
              <div class="text-xs text-muted">{{ task.assigned_node }} &middot; {{ task.required_cores }} cores</div>
            </div>
            <StatusBadge
              :status="task.status"
              size="sm" />
          </div>
        </div>
      </div>

      <!-- Active VPS -->
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">Active VPS</h3>
          <router-link
            to="/vps"
            class="text-blue-500 hover:text-blue-600 text-sm">
            View all
          </router-link>
        </div>

        <div
          v-if="vpsStore.runningVps.length === 0"
          class="text-center py-8 text-muted">
          <span class="i-carbon-virtual-machine text-4xl block mb-2"></span>
          No active VPS instances
        </div>

        <div
          v-else
          class="space-y-3">
          <div
            v-for="vps in vpsStore.runningVps.slice(0, 5)"
            :key="vps.task_id"
            class="flex items-center justify-between p-3 bg-app-surface rounded-lg">
            <div class="min-w-0 flex-1">
              <div class="font-medium text-sm">VPS #{{ vps.task_id }}</div>
              <div class="text-xs text-muted">{{ vps.assigned_node }} &middot; SSH Port: {{ vps.ssh_port }}</div>
            </div>
            <StatusBadge
              :status="vps.status"
              size="sm" />
          </div>
        </div>
      </div>
    </div>

    <!-- Node List -->
    <div class="card">
      <div class="card-header">
        <h3 class="card-title">Cluster Nodes</h3>
        <router-link
          to="/nodes"
          class="text-blue-500 hover:text-blue-600 text-sm">
          View details
        </router-link>
      </div>

      <div
        v-if="clusterStore.loading"
        class="text-center py-8">
        <el-icon class="is-loading text-2xl"><i class="i-carbon-renew"></i></el-icon>
      </div>

      <div
        v-else-if="clusterStore.nodes.length === 0"
        class="text-center py-8 text-muted">
        <span class="i-carbon-bare-metal-server text-4xl block mb-2"></span>
        No nodes registered
      </div>

      <div
        v-else
        class="overflow-x-auto">
        <table class="table">
          <thead class="table-header">
            <tr>
              <th class="table-cell">Hostname</th>
              <th class="table-cell">Status</th>
              <th class="table-cell">CPU</th>
              <th class="table-cell">Memory</th>
              <th class="table-cell">GPUs</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="node in clusterStore.nodes"
              :key="node.hostname"
              class="table-row">
              <td class="table-cell font-medium">{{ node.hostname }}</td>
              <td class="table-cell">
                <StatusBadge
                  :status="node.status"
                  size="sm" />
              </td>
              <td class="table-cell">
                <div class="w-24">
                  <ResourceBar
                    :value="node.cpu_percent || 0"
                    :max="100"
                    size="sm"
                    color="auto" />
                </div>
              </td>
              <td class="table-cell">
                <div class="w-24">
                  <ResourceBar
                    :value="node.memory_used_bytes || 0"
                    :max="node.memory_total_bytes || 1"
                    size="sm"
                    color="auto" />
                </div>
              </td>
              <td class="table-cell">{{ node.gpu_info?.length || 0 }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
