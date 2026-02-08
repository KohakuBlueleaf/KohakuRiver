/**
 * Composable for file tree context menu and file operations.
 *
 * Manages context menu state, new-item / rename dialogs,
 * and CRUD operations (create, rename, delete, copy path).
 */
import { ref } from 'vue'

export function useFileTreeOps(fs, sections, directoryCache, loadSection) {
  // Context menu state
  const contextMenuVisible = ref(false)
  const contextMenuPosition = ref({ x: 0, y: 0 })
  const contextMenuTarget = ref(null) // { type: 'file'|'directory'|'section', path: string, entry?: object }

  // Dialog states
  const newItemDialogVisible = ref(false)
  const newItemType = ref('file') // 'file' or 'folder'
  const newItemName = ref('')
  const newItemParentPath = ref('')
  const renameDialogVisible = ref(false)
  const renameNewName = ref('')
  const renameOldPath = ref('')

  /**
   * Show context menu for a node.
   */
  function showContextMenu(e, target) {
    e.preventDefault()
    e.stopPropagation()
    contextMenuPosition.value = { x: e.clientX, y: e.clientY }
    contextMenuTarget.value = target
    contextMenuVisible.value = true
  }

  /**
   * Hide context menu.
   */
  function hideContextMenu() {
    contextMenuVisible.value = false
    contextMenuTarget.value = null
  }

  /**
   * Handle right-click on section header.
   */
  function handleSectionContextMenu(e, sectionPath) {
    showContextMenu(e, { type: 'section', path: sectionPath })
  }

  /**
   * Handle right-click on node (forwarded from FileTreeNode).
   */
  function handleNodeContextMenu(e, entry) {
    showContextMenu(e, {
      type: entry.type === 'directory' ? 'directory' : 'file',
      path: entry.path,
      entry,
    })
  }

  /**
   * Open new file/folder dialog.
   */
  function openNewItemDialog(type, parentPath) {
    newItemType.value = type
    newItemParentPath.value = parentPath
    newItemName.value = ''
    newItemDialogVisible.value = true
    hideContextMenu()
  }

  /**
   * Create new file or folder.
   */
  async function createNewItem() {
    if (!newItemName.value.trim()) {
      ElMessage.warning('Please enter a name')
      return
    }

    const fullPath =
      newItemParentPath.value === '/'
        ? `/${newItemName.value.trim()}`
        : `${newItemParentPath.value}/${newItemName.value.trim()}`

    try {
      if (newItemType.value === 'folder') {
        await fs.createDirectory(fullPath)
        ElMessage.success('Folder created')
      } else {
        await fs.createFile(fullPath, '')
        ElMessage.success('File created')
      }

      // Refresh parent directory
      directoryCache.value.delete(newItemParentPath.value)
      const section = sections.value.find((s) => fullPath.startsWith(s.path) || s.path === '/')
      if (section) {
        await loadSection(section.path)
      }

      newItemDialogVisible.value = false
    } catch (e) {
      ElMessage.error(e.response?.data?.detail || e.message || 'Failed to create item')
    }
  }

  /**
   * Open rename dialog.
   */
  function openRenameDialog(path, name) {
    renameOldPath.value = path
    renameNewName.value = name
    renameDialogVisible.value = true
    hideContextMenu()
  }

  /**
   * Rename file or folder.
   */
  async function renameItem() {
    if (!renameNewName.value.trim()) {
      ElMessage.warning('Please enter a name')
      return
    }

    const parentPath = renameOldPath.value.substring(0, renameOldPath.value.lastIndexOf('/')) || '/'
    const newPath =
      parentPath === '/' ? `/${renameNewName.value.trim()}` : `${parentPath}/${renameNewName.value.trim()}`

    try {
      await fs.renameItem(renameOldPath.value, newPath)
      ElMessage.success('Renamed successfully')

      // Refresh parent directory
      directoryCache.value.delete(parentPath)
      const section = sections.value.find((s) => newPath.startsWith(s.path) || s.path === '/')
      if (section) {
        await loadSection(section.path)
      }

      renameDialogVisible.value = false
    } catch (e) {
      ElMessage.error(e.response?.data?.detail || e.message || 'Failed to rename')
    }
  }

  /**
   * Delete file or folder.
   */
  async function deleteItem(path, isDirectory) {
    hideContextMenu()

    try {
      await ElMessageBox.confirm(`Are you sure you want to delete "${path.split('/').pop()}"?`, 'Delete Confirmation', {
        confirmButtonText: 'Delete',
        cancelButtonText: 'Cancel',
        type: 'warning',
      })

      await fs.deleteItem(path, isDirectory)
      ElMessage.success('Deleted successfully')

      // Refresh parent directory
      const parentPath = path.substring(0, path.lastIndexOf('/')) || '/'
      directoryCache.value.delete(parentPath)
      const section = sections.value.find((s) => path.startsWith(s.path) || s.path === '/')
      if (section) {
        await loadSection(section.path)
      }
    } catch (e) {
      if (e !== 'cancel') {
        ElMessage.error(e.response?.data?.detail || e.message || 'Failed to delete')
      }
    }
  }

  /**
   * Copy file path to clipboard.
   */
  async function copyPath(path) {
    hideContextMenu()
    try {
      await navigator.clipboard.writeText(path)
      ElMessage.success('Path copied to clipboard')
    } catch (e) {
      ElMessage.error('Failed to copy path')
    }
  }

  /**
   * Refresh section and hide context menu.
   */
  async function refreshSectionFromMenu(sectionPath) {
    hideContextMenu()
    // refreshSection is called via loadSection's parent (the component owns refreshSection),
    // but we can replicate the cache-clear + reload pattern here.
    directoryCache.value.delete(sectionPath)
    await loadSection(sectionPath)
  }

  return {
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
  }
}
