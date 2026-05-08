<script setup>
/**
 * Docker Management Page
 *
 * Provides interface for managing Docker containers and tarballs.
 * Features:
 * - Create/start/stop/delete containers
 * - IDE integration for container access
 * - Tarball creation and management for environment distribution
 */

import { useDockerStore } from '@/stores/docker'

import { useNotification } from '@/composables/useNotification'
import { usePolling } from '@/composables/usePolling'

import { formatBytes, formatRelativeTime } from '@/utils/format'

import IdeContent from '@/components/ide/IdeContent.vue'
import IdeOverlay from '@/components/ide/IdeOverlay.vue'

const dockerStore = useDockerStore()
const notify = useNotification()

// Tabs
const activeTab = ref('containers')

// Dialogs
const createContainerDialogVisible = ref(false)
const selectedContainer = ref(null)
const createTarballDialogVisible = ref(false)
const selectedTarballContainer = ref(null)

// IDE Modal state
const ideModalVisible = ref(false)

// Create container form
const createContainerForm = ref({
  container_name: '',
  image_name: '',
})

// Polling
const { start: startPolling } = usePolling(() => {
  dockerStore.fetchContainers()
  dockerStore.fetchTarballs()
}, 10000)

onMounted(() => {
  startPolling()
})

async function handleCreateContainer() {
  if (!createContainerForm.value.container_name || !createContainerForm.value.image_name) {
    notify.warning('Please fill in all fields')
    return
  }

  try {
    await dockerStore.createContainer(createContainerForm.value)
    notify.success('Container created successfully')
    createContainerDialogVisible.value = false
    createContainerForm.value = { container_name: '', image_name: '' }
  } catch (e) {
    notify.error(e.response?.data?.detail || 'Failed to create container')
  }
}

async function handleStartContainer(name) {
  try {
    await dockerStore.startContainer(name)
    notify.success('Container started')
  } catch (e) {
    console.error('Failed to start container', e)
    notify.error('Failed to start container')
  }
}

async function handleStopContainer(name) {
  try {
    await dockerStore.stopContainer(name)
    notify.success('Container stopped')
  } catch (e) {
    console.error('Failed to stop container', e)
    notify.error('Failed to stop container')
  }
}

async function handleDeleteContainer(name) {
  try {
    await dockerStore.deleteContainer(name)
    notify.success('Container deleted')
  } catch (e) {
    console.error('Failed to delete container', e)
    notify.error('Failed to delete container')
  }
}

function openIde(containerName) {
  selectedContainer.value = containerName
  ideModalVisible.value = true
}

function closeIde() {
  ideModalVisible.value = false
  selectedContainer.value = null
}

function openCreateTarball(containerName) {
  selectedTarballContainer.value = containerName
  createTarballDialogVisible.value = true
}

async function handleCreateTarball() {
  if (!selectedTarballContainer.value) return

  try {
    await dockerStore.createTarball(selectedTarballContainer.value)
    notify.success('Tarball created successfully')
    createTarballDialogVisible.value = false
  } catch (e) {
    notify.error(e.response?.data?.detail || 'Failed to create tarball')
  }
}

async function handleDeleteTarball(name) {
  try {
    await dockerStore.deleteTarball(name)
    notify.success('Tarball deleted')
  } catch (e) {
    console.error('Failed to delete tarball', e)
    notify.error('Failed to delete tarball')
  }
}

function getContainerStatus(container) {
  return container.status === 'running' ? 'running' : 'stopped'
}

// Parse container name to remove kohakuriver-env prefix
function parseContainerName(name) {
  if (!name) return { displayName: '-', fullName: name }
  const prefix = 'kohakuriver-env-'
  if (name.startsWith(prefix)) {
    return {
      displayName: name.slice(prefix.length),
      fullName: name,
      hasPrefix: true,
    }
  }
  return { displayName: name, fullName: name, hasPrefix: false }
}

// Parse image/tag to handle long tags
function parseImageTag(image) {
  if (!image) return { name: '-', tag: null }
  const parts = image.split(':')
  if (parts.length === 2) {
    return { name: parts[0], tag: parts[1] }
  }
  return { name: image, tag: null }
}

// Expandable tags state
const expandedTags = ref(new Set())
</script>

