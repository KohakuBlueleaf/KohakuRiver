<script setup>
/**
 * VPS Management Page
 *
 * Provides interface for creating, managing, and connecting to VPS instances.
 * Features include:
 * - VPS creation with SSH key modes and GPU selection
 * - Real-time status monitoring via polling
 * - IDE integration for terminal and file access
 * - SSH connection info and command copying
 */

import { useClusterStore } from '@/stores/cluster'
import { useDockerStore } from '@/stores/docker'
import { useVpsStore } from '@/stores/vps'

import { useNotification } from '@/composables/useNotification'
import { usePolling } from '@/composables/usePolling'

import VpsCard from './components/VpsCard.vue'
import VpsCreateDialog from './components/VpsCreateDialog.vue'

const vpsStore = useVpsStore()
const clusterStore = useClusterStore()
const dockerStore = useDockerStore()
const notify = useNotification()

// Filter
const showAll = ref(false)

// IDE Modal state
const ideModalVisible = ref(false)
const ideTaskId = ref(null)

// Dialogs
const createDialogVisible = ref(false)
const sshInfoDialogVisible = ref(false)
const portForwardDialogVisible = ref(false)
const selectedVps = ref(null)

// Generated key result
const generatedKeyResult = ref(null)

// Polling
const { start: startPolling } = usePolling(() => {
  vpsStore.fetchVpsList(!showAll.value)
}, 5000)

onMounted(async () => {
  await Promise.all([clusterStore.fetchNodes(), dockerStore.fetchTarballs()])
  startPolling()
})

watch(showAll, () => {
  vpsStore.fetchVpsList(!showAll.value)
})

// VPS action handlers
async function handleStop(taskId) {
  try {
    await vpsStore.stopVps(taskId)
    notify.success('VPS stop requested')
  } catch (e) {
    notify.error('Failed to stop VPS')
  }
}

async function handleRestart(taskId) {
  try {
    await vpsStore.restartVps(taskId)
    notify.success('VPS restart requested')
  } catch (e) {
    notify.error('Failed to restart VPS')
  }
}

async function handlePause(taskId) {
  try {
    await vpsStore.pauseVps(taskId)
    notify.success('VPS paused')
  } catch (e) {
    notify.error('Failed to pause VPS')
  }
}

async function handleResume(taskId) {
  try {
    await vpsStore.resumeVps(taskId)
    notify.success('VPS resumed')
  } catch (e) {
    notify.error('Failed to resume VPS')
  }
}

function openIde(taskId) {
  ideTaskId.value = taskId
  ideModalVisible.value = true
}

function closeIde() {
  console.log('VPS page: closeIde called')
  ideModalVisible.value = false
  ideTaskId.value = null
}

function showSshInfo(vps) {
  selectedVps.value = vps
  sshInfoDialogVisible.value = true
}

function showPortForward(vps) {
  selectedVps.value = vps
  portForwardDialogVisible.value = true
}

async function copyToClipboard(text, successMsg) {
  try {
    await navigator.clipboard.writeText(text)
    notify.success(successMsg)
  } catch (err) {
    // Fallback for non-secure contexts
    const textarea = document.createElement('textarea')
    textarea.value = text
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    notify.success(successMsg)
  }
}

function copySshCommand(vps) {
  const cmd = `kohakuriver ssh connect ${vps.task_id}`
  copyToClipboard(cmd, 'SSH command copied')
}

function copyTerminalCommand(vps) {
  const cmd = `kohakuriver connect ${vps.task_id}`
  copyToClipboard(cmd, 'Terminal command copied')
}

function copyVpsId(taskId) {
  copyToClipboard(taskId, 'VPS ID copied')
}

function handleVpsCreated(result) {
  // If key was generated, show it
  if (result.ssh_private_key) {
    generatedKeyResult.value = result
  }
}

