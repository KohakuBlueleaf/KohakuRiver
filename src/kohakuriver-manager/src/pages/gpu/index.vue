<script setup>
/**
 * GPU Overview Page
 *
 * Displays cluster-wide GPU monitoring with detailed metrics.
 * Features:
 * - Aggregate statistics (total GPUs, avg utilization, power usage)
 * - Per-GPU cards with utilization, memory, temperature, power
 * - Table view for compact display
 * - Real-time polling for live updates
 */

import { useClusterStore } from '@/stores/cluster'

import { usePolling } from '@/composables/usePolling'

import { formatPercent } from '@/utils/format'

const clusterStore = useClusterStore()

const { start: startPolling } = usePolling(() => {
  clusterStore.fetchNodes()
}, 5000)

onMounted(() => {
  startPolling()
})

// Flatten all GPUs from all nodes into a single list with node context
const allGpus = computed(() => {
  const gpus = []
  for (const node of clusterStore.onlineNodes) {
    if (node.gpu_info && node.gpu_info.length > 0) {
      for (const gpu of node.gpu_info) {
        gpus.push({
          ...gpu,
          hostname: node.hostname,
          nodeStatus: node.status,
        })
      }
    }
  }
  return gpus
})

// Aggregate stats
const totalGpus = computed(() => allGpus.value.length)
const avgGpuUtilization = computed(() => {
  if (allGpus.value.length === 0) return 0
  const valid = allGpus.value.filter((g) => g.gpu_utilization >= 0)
  if (valid.length === 0) return 0
  return valid.reduce((sum, g) => sum + g.gpu_utilization, 0) / valid.length
})
const avgMemUtilization = computed(() => {
  if (allGpus.value.length === 0) return 0
  const valid = allGpus.value.filter((g) => g.mem_utilization >= 0)
  if (valid.length === 0) return 0
  return valid.reduce((sum, g) => sum + g.mem_utilization, 0) / valid.length
})
const avgTemperature = computed(() => {
  if (allGpus.value.length === 0) return 0
  const valid = allGpus.value.filter((g) => g.temperature >= 0)
  if (valid.length === 0) return 0
  return valid.reduce((sum, g) => sum + g.temperature, 0) / valid.length
})
const totalPowerUsage = computed(() => {
  return allGpus.value.reduce((sum, g) => sum + (g.power_usage_mw > 0 ? g.power_usage_mw : 0), 0)
})
const totalPowerLimit = computed(() => {
  return allGpus.value.reduce((sum, g) => sum + (g.power_limit_mw > 0 ? g.power_limit_mw : 0), 0)
})

// Format functions
function formatMiB(mib) {
  if (mib >= 1024) {
    return `${(mib / 1024).toFixed(1)} GiB`
  }
  return `${mib.toFixed(0)} MiB`
}

function formatPower(mw) {
  if (mw < 0) return '-'
  return `${(mw / 1000).toFixed(0)} W`
}

function formatClock(mhz) {
  if (mhz < 0) return '-'
  if (mhz >= 1000) {
    return `${(mhz / 1000).toFixed(2)} GHz`
  }
  return `${mhz} MHz`
}

// Get color class based on utilization
function getUtilizationColor(value) {
  if (value < 0) return 'text-gray-400'
  if (value < 30) return 'text-green-500'
  if (value < 70) return 'text-yellow-500'
  return 'text-red-500'
}

function getTempColor(temp) {
  if (temp < 0) return 'text-gray-400'
  if (temp < 60) return 'text-green-500'
  if (temp < 80) return 'text-yellow-500'
  return 'text-red-500'
}

// Group GPUs by node
const gpusByNode = computed(() => {
  const grouped = {}
  for (const gpu of allGpus.value) {
    if (!grouped[gpu.hostname]) {
      grouped[gpu.hostname] = []
    }
    grouped[gpu.hostname].push(gpu)
  }
  return grouped
})

// View mode
const viewMode = ref('cards') // 'cards' or 'table'
</script>

