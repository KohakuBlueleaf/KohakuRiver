<script setup>
/**
 * FileTree - File browser component for IDE.
 *
 * Features:
 * - Three collapsible sections: /shared, /local_temp, / (root)
 * - Lazy loading of directories
 * - Context menu for file operations
 * - File/folder icons
 * - Expandable/collapsible directories
 */

import { useIdeStore } from '@/stores/ide'
import { useFileSystem } from '@/composables/useFileSystem'
import { useFileWatcher, FileChangeEvent } from '@/composables/useFileWatcher'
import { useFileTreeOps } from './useFileTreeOps'
import FileTreeNode from './FileTreeNode.vue'

const props = defineProps({
  /**
   * Show hidden files (dotfiles)
   */
  showHidden: {
    type: Boolean,
    default: true,
  },
  /**
   * File tree mode: 'vps' shows sections (/shared, /local_temp, /), 'container' shows only root
   */
  mode: {
    type: String,
    default: 'vps',
    validator: (value) => ['vps', 'container'].includes(value),
  },
})

const emit = defineEmits(['file-select', 'file-open', 'refresh'])

const ideStore = useIdeStore()
const fs = useFileSystem()
const fileWatcher = useFileWatcher()

// Section definitions based on mode
const vpsSections = [
  { path: '/shared', name: 'Shared', icon: 'i-carbon-share', defaultExpanded: true },
  { path: '/local_temp', name: 'Local Temp', icon: 'i-carbon-data-backup', defaultExpanded: true },
  { path: '/', name: 'Root', icon: 'i-carbon-folder-parent', defaultExpanded: false },
]

const containerSections = [{ path: '/', name: 'Root', icon: 'i-carbon-folder-parent', defaultExpanded: true }]

// Use computed sections based on mode
const sections = computed(() => (props.mode === 'container' ? containerSections : vpsSections))

// Section state - initialized dynamically based on mode
const sectionEntries = ref({
  '/shared': [],
  '/local_temp': [],
  '/': [],
})
const sectionLoading = ref({
  '/shared': false,
  '/local_temp': false,
  '/': false,
})
const sectionErrors = ref({
  '/shared': null,
  '/local_temp': null,
  '/': null,
})

// Section expanded state - dynamically initialized based on mode
const sectionExpanded = ref({
  '/shared': true,
  '/local_temp': true,
  '/': false,
})

// Initialize expansion state based on mode
function initSectionExpanded() {
  if (props.mode === 'container') {
    sectionExpanded.value = { '/': true }
  } else {
    sectionExpanded.value = {
      '/shared': true,
      '/local_temp': true,
      '/': false,
    }
  }
}

const loading = ref(false)

// Directory cache: path -> entries array
const directoryCache = ref(new Map())

/**
 * Load directory entries.
 */
async function loadDirectory(path) {
  // Check cache first
  if (directoryCache.value.has(path)) {
    return directoryCache.value.get(path)
  }

  ideStore.setLoading(path, true)

  try {
    const entries = await fs.listDirectory(path, props.showHidden)

    // Sort: directories first, then files, alphabetically
    entries.sort((a, b) => {
      if (a.type === 'directory' && b.type !== 'directory') return -1
      if (a.type !== 'directory' && b.type === 'directory') return 1
      return a.name.localeCompare(b.name)
    })

    // Cache the result
    directoryCache.value.set(path, entries)

    return entries
  } catch (e) {
    console.error(`Failed to load directory ${path}:`, e)
    throw e
  } finally {
    ideStore.setLoading(path, false)
  }
}

/**
 * Load a section's root directory.
 */
async function loadSection(sectionPath) {
  sectionLoading.value[sectionPath] = true
  sectionErrors.value[sectionPath] = null

  try {
    const entries = await loadDirectory(sectionPath)
    sectionEntries.value[sectionPath] = entries
  } catch (e) {
    sectionErrors.value[sectionPath] = e.response?.data?.detail || e.message
  } finally {
    sectionLoading.value[sectionPath] = false
  }
}

/**
 * Load all sections.
 */
async function loadAllSections() {
  loading.value = true

  // Load sections in parallel
  await Promise.all(
    sections.value.map(async (section) => {
      // Only load if section is expanded
      if (sectionExpanded.value[section.path]) {
        await loadSection(section.path)
      }
    })
  )

  loading.value = false
}