function downloadPrivateKey() {
  if (!generatedKeyResult.value?.ssh_private_key) return

  const blob = new Blob([generatedKeyResult.value.ssh_private_key], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `vps-${generatedKeyResult.value.task_id}-key`
  a.click()
  URL.revokeObjectURL(url)
}

function getNodeHostname(node) {
  if (!node) return '-'
  return typeof node === 'object' ? node.hostname : node
}
</script>

<template>
  <div class="vps-page">
    <!-- Main Content -->
    <div class="vps-content space-y-6">
      <!-- Header -->
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 class="page-title mb-0">VPS Instances</h2>
          <p class="text-muted">{{ vpsStore.runningVps.length }} running, {{ vpsStore.activeVps.length }} active</p>
        </div>
        <div class="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
          <el-switch
            v-model="showAll"
            active-text="Show all"
            inactive-text="Active only" />
          <el-button
            type="primary"
            @click="createDialogVisible = true"
            class="w-full sm:w-auto">
            <span class="i-carbon-add mr-2"></span>
            Create VPS
          </el-button>
        </div>
      </div>

      <!-- VPS Cards -->
      <div
        v-if="vpsStore.loading && vpsStore.vpsList.length === 0"
        class="text-center py-12">
        <el-icon class="is-loading text-4xl text-blue-500"><i class="i-carbon-renew"></i></el-icon>
      </div>

      <EmptyState
        v-else-if="vpsStore.vpsList.length === 0"
        icon="i-carbon-virtual-machine"
        title="No VPS instances"
        description="Create a new VPS to get started.">
        <template #action>
          <el-button
            type="primary"
            @click="createDialogVisible = true">
            Create VPS
          </el-button>
        </template>
      </EmptyState>

      <div
        v-else
        class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        <VpsCard
          v-for="vps in vpsStore.vpsList"
          :key="vps.task_id"
          :vps="vps"
          @open-ide="openIde"
          @show-ssh-info="showSshInfo"
          @show-port-forward="showPortForward"
          @copy-ssh="copySshCommand"
          @copy-terminal="copyTerminalCommand"
          @copy-id="copyVpsId"
          @stop="handleStop"
          @restart="handleRestart"
          @pause="handlePause"
          @resume="handleResume" />
      </div>
    </div>

    <!-- IDE Modal -->
    <IdeOverlay
      :visible="ideModalVisible"
      @close="closeIde">
      <IdeContent
        v-if="ideTaskId"
        :task-id="ideTaskId"
        type="task"
        @close="closeIde" />
    </IdeOverlay>

    <!-- Create Dialog -->
    <VpsCreateDialog
      v-model:visible="createDialogVisible"
      @created="handleVpsCreated" />

    <!-- SSH Info Dialog -->
    <el-dialog
      v-model="sshInfoDialogVisible"
      title="Connection Info"
      width="500px">
      <div
        v-if="selectedVps"
        class="space-y-4">
        <div class="p-4 bg-app-surface rounded-lg">
          <p class="text-sm text-muted mb-2">SSH Command (via proxy):</p>
          <code class="text-sm font-mono break-all">kohakuriver ssh connect {{ selectedVps.task_id }}</code>
        </div>
        <div class="p-4 bg-app-surface rounded-lg">
          <p class="text-sm text-muted mb-2">Terminal Command:</p>
          <code class="text-sm font-mono break-all">kohakuriver connect {{ selectedVps.task_id }}</code>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          <div>
            <span class="text-muted">Task ID:</span>
            <span class="ml-2 font-mono">{{ selectedVps.task_id }}</span>
          </div>
          <div>
            <span class="text-muted">Node:</span>
            <span class="ml-2 break-all">{{ getNodeHostname(selectedVps.assigned_node) }}</span>
          </div>
        </div>
      </div>
      <template #footer>
        <div class="flex flex-col sm:flex-row gap-2 sm:justify-end">
          <el-button
            @click="copySshCommand(selectedVps)"
            class="w-full sm:w-auto">
            <span class="i-carbon-terminal mr-1"></span>
            Copy SSH
          </el-button>
          <el-button
            @click="copyTerminalCommand(selectedVps)"
            class="w-full sm:w-auto">
            <span class="i-carbon-copy mr-1"></span>
            Copy Terminal
          </el-button>
          <el-button
            type="primary"
            @click="sshInfoDialogVisible = false"
            class="w-full sm:w-auto">
            Close
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- Generated Key Dialog -->
    <el-dialog
      v-model="generatedKeyResult"
      title="SSH Key Generated"
      width="600px"
      :close-on-click-modal="false">
      <div class="space-y-4">
        <el-alert
          type="warning"
          :closable="false">
          Save this private key now. It will not be shown again.
        </el-alert>

        <div>
          <p class="text-sm font-medium mb-2">Private Key:</p>
          <div
            class="p-3 bg-gray-900 text-gray-100 rounded-lg font-mono text-xs max-h-48 overflow-auto whitespace-pre break-all">
            {{ generatedKeyResult?.ssh_private_key }}
          </div>
        </div>

        <div v-if="generatedKeyResult?.ssh_public_key">
          <p class="text-sm font-medium mb-2">Public Key:</p>
          <div class="p-3 bg-app-surface rounded-lg font-mono text-xs overflow-auto break-all">
            {{ generatedKeyResult?.ssh_public_key }}
          </div>
        </div>
      </div>

      <template #footer>
        <div class="flex flex-col sm:flex-row gap-2 sm:justify-end">
          <el-button
            @click="downloadPrivateKey"
            class="w-full sm:w-auto">
            <span class="i-carbon-download mr-1"></span>
            Download Key
          </el-button>
          <el-button
            type="primary"
            @click="generatedKeyResult = null"
            class="w-full sm:w-auto">
            Done
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- Port Forward Dialog -->
    <PortForwardDialog
      v-if="selectedVps"
      v-model:visible="portForwardDialogVisible"
      :task-id="selectedVps.task_id"
      :status="selectedVps.status" />
  </div>
</template>

<style scoped>
/* =============================================================================
 * VPS Page Layout
 * ============================================================================= */

.vps-page {
  height: 100%;
  overflow: auto;
}

.vps-content {
  padding: 0;
}
</style>
