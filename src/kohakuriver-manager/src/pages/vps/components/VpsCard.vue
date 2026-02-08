<script setup>
/**
 * VPS Card Component
 *
 * Displays a single VPS instance as a card with status, info, and action buttons.
 */

import { formatBytes, formatRelativeTime } from '@/utils/format'

const props = defineProps({
  vps: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits([
  'open-ide',
  'show-ssh-info',
  'show-port-forward',
  'copy-ssh',
  'copy-terminal',
  'copy-id',
  'stop',
  'restart',
  'pause',
  'resume',
])

function getNodeHostname(node) {
  if (!node) return '-'
  return typeof node === 'object' ? node.hostname : node
}
</script>

<template>
  <div class="card flex flex-col">
    <!-- Header with name and ID -->
    <div class="flex items-start justify-between gap-2 mb-4">
      <div class="flex items-center gap-2 min-w-0 flex-1">
        <span class="i-carbon-virtual-machine text-2xl text-blue-500 flex-shrink-0"></span>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <h3
              class="font-semibold truncate"
              :title="vps.name || vps.task_id">
              {{ vps.name || `VPS #${vps.task_id.substring(0, 8)}` }}
            </h3>
            <el-tooltip
              content="Copy VPS ID"
              placement="top">
              <button
                @click="emit('copy-id', vps.task_id)"
                class="text-gray-400 hover:text-blue-500 transition-colors flex-shrink-0">
                <span class="i-carbon-copy text-sm"></span>
              </button>
            </el-tooltip>
          </div>
          <p class="text-xs text-muted font-mono truncate">{{ vps.task_id }}</p>
        </div>
      </div>
      <StatusBadge
        :status="vps.status"
        class="flex-shrink-0" />
    </div>

    <!-- Info -->
    <div class="space-y-2 text-sm flex-1">
      <div class="flex justify-between">
        <span class="text-muted">Backend</span>
        <el-tag
          :type="vps.vps_backend === 'qemu' ? 'warning' : 'info'"
          size="small">
          {{ vps.vps_backend === 'qemu' ? 'VM (QEMU)' : 'Docker' }}
        </el-tag>
      </div>
      <div class="flex justify-between">
        <span class="text-muted">Node</span>
        <span>{{ getNodeHostname(vps.assigned_node) }}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-muted">CPU Cores</span>
        <span>{{ vps.required_cores }}</span>
      </div>
      <div
        v-if="vps.vps_backend === 'qemu' && vps.vm_ip"
        class="flex justify-between">
        <span class="text-muted">VM IP</span>
        <span class="font-mono">{{ vps.vm_ip }}</span>
      </div>
      <div
        v-if="vps.vps_backend === 'qemu' && vps.vm_image"
        class="flex justify-between">
        <span class="text-muted">VM Image</span>
        <span>{{ vps.vm_image }}</span>
      </div>
      <div
        v-if="vps.required_memory_bytes"
        class="flex justify-between">
        <span class="text-muted">Memory</span>
        <span>{{ formatBytes(vps.required_memory_bytes) }}</span>
      </div>
      <div
        v-if="vps.ssh_port"
        class="flex justify-between">
        <span class="text-muted">SSH Port</span>
        <span class="font-mono">{{ vps.ssh_port }}</span>
      </div>
      <div
        v-if="vps.container_name"
        class="flex justify-between gap-2">
        <span class="text-muted flex-shrink-0">Container</span>
        <span
          class="truncate"
          :title="vps.container_name">
          {{ vps.container_name }}
        </span>
      </div>
      <div
        v-if="vps.owner_username"
        class="flex justify-between">
        <span class="text-muted">Creator</span>
        <span>{{ vps.owner_username }}</span>
      </div>
      <div
        v-if="vps.assignees && vps.assignees.length > 0"
        class="flex justify-between gap-2">
        <span class="text-muted flex-shrink-0">Assignees</span>
        <span
          class="truncate text-right"
          :title="vps.assignees.map((a) => a.username).join(', ')">
          {{ vps.assignees.map((a) => a.username).join(', ') }}
        </span>
      </div>
      <div class="flex justify-between">
        <span class="text-muted">Created</span>
        <span>{{ formatRelativeTime(vps.submitted_at) }}</span>
      </div>
    </div>

    <!-- Actions - Aligned grid layout -->
    <div class="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
      <!-- Running state buttons -->
      <div
        v-if="vps.status === 'running'"
        class="flex flex-col gap-2">
        <!-- Primary actions row -->
        <div class="flex gap-2">
          <el-tooltip
            content="Open IDE (Terminal + Files)"
            placement="top">
            <el-button
              size="small"
              type="primary"
              @click="emit('open-ide', vps.task_id)"
              class="flex-1">
              <span class="i-carbon-terminal mr-1"></span>
              IDE
            </el-button>
          </el-tooltip>
          <el-tooltip
            v-if="vps.ssh_port"
            content="SSH Connection Info"
            placement="top">
            <el-button
              size="small"
              type="info"
              @click="emit('show-ssh-info', vps)"
              class="flex-1">
              <span class="i-carbon-connect mr-1"></span>
              SSH Info
            </el-button>
          </el-tooltip>
          <el-tooltip
            v-else
            content="Copy Terminal Command"
            placement="top">
            <el-button
              size="small"
              type="info"
              @click="emit('copy-terminal', vps)"
              class="flex-1">
              <span class="i-carbon-copy mr-1"></span>
              Copy CMD
            </el-button>
          </el-tooltip>
        </div>

        <!-- Copy commands row (only when SSH is enabled) -->
        <div
          v-if="vps.ssh_port"
          class="flex gap-2">
          <el-tooltip
            content="Copy SSH Command"
            placement="top">
            <el-button
              size="small"
              type="info"
              @click="emit('copy-ssh', vps)"
              class="flex-1">
              <span class="i-carbon-terminal mr-1"></span>
              SSH
            </el-button>
          </el-tooltip>
          <el-tooltip
            content="Copy Terminal Command"
            placement="top">
            <el-button
              size="small"
              type="info"
              @click="emit('copy-terminal', vps)"
              class="flex-1">
              <span class="i-carbon-copy mr-1"></span>
              Terminal
            </el-button>
          </el-tooltip>
        </div>

        <!-- Port forwarding row -->
        <div class="flex gap-2">
          <el-tooltip
            content="Forward container ports to local machine"
            placement="top">
            <el-button
              size="small"
              type="success"
              @click="emit('show-port-forward', vps)"
              class="flex-1">
              <span class="i-carbon-arrows-horizontal mr-1"></span>
              Port Forward
            </el-button>
          </el-tooltip>
        </div>

        <!-- Control buttons row -->
        <div class="flex gap-2">
          <el-tooltip
            content="Pause"
            placement="top">
            <el-button
              size="small"
              type="info"
              @click="emit('pause', vps.task_id)"
              class="flex-1">
              <span class="i-carbon-pause"></span>
            </el-button>
          </el-tooltip>
          <el-tooltip
            content="Restart"
            placement="top">
            <el-button
              size="small"
              type="warning"
              @click="emit('restart', vps.task_id)"
              class="flex-1">
              <span class="i-carbon-restart"></span>
            </el-button>
          </el-tooltip>
          <el-tooltip
            content="Stop"
            placement="top">
            <el-button
              size="small"
              type="danger"
              @click="emit('stop', vps.task_id)"
              class="flex-1">
              <span class="i-carbon-stop"></span>
            </el-button>
          </el-tooltip>
        </div>
      </div>

      <!-- Paused state buttons -->
      <div
        v-else-if="vps.status === 'paused'"
        class="grid grid-cols-2 gap-2">
        <el-tooltip
          content="Resume VPS"
          placement="top">
          <el-button
            size="small"
            type="success"
            @click="emit('resume', vps.task_id)"
            class="w-full">
            <span class="i-carbon-play mr-1"></span>
            Resume
          </el-button>
        </el-tooltip>
        <el-tooltip
          content="Stop VPS"
          placement="top">
          <el-button
            size="small"
            type="danger"
            @click="emit('stop', vps.task_id)"
            class="w-full">
            <span class="i-carbon-stop mr-1"></span>
            Stop
          </el-button>
        </el-tooltip>
      </div>

      <!-- Assigning state (provisioning) -->
      <div
        v-else-if="vps.status === 'assigning'"
        class="text-center text-sm py-2">
        <div class="text-blue-500 dark:text-blue-400 animate-pulse">
          {{ vps.error_message || 'Provisioning VM...' }}
        </div>
      </div>

      <!-- Pending/Other states -->
      <div
        v-else-if="vps.status === 'pending'"
        class="text-center text-muted text-sm py-2">
        Waiting for assignment...
      </div>
    </div>
  </div>
</template>