/**
 * Toggle section expansion.
 */
async function toggleSection(sectionPath) {
  sectionExpanded.value[sectionPath] = !sectionExpanded.value[sectionPath]

  // Load section if expanding and not yet loaded
  if (
    sectionExpanded.value[sectionPath] &&
    sectionEntries.value[sectionPath].length === 0 &&
    !sectionErrors.value[sectionPath]
  ) {
    await loadSection(sectionPath)
  }
}

/**
 * Refresh a specific section.
 */
async function refreshSection(sectionPath) {
  // Clear cache for this section
  directoryCache.value.delete(sectionPath)

  // Reload
  await loadSection(sectionPath)
  emit('refresh', sectionPath)
}

/**
 * Refresh entire tree.
 */
async function refreshAll() {
  directoryCache.value.clear()

  // Reset all section entries
  for (const section of sections.value) {
    sectionEntries.value[section.path] = []
    sectionErrors.value[section.path] = null
  }

  await loadAllSections()
}

/**
 * Handle node click (select).
 */
function handleNodeClick(entry) {
  ideStore.setSelectedPath(entry.path)
  ideStore.setSelectedFileInfo({
    path: entry.path,
    name: entry.name,
    type: entry.type,
    size: entry.size || 0,
  })
  emit('file-select', entry)
}

/**
 * Handle node double-click (open file).
 */
function handleNodeDblClick(entry) {
  if (entry.type === 'file') {
    emit('file-open', entry)
  }
}

/**
 * Ensure a directory's contents are loaded into the cache.
 * Returns true if the directory is ready, false if loading failed.
 */
async function ensureDirectoryLoaded(path) {
  if (directoryCache.value.has(path)) {
    return true
  }

  try {
    await loadDirectory(path)
    return true
  } catch (e) {
    return false
  }
}

/**
 * Handle directory expand/collapse.
 */
async function handleToggleExpand(entry) {
  if (entry.type !== 'directory') return

  if (ideStore.isExpanded(entry.path)) {
    ideStore.setExpanded(entry.path, false)
    return
  }

  // Expanding - load children if not cached
  ideStore.setExpanded(entry.path, true)

  if (!(await ensureDirectoryLoaded(entry.path))) {
    // Collapse back on error
    ideStore.setExpanded(entry.path, false)
  }
}

/**
 * Get children for a directory from cache.
 */
function getChildren(path) {
  return directoryCache.value.get(path) || []
}

// Context menu & file operations (composable)
const {
  contextMenuVisible,
  contextMenuPosition,
  contextMenuTarget,
  newItemDialogVisible,
  newItemType,
  newItemName,
  newItemParentPath,
  renameDialogVisible,
  renameNewName,
  renameOldPath,
  showContextMenu,
  hideContextMenu,
  handleSectionContextMenu,
  handleNodeContextMenu,
  openNewItemDialog,
  createNewItem,
  openRenameDialog,
  renameItem,
  deleteItem,
  copyPath,
  refreshSectionFromMenu,
} = useFileTreeOps(fs, sections, directoryCache, loadSection)

// ============================================
// File Watcher Integration
// ============================================

/**
 * Handle file change event from watcher.
 */
function handleFileChange(change) {
  const { event, path, isDir } = change

  // Get parent directory
  const parentPath = path.substring(0, path.lastIndexOf('/')) || '/'

  // Find which section this path belongs to
  const section = sections.value.find((s) => path === s.path || path.startsWith(s.path + '/') || s.path === '/')

  if (!section) return

  console.log('[FileTree] File change:', event, path, isDir ? '(dir)' : '')

  // Invalidate cache for the parent directory
  directoryCache.value.delete(parentPath)

  // Also invalidate cache for the file/directory itself if it's a directory
  if (isDir) {
    directoryCache.value.delete(path)
  }

  // Reload the parent directory if it's currently visible
  // Check if parent path is in expanded state or is a section root
  const isParentVisible = parentPath === section.path || ideStore.isExpanded(parentPath)

  if (isParentVisible) {
    // Debounce reloads to avoid hammering the server
    debouncedReloadPath(parentPath, section.path)
  }

  // Emit refresh event
  emit('refresh', { event, path, isDir, parentPath })
}

