<script setup>
/**
 * Compute Nodes Page
 *
 * Displays cluster nodes with their resource utilization and status.
 * Features:
 * - Cards/Table view toggle
 * - CPU, memory, GPU resource monitoring
 * - NUMA topology visualization
 * - Temperature monitoring
 */

import { useClusterStore } from '@/stores/cluster'

import { usePolling } from '@/composables/usePolling'

import { formatBytes, formatPercent, formatRelativeTime } from '@/utils/format'

const clusterStore = useClusterStore()

const { start: startPolling } = usePolling(() => {
  clusterStore.fetchNodes()
}, 5000)

onMounted(() => {
  startPolling()
})

// View mode
const viewMode = ref('cards') // 'cards' or 'table'

// Expanded node for details
const expandedNode = ref(null)

function toggleExpand(hostname) {
  expandedNode.value = expandedNode.value === hostname ? null : hostname
}

function getGpuSummary(gpuInfo) {
  if (!gpuInfo || gpuInfo.length === 0) return 'No GPUs'
  const names = gpuInfo.map((g) => g.name || 'Unknown')
  const unique = [...new Set(names)]
  if (unique.length === 1) {
    return `${gpuInfo.length}x ${unique[0]}`
  }
  return `${gpuInfo.length} GPUs`
}
</script>