<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <h2 class="page-title mb-0">Docker Management</h2>
        <p class="text-muted">Manage environment containers and tarballs</p>
      </div>
    </div>

    <!-- Tabs -->
    <el-tabs v-model="activeTab">
      <!-- Containers Tab -->
      <el-tab-pane
        label="Containers"
        name="containers">
        <div class="space-y-4">
          <!-- Actions -->
          <div class="flex justify-end">
            <el-button
              type="primary"
              @click="createContainerDialogVisible = true">
              <span class="i-carbon-add mr-1"></span>
              Create Container
            </el-button>
          </div>

          <!-- Container List -->
          <div
            v-if="dockerStore.loading && dockerStore.containers.length === 0"
            class="text-center py-12">
            <el-icon class="is-loading text-4xl text-blue-500"><i class="i-carbon-renew"></i></el-icon>
          </div>

          <EmptyState
            v-else-if="dockerStore.containers.length === 0"
            icon="i-carbon-container-software"
            title="No containers"
            description="Create an environment container to get started.">
            <template #action>
              <el-button
                type="primary"
                @click="createContainerDialogVisible = true">
                Create Container
              </el-button>
            </template>
          </EmptyState>

          <div
            v-else
            class="grid-cards">
            <div
              v-for="container in dockerStore.containers"
              :key="container.name"
              class="card">
              <!-- Header -->
              <div class="flex items-start gap-3 mb-4">
                <span class="i-carbon-container-software text-2xl text-purple-500 flex-shrink-0 mt-0.5"></span>
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-2 flex-wrap">
                    <h3
                      class="font-semibold"
                      :title="parseContainerName(container.name).fullName">
                      {{ parseContainerName(container.name).displayName }}
                    </h3>
                    <el-tag
                      v-if="parseContainerName(container.name).hasPrefix"
                      size="small"
                      type="info">
                      env
                    </el-tag>
                  </div>
                  <StatusBadge
                    :status="getContainerStatus(container)"
                    class="mt-1" />
                  <!-- Image with expandable tag -->
                  <div class="text-xs text-muted flex items-center gap-1 min-w-0 mt-2">
                    <span class="truncate">{{ parseImageTag(container.image).name }}</span>
                    <template v-if="parseImageTag(container.image).tag">
                      <span>:</span>
                      <span
                        v-if="parseImageTag(container.image).tag.length > 20 && !expandedTags.has(container.name)"
                        class="truncate max-w-20 cursor-pointer hover:text-blue-500"
                        :title="parseImageTag(container.image).tag"
                        @click="expandedTags.add(container.name)">
                        {{ parseImageTag(container.image).tag.slice(0, 20) }}...
                      </span>
                      <span
                        v-else-if="parseImageTag(container.image).tag.length > 20"
                        class="cursor-pointer hover:text-blue-500 break-all"
                        @click="expandedTags.delete(container.name)">
                        {{ parseImageTag(container.image).tag }}
                      </span>
                      <span v-else>{{ parseImageTag(container.image).tag }}</span>
                    </template>
                  </div>
                </div>
              </div>

              <!-- Info -->
              <div class="space-y-2 text-sm">
                <div
                  v-if="container.created"
                  class="flex justify-between">
                  <span class="text-muted">Created</span>
                  <span>{{ formatRelativeTime(container.created) }}</span>
                </div>
                <div
                  v-if="container.state"
                  class="flex justify-between">
                  <span class="text-muted">State</span>
                  <span>{{ container.state }}</span>
                </div>
              </div>

              <!-- Actions -->
              <div class="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700 flex flex-wrap gap-2">
                <!-- IDE (only for running containers) -->
                <el-tooltip
                  v-if="container.status === 'running'"
                  content="Open IDE">
                  <el-button
                    size="small"
                    type="primary"
                    @click="openIde(container.name)">
                    <span class="i-carbon-code mr-1"></span>
                    IDE
                  </el-button>
                </el-tooltip>

                <!-- Start/Stop -->
                <el-tooltip
                  v-if="container.status !== 'running'"
                  content="Start">
                  <el-button
                    size="small"
                    type="success"
                    @click="handleStartContainer(container.name)">
                    <span class="i-carbon-play"></span>
                  </el-button>
                </el-tooltip>
                <el-tooltip
                  v-else
                  content="Stop">
                  <el-button
                    size="small"
                    type="warning"
                    @click="handleStopContainer(container.name)">
                    <span class="i-carbon-stop"></span>
                  </el-button>
                </el-tooltip>

                <!-- Create Tarball -->
                <el-tooltip content="Create Tarball">
                  <el-button
                    size="small"
                    type="info"
                    @click="openCreateTarball(container.name)">
                    <span class="i-carbon-archive"></span>
                  </el-button>
                </el-tooltip>

                <!-- Delete -->
                <el-popconfirm
                  title="Are you sure to delete this container?"
                  @confirm="handleDeleteContainer(container.name)">
                  <template #reference>
                    <el-button
                      size="small"
                      type="danger">
                      <span class="i-carbon-trash-can"></span>
                    </el-button>
                  </template>
                </el-popconfirm>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- Tarballs Tab -->
      <el-tab-pane
        label="Tarballs"
        name="tarballs">
        <div class="space-y-4">
          <!-- Tarball List -->
          <EmptyState
            v-if="dockerStore.tarballs.length === 0"
            icon="i-carbon-archive"
            title="No tarballs"
            description="Create a tarball from a container to distribute environments." />

          <div
            v-else
            class="table-container">
            <table class="table">
              <thead class="table-header">
                <tr>
                  <th class="table-cell">Name</th>
                  <th class="table-cell">Version</th>
                  <th class="table-cell">Size</th>
                  <th class="table-cell">Created</th>
                  <th class="table-cell">Actions</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="tarball in dockerStore.tarballs"
                  :key="tarball.name"
                  class="table-row">
                  <td class="table-cell font-medium">{{ tarball.name }}</td>
                  <td class="table-cell">
                    <span
                      v-if="tarball.versions?.length"
                      class="text-muted">
                      {{ tarball.versions.length }} version(s)
                    </span>
                    <span
                      v-else
                      class="text-muted">
                      -
                    </span>
                  </td>
                  <td class="table-cell">
                    <span v-if="tarball.size">{{ formatBytes(tarball.size) }}</span>
                    <span
                      v-else
                      class="text-muted">
                      -
                    </span>
                  </td>
                  <td class="table-cell text-muted">
                    {{ tarball.created ? formatRelativeTime(tarball.created) : '-' }}
                  </td>
                  <td class="table-cell">
                    <el-popconfirm
                      title="Delete this tarball?"
                      @confirm="handleDeleteTarball(tarball.name)">
                      <template #reference>
                        <el-button
                          size="small"
                          type="danger">
                          <span class="i-carbon-trash-can"></span>
                        </el-button>
                      </template>
                    </el-popconfirm>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- Create Container Dialog -->
    <el-dialog
      v-model="createContainerDialogVisible"
      title="Create Container"
      width="500px">
      <el-form
        :model="createContainerForm"
        label-position="top">
        <el-form-item
          label="Environment Name"
          required>
          <el-input
            v-model="createContainerForm.container_name"
            placeholder="e.g., pytorch-env" />
        </el-form-item>

        <el-form-item
          label="Base Image"
          required>
          <el-input
            v-model="createContainerForm.image_name"
            placeholder="e.g., ubuntu:22.04" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="createContainerDialogVisible = false">Cancel</el-button>
        <el-button
          type="primary"
          @click="handleCreateContainer">
          Create
        </el-button>
      </template>
    </el-dialog>

    <!-- IDE Modal -->
    <IdeOverlay
      :visible="ideModalVisible"
      @close="closeIde">
      <IdeContent
        v-if="selectedContainer"
        :task-id="selectedContainer"
        :container-name="selectedContainer"
        type="container"
        file-tree-mode="container"
        :title="`Container: ${parseContainerName(selectedContainer).displayName}`"
        @close="closeIde" />
    </IdeOverlay>

    <!-- Create Tarball Dialog -->
    <el-dialog
      v-model="createTarballDialogVisible"
      title="Create Tarball"
      width="400px">
      <p>
        Create a tarball from container
        <strong>{{ selectedTarballContainer }}</strong>
        ?
      </p>
      <p class="text-muted text-sm mt-2">
        This will save the container state as a distributable tarball that can be used by runner nodes.
      </p>

      <template #footer>
        <el-button @click="createTarballDialogVisible = false">Cancel</el-button>
        <el-button
          type="primary"
          @click="handleCreateTarball">
          Create Tarball
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* Docker page has no additional custom styles - using shared components */
</style>