// Debounce reload to batch rapid changes
let reloadTimeout = null
const pendingReloads = new Set()

function debouncedReloadPath(parentPath, sectionPath) {
  pendingReloads.add(parentPath)

  if (reloadTimeout) {
    clearTimeout(reloadTimeout)
  }

  reloadTimeout = setTimeout(async () => {
    const pathsToReload = new Set(pendingReloads)
    pendingReloads.clear()
    reloadTimeout = null

    for (const path of pathsToReload) {
      try {
        // Reload the directory
        directoryCache.value.delete(path)

        if (path === sectionPath) {
          // Reload section root
          await loadSection(sectionPath)
        } else {
          // Reload subdirectory
          await loadDirectory(path)
        }
      } catch (e) {
        console.error('[FileTree] Failed to reload path:', path, e)
      }
    }
  }, 300) // 300ms debounce
}

/**
 * Start file watcher when connected.
 */
function startFileWatcher() {
  if (!ideStore.taskId) return

  // Get paths to watch based on mode
  const watchPaths = props.mode === 'container' ? ['/'] : ['/shared', '/local_temp']

  console.log('[FileTree] Starting file watcher for paths:', watchPaths)

  // Register change handler
  fileWatcher.onChange(handleFileChange)

  // Connect to watcher
  fileWatcher.connect(ideStore.taskId, watchPaths)
}

/**
 * Stop file watcher.
 */
function stopFileWatcher() {
  fileWatcher.disconnect()
}

// Load when connected
onMounted(() => {
  initSectionExpanded()
  if (ideStore.connected && ideStore.taskId) {
    loadAllSections()
    startFileWatcher()
  }
})

// Watch for connection state change
watch(
  () => ideStore.connected,
  (connected) => {
    if (connected && ideStore.taskId) {
      loadAllSections()
      startFileWatcher()
    } else {
      // Disconnected - clear tree and stop watcher
      stopFileWatcher()
      for (const section of sections.value) {
        sectionEntries.value[section.path] = []
        sectionErrors.value[section.path] = null
      }
      directoryCache.value.clear()
    }
  },
  { immediate: false }
)

// Cleanup on unmount
onBeforeUnmount(() => {
  stopFileWatcher()
  if (reloadTimeout) {
    clearTimeout(reloadTimeout)
  }
})

// Expose methods for parent components
defineExpose({
  loadDirectory,
  refreshSection,
  refreshAll,
  getChildren,
  fileWatcher,
})
</script>