<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <h2 class="page-title mb-0">Compute Nodes</h2>
        <p class="text-muted">{{ clusterStore.onlineNodes.length }} online / {{ clusterStore.nodes.length }} total</p>
      </div>
      <div class="flex items-center gap-2">
        <el-button-group>
          <el-button
            :type="viewMode === 'cards' ? 'primary' : 'default'"
            @click="viewMode = 'cards'">
            <span class="i-carbon-grid mr-2"></span>
            Cards
          </el-button>
          <el-button
            :type="viewMode === 'table' ? 'primary' : 'default'"
            @click="viewMode = 'table'">
            <span class="i-carbon-list mr-2"></span>
            Table
          </el-button>
        </el-button-group>
      </div>
    </div>

    <!-- Loading -->
    <div
      v-if="clusterStore.loading && clusterStore.nodes.length === 0"
      class="text-center py-12">
      <el-icon class="is-loading text-4xl text-blue-500"><i class="i-carbon-renew"></i></el-icon>
      <p class="text-muted mt-2">Loading nodes...</p>
    </div>

    <!-- Empty State -->
    <EmptyState
      v-else-if="clusterStore.nodes.length === 0"
      icon="i-carbon-bare-metal-server"
      title="No nodes registered"
      description="Start runner nodes to register them with the cluster." />

    <!-- Cards View -->
    <div
      v-else-if="viewMode === 'cards'"
      class="grid-cards">
      <div
        v-for="node in clusterStore.nodes"
        :key="node.hostname"
        class="card-hover cursor-pointer"
        @click="toggleExpand(node.hostname)">
        <!-- Header -->
        <div class="flex items-center justify-between mb-4">
          <div class="flex items-center gap-3">
            <span class="i-carbon-bare-metal-server text-2xl text-gray-400"></span>
            <div>
              <h3 class="font-semibold text-gray-800 dark:text-white">{{ node.hostname }}</h3>
              <p class="text-xs text-muted">{{ formatRelativeTime(node.last_heartbeat) }}</p>
            </div>
          </div>
          <StatusBadge :status="node.status" />
        </div>

        <!-- Badges -->
        <div class="flex items-center gap-2 mb-3 flex-wrap">
          <el-tag
            v-if="node.runner_version"
            size="small"
            type="info">
            v{{ node.runner_version }}
          </el-tag>
          <el-tag
            v-if="node.vm_capable"
            size="small"
            type="success">
            VM Ready
          </el-tag>
          <el-tag
            v-if="node.vfio_gpus && node.vfio_gpus.length > 0"
            size="small"
            type="warning">
            {{ node.vfio_gpus.length }} VFIO GPUs
          </el-tag>
        </div>

        <!-- Resources -->
        <div class="space-y-3">
          <!-- CPU -->
          <div>
            <div class="flex justify-between text-sm mb-1">
              <span class="text-muted">CPU ({{ node.total_cores }} cores)</span>
              <span>{{ formatPercent(node.cpu_percent || 0) }}</span>
            </div>
            <ResourceBar
              :value="node.cpu_percent || 0"
              :max="100"
              color="auto"
              :show-percent="false" />
          </div>

          <!-- Memory -->
          <div>
            <div class="flex justify-between text-sm mb-1">
              <span class="text-muted">Memory</span>
              <span>{{ formatPercent(node.memory_percent || 0) }}</span>
            </div>
            <ResourceBar
              :value="node.memory_used_bytes || 0"
              :max="node.memory_total_bytes || 1"
              color="auto"
              :show-percent="false" />
            <p class="text-xs text-muted mt-1">
              {{ formatBytes(node.memory_used_bytes || 0) }} / {{ formatBytes(node.memory_total_bytes || 0) }}
            </p>
          </div>

          <!-- GPU -->
          <div class="flex items-center justify-between text-sm">
            <span class="text-muted">GPUs</span>
            <span>{{ getGpuSummary(node.gpu_info) }}</span>
          </div>

          <!-- Temperature -->
          <div
            v-if="node.current_avg_temp"
            class="flex items-center justify-between text-sm">
            <span class="text-muted">Temperature</span>
            <span :class="node.current_max_temp > 80 ? 'text-red-500' : ''">
              {{ node.current_avg_temp?.toFixed(1) }}°C (max: {{ node.current_max_temp?.toFixed(1) }}°C)
            </span>
          </div>
        </div>

        <!-- Expanded Details -->
        <div
          v-if="expandedNode === node.hostname"
          class="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
          <!-- NUMA Topology -->
          <div
            v-if="node.numa_topology"
            class="mb-3">
            <h4 class="text-sm font-medium mb-2">NUMA Topology</h4>
            <div class="space-y-1">
              <div
                v-for="(cores, numaId) in node.numa_topology"
                :key="numaId"
                class="text-xs bg-app-surface p-2 rounded">
                <span class="font-medium">NUMA {{ numaId }}:</span>
                {{ cores.length }} cores ({{ cores.slice(0, 5).join(', ') }}{{ cores.length > 5 ? '...' : '' }})
              </div>
            </div>
          </div>

          <!-- GPU Details -->
          <div v-if="node.gpu_info && node.gpu_info.length > 0">
            <h4 class="text-sm font-medium mb-2">GPU Details</h4>
            <div class="space-y-1">
              <div
                v-for="(gpu, idx) in node.gpu_info"
                :key="idx"
                class="text-xs bg-app-surface p-2 rounded">
                <div class="font-medium">{{ gpu.name || `GPU ${idx}` }}</div>
                <div
                  v-if="gpu.memory_total"
                  class="text-muted">
                  Memory: {{ formatBytes(gpu.memory_used || 0) }} / {{ formatBytes(gpu.memory_total) }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Table View -->
    <div
      v-else
      class="table-container">
      <table class="table">
        <thead class="table-header">
          <tr>
            <th class="table-cell">Hostname</th>
            <th class="table-cell">Status</th>
            <th class="table-cell">Version</th>
            <th class="table-cell">Capabilities</th>
            <th class="table-cell">Cores</th>
            <th class="table-cell">CPU %</th>
            <th class="table-cell">Memory</th>
            <th class="table-cell">GPUs</th>
            <th class="table-cell">Temperature</th>
            <th class="table-cell">Last Heartbeat</th>
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
              <span
                v-if="node.runner_version"
                class="text-sm">
                v{{ node.runner_version }}
              </span>
              <span
                v-else
                class="text-muted">
                -
              </span>
            </td>
            <td class="table-cell">
              <div class="flex items-center gap-1 flex-wrap">
                <el-tag
                  v-if="node.vm_capable"
                  size="small"
                  type="success">
                  VM
                </el-tag>
                <el-tag
                  v-if="node.vfio_gpus && node.vfio_gpus.length > 0"
                  size="small"
                  type="warning">
                  {{ node.vfio_gpus.length }} VFIO
                </el-tag>
                <span
                  v-if="!node.vm_capable && !(node.vfio_gpus && node.vfio_gpus.length > 0)"
                  class="text-muted">
                  -
                </span>
              </div>
            </td>
            <td class="table-cell">{{ node.total_cores }}</td>
            <td class="table-cell">
              <div class="flex items-center gap-2">
                <div class="w-16">
                  <ResourceBar
                    :value="node.cpu_percent || 0"
                    :max="100"
                    size="sm"
                    color="auto"
                    :show-percent="false" />
                </div>
                <span class="text-sm">{{ formatPercent(node.cpu_percent || 0) }}</span>
              </div>
            </td>
            <td class="table-cell">
              <div class="flex items-center gap-2">
                <div class="w-16">
                  <ResourceBar
                    :value="node.memory_used_bytes || 0"
                    :max="node.memory_total_bytes || 1"
                    size="sm"
                    color="auto"
                    :show-percent="false" />
                </div>
                <span class="text-sm">{{ formatBytes(node.memory_used_bytes || 0) }}</span>
              </div>
            </td>
            <td class="table-cell">{{ getGpuSummary(node.gpu_info) }}</td>
            <td class="table-cell">
              <span
                v-if="node.current_avg_temp"
                :class="node.current_max_temp > 80 ? 'text-red-500' : ''">
                {{ node.current_avg_temp?.toFixed(1) }}°C
              </span>
              <span
                v-else
                class="text-muted">
                -
              </span>
            </td>
            <td class="table-cell text-muted">{{ formatRelativeTime(node.last_heartbeat) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