<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <h2 class="page-title mb-0">GPU Overview</h2>
        <p class="text-muted">
          {{ totalGpus }} GPU{{ totalGpus !== 1 ? 's' : '' }} across {{ Object.keys(gpusByNode).length }} node{{
            Object.keys(gpusByNode).length !== 1 ? 's' : ''
          }}
        </p>
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

    <!-- Aggregate Stats Cards -->
    <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
      <!-- Total GPUs -->
      <div class="card">
        <div class="flex items-center gap-3">
          <span class="i-carbon-chip text-2xl text-purple-500"></span>
          <div>
            <p class="text-muted text-xs">Total GPUs</p>
            <p class="text-xl font-semibold">{{ totalGpus }}</p>
          </div>
        </div>
      </div>

      <!-- Avg GPU Utilization -->
      <div class="card">
        <div class="flex items-center gap-3">
          <span class="i-carbon-activity text-2xl text-blue-500"></span>
          <div>
            <p class="text-muted text-xs">Avg GPU Usage</p>
            <p
              class="text-xl font-semibold"
              :class="getUtilizationColor(avgGpuUtilization)">
              {{ formatPercent(avgGpuUtilization) }}
            </p>
          </div>
        </div>
      </div>

      <!-- Avg Memory Utilization -->
      <div class="card">
        <div class="flex items-center gap-3">
          <span class="i-carbon-data-volume text-2xl text-green-500"></span>
          <div>
            <p class="text-muted text-xs">Avg Memory</p>
            <p
              class="text-xl font-semibold"
              :class="getUtilizationColor(avgMemUtilization)">
              {{ formatPercent(avgMemUtilization) }}
            </p>
          </div>
        </div>
      </div>

      <!-- Avg Temperature -->
      <div class="card">
        <div class="flex items-center gap-3">
          <span class="i-carbon-temperature text-2xl text-orange-500"></span>
          <div>
            <p class="text-muted text-xs">Avg Temp</p>
            <p
              class="text-xl font-semibold"
              :class="getTempColor(avgTemperature)">
              {{ avgTemperature > 0 ? `${avgTemperature.toFixed(0)}°C` : '-' }}
            </p>
          </div>
        </div>
      </div>

      <!-- Total Power Usage -->
      <div class="card">
        <div class="flex items-center gap-3">
          <span class="i-carbon-lightning text-2xl text-yellow-500"></span>
          <div>
            <p class="text-muted text-xs">Power Usage</p>
            <p class="text-xl font-semibold">{{ formatPower(totalPowerUsage) }}</p>
          </div>
        </div>
      </div>

      <!-- Power Limit -->
      <div class="card">
        <div class="flex items-center gap-3">
          <span class="i-carbon-meter text-2xl text-gray-500"></span>
          <div>
            <p class="text-muted text-xs">Power Limit</p>
            <p class="text-xl font-semibold">{{ formatPower(totalPowerLimit) }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div
      v-if="clusterStore.loading && allGpus.length === 0"
      class="text-center py-12">
      <el-icon class="is-loading text-4xl text-blue-500"><i class="i-carbon-renew"></i></el-icon>
      <p class="text-muted mt-2">Loading GPU data...</p>
    </div>

    <!-- Empty State -->
    <EmptyState
      v-else-if="allGpus.length === 0"
      icon="i-carbon-chip"
      title="No GPUs detected"
      description="No nodes with GPUs are currently online." />

    <!-- Cards View -->
    <template v-else-if="viewMode === 'cards'">
      <div
        v-for="(gpus, hostname) in gpusByNode"
        :key="hostname"
        class="space-y-4">
        <!-- Node Header -->
        <h3 class="text-lg font-semibold flex items-center gap-2">
          <span class="i-carbon-bare-metal-server text-gray-400"></span>
          {{ hostname }}
          <span class="text-sm text-muted font-normal">({{ gpus.length }} GPU{{ gpus.length !== 1 ? 's' : '' }})</span>
        </h3>

        <div class="grid-cards-fixed">
          <div
            v-for="gpu in gpus"
            :key="`${hostname}-${gpu.gpu_id}`"
            class="card w-62 flex-shrink-0">
            <!-- Header -->
            <div class="flex items-center gap-2 mb-3 mt-3">
              <span class="i-carbon-chip text-xl text-purple-500 flex-shrink-0 self-center"></span>
              <div class="overflow-hidden min-w-0">
                <h4
                  class="font-semibold text-sm text-gray-800 dark:text-white whitespace-nowrap overflow-hidden leading-tight !m-0 !mb-0.5">
                  <span class="marquee-text">{{ gpu.name || `GPU ${gpu.gpu_id}` }}</span>
                </h4>
                <p class="text-xs text-muted leading-tight !m-0">GPU {{ gpu.gpu_id }}</p>
              </div>
            </div>

            <div class="space-y-2">
              <!-- GPU Core Utilization -->
              <div>
                <div class="flex justify-between text-sm mb-1">
                  <span class="text-muted">GPU Core</span>
                  <span :class="getUtilizationColor(gpu.gpu_utilization)">
                    {{ gpu.gpu_utilization >= 0 ? formatPercent(gpu.gpu_utilization) : '-' }}
                    <span class="text-xs text-muted ml-1">{{ formatClock(gpu.graphics_clock_mhz) }}</span>
                  </span>
                </div>
                <ResourceBar
                  :value="gpu.gpu_utilization >= 0 ? gpu.gpu_utilization : 0"
                  :max="100"
                  color="auto"
                  :show-percent="false" />
              </div>

              <!-- Memory Utilization -->
              <div>
                <div class="flex justify-between text-sm mb-1">
                  <span class="text-muted">Memory</span>
                  <span :class="getUtilizationColor(gpu.mem_utilization)">
                    {{ gpu.mem_utilization >= 0 ? formatPercent(gpu.mem_utilization) : '-' }}
                    <span class="text-xs text-muted ml-1">{{ formatClock(gpu.mem_clock_mhz) }}</span>
                  </span>
                </div>
                <ResourceBar
                  :value="gpu.memory_used_mib || 0"
                  :max="gpu.memory_total_mib || 1"
                  color="auto"
                  :show-percent="false" />
                <p class="text-xs text-muted mt-1">
                  {{ formatMiB(gpu.memory_used_mib || 0) }} / {{ formatMiB(gpu.memory_total_mib || 0) }}
                </p>
              </div>

              <!-- Temp / Fan / Power -->
              <div class="grid grid-cols-3 gap-2 border-t border-gray-200 dark:border-gray-700 text-center">
                <div>
                  <p class="text-xs text-muted">Temp</p>
                  <p
                    class="text-sm font-semibold"
                    :class="getTempColor(gpu.temperature)">
                    {{ gpu.temperature >= 0 ? `${gpu.temperature}°C` : '-' }}
                  </p>
                </div>
                <div>
                  <p class="text-xs text-muted">Fan</p>
                  <p class="text-sm font-semibold">
                    {{ gpu.fan_speed >= 0 ? `${gpu.fan_speed}%` : '-' }}
                  </p>
                </div>
                <div>
                  <p class="text-xs text-muted">Power</p>
                  <p class="text-sm font-semibold">{{ formatPower(gpu.power_usage_mw) }}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- Table View -->
    <div
      v-else
      class="table-container">
      <table class="table">
        <thead class="table-header">
          <tr>
            <th class="table-cell">Node</th>
            <th class="table-cell">GPU</th>
            <th class="table-cell">Name</th>
            <th class="table-cell">GPU %</th>
            <th class="table-cell">Memory</th>
            <th class="table-cell">Temp</th>
            <th class="table-cell">Fan</th>
            <th class="table-cell">Power</th>
            <th class="table-cell">Clocks</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="gpu in allGpus"
            :key="`${gpu.hostname}-${gpu.gpu_id}`"
            class="table-row">
            <td class="table-cell text-muted">{{ gpu.hostname }}</td>
            <td class="table-cell font-medium">{{ gpu.gpu_id }}</td>
            <td class="table-cell">{{ gpu.name || '-' }}</td>
            <td class="table-cell">
              <div class="flex items-center gap-2">
                <div class="w-12">
                  <ResourceBar
                    :value="gpu.gpu_utilization >= 0 ? gpu.gpu_utilization : 0"
                    :max="100"
                    size="sm"
                    color="auto"
                    :show-percent="false" />
                </div>
                <span
                  class="text-sm"
                  :class="getUtilizationColor(gpu.gpu_utilization)">
                  {{ gpu.gpu_utilization >= 0 ? formatPercent(gpu.gpu_utilization) : '-' }}
                </span>
              </div>
            </td>
            <td class="table-cell">
              <div class="flex items-center gap-2">
                <div class="w-12">
                  <ResourceBar
                    :value="gpu.memory_used_mib || 0"
                    :max="gpu.memory_total_mib || 1"
                    size="sm"
                    color="auto"
                    :show-percent="false" />
                </div>
                <span class="text-sm">
                  {{ formatMiB(gpu.memory_used_mib || 0) }}
                </span>
              </div>
            </td>
            <td class="table-cell">
              <span :class="getTempColor(gpu.temperature)">
                {{ gpu.temperature >= 0 ? `${gpu.temperature}°C` : '-' }}
              </span>
            </td>
            <td class="table-cell">
              {{ gpu.fan_speed >= 0 ? `${gpu.fan_speed}%` : '-' }}
            </td>
            <td class="table-cell">{{ formatPower(gpu.power_usage_mw) }} / {{ formatPower(gpu.power_limit_mw) }}</td>
            <td class="table-cell text-sm text-muted">
              <div>GPU: {{ formatClock(gpu.graphics_clock_mhz) }}</div>
              <div>Mem: {{ formatClock(gpu.mem_clock_mhz) }}</div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.marquee-text {
  display: inline-block;
  white-space: nowrap;
}
.marquee-text:hover {
  animation: marquee 4s linear infinite;
}
@keyframes marquee {
  0% {
    transform: translateX(0);
  }
  100% {
    transform: translateX(-100%);
  }
}
</style>
