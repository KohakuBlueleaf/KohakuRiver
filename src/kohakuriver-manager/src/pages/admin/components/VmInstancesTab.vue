<script setup>
/**
 * VM Instances Tab
 *
 * Displays VM instances across nodes with summary stats, disk usage, and delete actions.
 */

import { ElMessage, ElMessageBox } from 'element-plus'
import { vpsAPI } from '@/utils/api/vps'

// VM Instances state
const vmInstancesData = ref(null)
const vmInstancesLoading = ref(false)
const vmInstancesLoaded = ref(false)

// Fetch VM instances
async function fetchVmInstances() {
  vmInstancesLoading.value = true
  try {
    const response = await vpsAPI.listVmInstances()
    vmInstancesData.value = response.data
    vmInstancesLoaded.value = true
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || 'Failed to fetch VM instances')
    console.error(err)
  } finally {
    vmInstancesLoading.value = false
  }
}

// Delete VM instance
async function deleteVmInstance(instance, hostname) {
  const diskMB = (instance.disk_usage_bytes / (1024 * 1024)).toFixed(1)
  try {
    await ElMessageBox.confirm(
      `Delete VM instance ${instance.task_id} on ${hostname}?\n` +
        `This will free ${diskMB} MB of disk space.\n` +
        (instance.qemu_running ? 'QEMU is still running and will be force-stopped.' : ''),
      'Delete VM Instance',
      {
        confirmButtonText: 'Delete',
        cancelButtonText: 'Cancel',
        type: 'warning',
      }
    )
    await vpsAPI.deleteVmInstance(instance.task_id, hostname, instance.qemu_running)
    ElMessage.success(`VM instance ${instance.task_id} deleted`)
    fetchVmInstances()
  } catch (err) {
    if (err !== 'cancel') {
      ElMessage.error(err.response?.data?.detail || 'Failed to delete VM instance')
    }
  }
}

// Flatten VM instances for table display
const vmInstancesFlat = computed(() => {
  if (!vmInstancesData.value?.nodes) return []
  const rows = []
  for (const node of vmInstancesData.value.nodes) {
    if (!node.instances) continue
    for (const inst of node.instances) {
      rows.push({ ...inst, hostname: node.hostname })
    }
  }
  return rows
})

// Format bytes to human readable
function formatBytes(bytes) {
  if (bytes == null) return '-'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB'
}

// DB status tag type
function dbStatusType(status) {
  if (status === 'orphaned') return 'danger'
  if (status === 'running') return 'success'
  if (status === 'stopped' || status === 'failed' || status === 'killed') return 'info'
  if (status === 'paused') return 'warning'
  return ''
}

// Load data on mount
onMounted(() => {
  fetchVmInstances()
})

defineExpose({ fetchVmInstances })
</script>

<template>
  <div class="space-y-4">
    <!-- Summary bar -->
    <div
      v-if="vmInstancesData?.summary"
      class="flex gap-6 p-4 rounded bg-gray-800/50">
      <div>
        <span class="text-gray-400 text-sm">Total Instances</span>
        <div class="text-xl font-bold">{{ vmInstancesData.summary.total_instances }}</div>
      </div>
      <div>
        <span class="text-gray-400 text-sm">Orphaned</span>
        <div class="text-xl font-bold text-red-400">{{ vmInstancesData.summary.orphaned_count }}</div>
      </div>
      <div>
        <span class="text-gray-400 text-sm">Total Disk Usage</span>
        <div class="text-xl font-bold">{{ formatBytes(vmInstancesData.summary.total_disk_usage_bytes) }}</div>
      </div>
      <div class="ml-auto flex items-center">
        <el-button
          @click="fetchVmInstances"
          :loading="vmInstancesLoading">
          <span class="i-carbon-renew mr-1"></span>
          Refresh
        </el-button>
      </div>
    </div>

    <!-- Instances table -->
    <el-table
      :data="vmInstancesFlat"
      v-loading="vmInstancesLoading"
      stripe
      style="width: 100%">
      <el-table-column
        prop="hostname"
        label="Node"
        width="140" />
      <el-table-column
        label="Task ID"
        width="200">
        <template #default="{ row }">
          <code class="text-xs">{{ row.task_id }}</code>
        </template>
      </el-table-column>
      <el-table-column
        label="Disk Usage"
        width="110">
        <template #default="{ row }">
          {{ formatBytes(row.disk_usage_bytes) }}
        </template>
      </el-table-column>
      <el-table-column
        label="QEMU"
        width="90">
        <template #default="{ row }">
          <el-tag
            :type="row.qemu_running ? 'success' : 'info'"
            size="small">
            {{ row.qemu_running ? 'Running' : 'Stopped' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column
        label="DB Status"
        width="110">
        <template #default="{ row }">
          <el-tag
            :type="dbStatusType(row.db_status)"
            size="small">
            {{ row.db_status || 'unknown' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column
        label="Name / Image"
        min-width="160">
        <template #default="{ row }">
          <template v-if="row.task_metadata">
            <div>{{ row.task_metadata.name || '-' }}</div>
            <div class="text-xs text-gray-400">{{ row.task_metadata.vm_image || '' }}</div>
          </template>
          <span
            v-else
            class="text-gray-500">
            -
          </span>
        </template>
      </el-table-column>
      <el-table-column
        label="Files"
        min-width="140">
        <template #default="{ row }">
          <span class="text-xs text-gray-400">{{ row.files?.join(', ') }}</span>
        </template>
      </el-table-column>
      <el-table-column
        label="Actions"
        width="100"
        fixed="right">
        <template #default="{ row }">
          <el-button
            size="small"
            type="danger"
            @click="deleteVmInstance(row, row.hostname)">
            Delete
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <div
      v-if="vmInstancesFlat.length === 0 && !vmInstancesLoading && vmInstancesLoaded"
      class="text-center py-8 text-muted">
      No VM instances found
    </div>
  </div>
</template>