<template>
  <div class="file-tree">
    <!-- Header -->
    <div class="file-tree-header">
      <span class="file-tree-title">Files</span>
      <!-- File watcher status indicator -->
      <el-tooltip
        :content="
          fileWatcher.connected.value
            ? `Auto-sync: ${fileWatcher.watchMethod.value || 'active'}`
            : fileWatcher.connecting.value
              ? 'Connecting...'
              : 'Auto-sync offline'
        "
        placement="bottom">
        <span
          class="watcher-indicator"
          :class="{
            connected: fileWatcher.connected.value,
            connecting: fileWatcher.connecting.value,
          }" />
      </el-tooltip>
      <div class="file-tree-actions">
        <el-tooltip
          content="Refresh All"
          placement="bottom">
          <el-button
            link
            size="small"
            :loading="loading"
            @click="refreshAll">
            <span class="i-carbon-rotate" />
          </el-button>
        </el-tooltip>
      </div>
    </div>

    <!-- Waiting for connection -->
    <div
      v-if="!ideStore.connected"
      class="file-tree-loading">
      <el-icon class="is-loading">
        <span class="i-carbon-circle-dash" />
      </el-icon>
      <span>Waiting for connection...</span>
    </div>

    <!-- Sections content -->
    <div
      v-else
      class="file-tree-content">
      <div
        v-for="section in sections"
        :key="section.path"
        class="file-tree-section">
        <!-- Section header -->
        <div
          class="section-header"
          :class="{ expanded: sectionExpanded[section.path] }"
          @click="toggleSection(section.path)"
          @contextmenu="handleSectionContextMenu($event, section.path)">
          <span
            class="section-chevron"
            :class="{ expanded: sectionExpanded[section.path] }">
            <span class="i-carbon-chevron-right" />
          </span>
          <span
            :class="section.icon"
            class="section-icon" />
          <span class="section-name">{{ section.name }}</span>

          <!-- Section actions -->
          <div
            class="section-actions"
            @click.stop>
            <button
              class="section-action-btn"
              title="New File"
              @click="openNewItemDialog('file', section.path)">
              <span class="i-carbon-document-add" />
            </button>
            <button
              class="section-action-btn"
              title="New Folder"
              @click="openNewItemDialog('folder', section.path)">
              <span class="i-carbon-folder-add" />
            </button>
          </div>
        </div>

        <!-- Section content -->
        <div
          v-show="sectionExpanded[section.path]"
          class="section-content">
          <!-- Loading state -->
          <div
            v-if="sectionLoading[section.path] && sectionEntries[section.path].length === 0"
            class="section-loading">
            <el-icon class="is-loading">
              <span class="i-carbon-circle-dash" />
            </el-icon>
            <span>Loading...</span>
          </div>

          <!-- Error state -->
          <div
            v-else-if="sectionErrors[section.path]"
            class="section-error">
            <span class="i-carbon-warning" />
            <span>{{ sectionErrors[section.path] }}</span>
            <el-button
              link
              size="small"
              @click="refreshSection(section.path)">
              Retry
            </el-button>
          </div>

          <!-- Empty state -->
          <div
            v-else-if="sectionEntries[section.path].length === 0"
            class="section-empty">
            <span>Empty directory</span>
          </div>

          <!-- Tree nodes -->
          <div
            v-else
            class="section-tree">
            <FileTreeNode
              v-for="entry in sectionEntries[section.path]"
              :key="entry.path"
              :entry="entry"
              :depth="0"
              :get-children="getChildren"
              :load-directory="loadDirectory"
              @click="handleNodeClick"
              @dblclick="handleNodeDblClick"
              @toggle-expand="handleToggleExpand"
              @contextmenu="handleNodeContextMenu"
              @new-file="(path) => openNewItemDialog('file', path)"
              @new-folder="(path) => openNewItemDialog('folder', path)" />
          </div>
        </div>
      </div>
    </div>

    <!-- Context Menu -->
    <teleport to="body">
      <div
        v-if="contextMenuVisible"
        class="context-menu-overlay"
        @click="hideContextMenu"
        @contextmenu.prevent="hideContextMenu">
        <div
          class="context-menu"
          :style="{ left: contextMenuPosition.x + 'px', top: contextMenuPosition.y + 'px' }"
          @click.stop>
          <!-- For sections and directories -->
          <template v-if="contextMenuTarget?.type === 'section' || contextMenuTarget?.type === 'directory'">
            <div
              class="context-menu-item"
              @click="openNewItemDialog('file', contextMenuTarget.path)">
              <span class="i-carbon-document-add" />
              <span>New File</span>
            </div>
            <div
              class="context-menu-item"
              @click="openNewItemDialog('folder', contextMenuTarget.path)">
              <span class="i-carbon-folder-add" />
              <span>New Folder</span>
            </div>
          </template>

          <!-- For files and directories (not sections) -->
          <template v-if="contextMenuTarget?.type === 'file' || contextMenuTarget?.type === 'directory'">
            <div
              class="context-menu-divider"
              v-if="contextMenuTarget?.type === 'directory'" />
            <div
              class="context-menu-item"
              @click="openRenameDialog(contextMenuTarget.path, contextMenuTarget.entry?.name)">
              <span class="i-carbon-edit" />
              <span>Rename</span>
            </div>
            <div
              class="context-menu-item danger"
              @click="deleteItem(contextMenuTarget.path, contextMenuTarget.type === 'directory')">
              <span class="i-carbon-trash-can" />
              <span>Delete</span>
            </div>
            <div class="context-menu-divider" />
            <div
              class="context-menu-item"
              @click="copyPath(contextMenuTarget.path)">
              <span class="i-carbon-copy" />
              <span>Copy Path</span>
            </div>
          </template>

          <!-- Refresh for sections -->
          <template v-if="contextMenuTarget?.type === 'section'">
            <div class="context-menu-divider" />
            <div
              class="context-menu-item"
              @click="refreshSectionFromMenu(contextMenuTarget.path)">
              <span class="i-carbon-refresh" />
              <span>Refresh</span>
            </div>
          </template>
        </div>
      </div>
    </teleport>

    <!-- New File/Folder Dialog -->
    <el-dialog
      v-model="newItemDialogVisible"
      :title="newItemType === 'folder' ? 'New Folder' : 'New File'"
      width="400px"
      :close-on-click-modal="false">
      <el-form @submit.prevent="createNewItem">
        <el-form-item :label="newItemType === 'folder' ? 'Folder Name' : 'File Name'">
          <el-input
            v-model="newItemName"
            :placeholder="newItemType === 'folder' ? 'folder-name' : 'filename.txt'"
            autofocus
            @keyup.enter="createNewItem" />
        </el-form-item>
        <el-form-item label="Location">
          <el-input
            v-model="newItemParentPath"
            disabled />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newItemDialogVisible = false">Cancel</el-button>
        <el-button
          type="primary"
          @click="createNewItem">
          Create
        </el-button>
      </template>
    </el-dialog>

    <!-- Rename Dialog -->
    <el-dialog
      v-model="renameDialogVisible"
      title="Rename"
      width="400px"
      :close-on-click-modal="false">
      <el-form @submit.prevent="renameItem">
        <el-form-item label="New Name">
          <el-input
            v-model="renameNewName"
            placeholder="new-name"
            autofocus
            @keyup.enter="renameItem" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="renameDialogVisible = false">Cancel</el-button>
        <el-button
          type="primary"
          @click="renameItem">
          Rename
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.file-tree {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--el-bg-color);
  overflow: hidden;
}

