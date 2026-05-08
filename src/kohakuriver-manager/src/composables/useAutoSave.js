import { useIdeStore } from '@/stores/ide'
import { useFileSystem } from '@/composables/useFileSystem'

/**
 * Composable for auto-save functionality.
 *
 * Automatically saves dirty files after a configurable delay.
 */
export function useAutoSave() {
  const ideStore = useIdeStore()
  const fs = useFileSystem()

  // Map of path -> timeout ID for pending saves
  const pendingSaves = ref(new Map())

  /**
   * Schedule an auto-save for a file.
   * Cancels any existing pending save for the same file.
   * @param {string} path - File path
   */
  function scheduleAutoSave(path) {
    if (!ideStore.autoSaveEnabled) return

    // Cancel existing pending save
    cancelPendingSave(path)

    // Schedule new save
    const timeoutId = setTimeout(async () => {
      await saveFile(path)
      pendingSaves.value.delete(path)
    }, ideStore.autoSaveDelay)

    pendingSaves.value.set(path, timeoutId)
  }

  /**
   * Cancel a pending auto-save for a file.
   * @param {string} path - File path
   */
  function cancelPendingSave(path) {
    const existingTimeout = pendingSaves.value.get(path)
    if (existingTimeout) {
      clearTimeout(existingTimeout)
      pendingSaves.value.delete(path)
    }
  }

  /**
   * Save a file immediately.
   * @param {string} path - File path
   * @returns {Promise<boolean>} - Whether save was successful
   */
  async function saveFile(path) {
    const file = ideStore.openFiles.find((f) => f.path === path)
    if (!file?.isDirty) return true

    ideStore.setSaving(path, true)

    try {
      await fs.writeFile(path, file.content, { encoding: file.encoding })
      return true
    } catch (e) {
      console.error('Auto-save failed:', e)
      return false
    } finally {
      ideStore.setSaving(path, false)
    }
  }

  /**
   * Force save a file immediately, canceling any pending auto-save.
   * @param {string} path - File path
   * @returns {Promise<boolean>}
   */
  async function saveNow(path) {
    cancelPendingSave(path)
    return saveFile(path)
  }

  /**
   * Save all dirty files immediately.
   * @returns {Promise<{success: number, failed: number}>}
   */
  async function saveAllDirty() {
    const dirtyFiles = ideStore.openFiles.filter((f) => f.isDirty)
    let success = 0
    let failed = 0

    for (const file of dirtyFiles) {
      cancelPendingSave(file.path)
      const result = await saveFile(file.path)
      if (result) {
        success++
      } else {
        failed++
      }
    }

    return { success, failed }
  }

  /**
   * Cancel all pending auto-saves.
   */
  function cancelAll() {
    pendingSaves.value.forEach((timeoutId) => clearTimeout(timeoutId))
    pendingSaves.value.clear()
  }

  /**
   * Check if a file has a pending save.
   * @param {string} path - File path
   * @returns {boolean}
   */
  function hasPendingSave(path) {
    return pendingSaves.value.has(path)
  }

  /**
   * Get count of files with pending saves.
   * @returns {number}
   */
  function pendingSaveCount() {
    return pendingSaves.value.size
  }

  // Cleanup on unmount
  onUnmounted(() => {
    cancelAll()
  })

  return {
    // State
    pendingSaves,

    // Actions
    scheduleAutoSave,
    cancelPendingSave,
    saveFile,
    saveNow,
    saveAllDirty,
    cancelAll,

    // Queries
    hasPendingSave,
    pendingSaveCount,
  }
}