.file-tree-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--el-border-color-light);
  flex-shrink: 0;
}

.file-tree-title {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--el-text-color-secondary);
  letter-spacing: 0.5px;
}

.file-tree-actions {
  display: flex;
  gap: 4px;
}

.watcher-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--el-color-danger);
  margin-left: 6px;
  flex-shrink: 0;
  transition: background-color 0.3s;
}

.watcher-indicator.connected {
  background: var(--el-color-success);
}

.watcher-indicator.connecting {
  background: var(--el-color-warning);
  animation: pulse 1s infinite;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

.file-tree-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  min-height: 0;
}

.file-tree-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

/* Section styles */
.file-tree-section {
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.file-tree-section:last-child {
  border-bottom: none;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  cursor: pointer;
  user-select: none;
  background: var(--el-fill-color-light);
  transition: background-color 0.15s;
}

.section-header:hover {
  background: var(--el-fill-color);
}

.section-chevron {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  transition: transform 0.15s;
  color: var(--el-text-color-secondary);
}

.section-chevron.expanded {
  transform: rotate(90deg);
}

.section-icon {
  font-size: 14px;
  color: var(--el-color-primary);
}

.section-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.section-actions {
  display: flex;
  gap: 2px;
  margin-left: auto;
  opacity: 0;
  transition: opacity 0.15s;
}

.section-header:hover .section-actions {
  opacity: 1;
}

.section-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: none;
  background: transparent;
  border-radius: 3px;
  cursor: pointer;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  transition:
    background-color 0.1s,
    color 0.1s;
}

.section-action-btn:hover {
  background: var(--el-fill-color-darker);
  color: var(--el-text-color-primary);
}

.section-content {
  padding-left: 8px;
}

.section-loading,
.section-error,
.section-empty {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.section-error {
  color: var(--el-color-danger);
}

.section-tree {
  padding: 4px 0;
}

/* Context Menu Styles */
.context-menu-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 9999;
}

.context-menu {
  position: fixed;
  min-width: 160px;
  background: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  padding: 4px 0;
  z-index: 10000;
}

.context-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  font-size: 13px;
  cursor: pointer;
  color: var(--el-text-color-primary);
  transition: background-color 0.1s;
}

.context-menu-item:hover {
  background: var(--el-fill-color-light);
}

.context-menu-item.danger {
  color: var(--el-color-danger);
}

.context-menu-item.danger:hover {
  background: var(--el-color-danger-light-9);
}

.context-menu-item span:first-child {
  font-size: 14px;
}

.context-menu-divider {
  height: 1px;
  background: var(--el-border-color-lighter);
  margin: 4px 0;
}
</style>
