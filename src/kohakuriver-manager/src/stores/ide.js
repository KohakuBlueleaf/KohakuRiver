import { defineStore } from 'pinia'

/**
 * IDE Store - Manages the state for the VSCode-like IDE interface.
 *
 * Handles:
 * - Open files and tabs
 * - File tree state (expanded paths, loading)
 * - Layout preferences (terminal position, panel sizes)
 * - Auto-save configuration
 */
export const useIdeStore = defineStore('ide', () => {
  // ==========================================================================
  // Connection State
  // ==========================================================================

  const taskId = ref(null)
  const containerName = ref(null)
  const connected = ref(false)
  const connectionType = ref('task') // 'task' or 'container'

  // ==========================================================================
  // File Tree State
  // ==========================================================================

  const rootPath = ref('/')
  const expandedPaths = ref(new Set())
  const fileTree = ref({}) // { path: { name, type, children?, loaded?, loading? } }
  const loadingPaths = ref(new Set())
  const selectedPath = ref(null)
  /** @type {import('vue').Ref<{path: string, name: string, type: string, size: number} | null>} */
  const selectedFileInfo = ref(null)

  // ==========================================================================
  // Open Files State
  // ==========================================================================

  // Each file: { path, name, content, originalContent, isDirty, language, encoding }
  const openFiles = ref([])
  const activeFilePath = ref(null)

  // ==========================================================================
  // UI/Layout State
  // ==========================================================================

  const fileTreeWidth = ref(250)
  const terminalSize = ref(300) // width if right, height if bottom
  const terminalPosition = ref('right') // 'right' | 'bottom'
  const showFileTree = ref(true)
  const showTerminal = ref(true)

  // ==========================================================================
  // Auto-save State
  // ==========================================================================

  const autoSaveEnabled = ref(true)
  const autoSaveDelay = ref(2000) // ms
  const savingFiles = ref(new Set())

  // ==========================================================================
  // Computed Properties
  // ==========================================================================

  const activeFile = computed(() => openFiles.value.find((f) => f.path === activeFilePath.value))

  const hasUnsavedChanges = computed(() => openFiles.value.some((f) => f.isDirty))

  const openFilePaths = computed(() => openFiles.value.map((f) => f.path))

  // ==========================================================================
  // Connection Actions
  // ==========================================================================

  function setConnection(id, type = 'task', container = null) {
    taskId.value = id
    connectionType.value = type
    containerName.value = container
    connected.value = true
  }

  function clearConnection() {
    taskId.value = null
    containerName.value = null
    connected.value = false
    connectionType.value = 'task'
  }

  // ==========================================================================
  // File Tree Actions
  // ==========================================================================

  function setRootPath(path) {
    rootPath.value = path
  }

  function toggleExpanded(path) {
    if (expandedPaths.value.has(path)) {
      expandedPaths.value.delete(path)
    } else {
      expandedPaths.value.add(path)
    }
    // Force reactivity
    expandedPaths.value = new Set(expandedPaths.value)
  }

  function setExpanded(path, expanded) {
    if (expanded) {
      expandedPaths.value.add(path)
    } else {
      expandedPaths.value.delete(path)
    }
    expandedPaths.value = new Set(expandedPaths.value)
  }

  function setLoading(path, loading) {
    if (loading) {
      loadingPaths.value.add(path)
    } else {
      loadingPaths.value.delete(path)
    }
    loadingPaths.value = new Set(loadingPaths.value)
  }

  function isLoading(path) {
    return loadingPaths.value.has(path)
  }

  function isExpanded(path) {
    return expandedPaths.value.has(path)
  }

  function setSelectedPath(path) {
    selectedPath.value = path
  }

  function setSelectedFileInfo(info) {
    selectedFileInfo.value = info
  }

  // ==========================================================================
  // Open Files Actions
  // ==========================================================================

  function openFile(path, content, language = 'plaintext', encoding = 'utf-8') {
    // Check if file is already open
    const existing = openFiles.value.find((f) => f.path === path)
    if (existing) {
      activeFilePath.value = path
      return existing
    }

    // Extract filename from path
    const name = path.split('/').pop() || path

    const file = {
      path,
      name,
      content,
      originalContent: content,
      isDirty: false,
      language,
      encoding,
      cursorPosition: { line: 1, column: 1 },
    }

    openFiles.value.push(file)
    activeFilePath.value = path

    return file
  }

  function closeFile(path) {
    const index = openFiles.value.findIndex((f) => f.path === path)
    if (index === -1) return

    openFiles.value.splice(index, 1)

    // Update active file if needed
    if (activeFilePath.value === path) {
      if (openFiles.value.length > 0) {
        // Select previous file or first available
        const newIndex = Math.max(0, index - 1)
        activeFilePath.value = openFiles.value[newIndex]?.path || null
      } else {
        activeFilePath.value = null
      }
    }
  }

  function closeAllFiles() {
    openFiles.value = []
    activeFilePath.value = null
  }

  function closeOtherFiles(path) {
    openFiles.value = openFiles.value.filter((f) => f.path === path)
    activeFilePath.value = path
  }

  function setActiveFile(path) {
    if (openFiles.value.some((f) => f.path === path)) {
      activeFilePath.value = path
    }
  }

  function updateFileContent(path, content) {
    const file = openFiles.value.find((f) => f.path === path)
    if (file) {
      file.content = content
      file.isDirty = content !== file.originalContent
    }
  }

  function markFileSaved(path, newContent = null) {
    const file = openFiles.value.find((f) => f.path === path)
    if (file) {
      if (newContent !== null) {
        file.content = newContent
      }
      file.originalContent = file.content
      file.isDirty = false
    }
  }

  function updateFileCursor(path, line, column) {
    const file = openFiles.value.find((f) => f.path === path)
    if (file) {
      file.cursorPosition = { line, column }
    }
  }

  function nextTab() {
    if (openFiles.value.length <= 1) return
    const currentIndex = openFiles.value.findIndex((f) => f.path === activeFilePath.value)
    const nextIndex = (currentIndex + 1) % openFiles.value.length
    activeFilePath.value = openFiles.value[nextIndex].path
  }

  function prevTab() {
    if (openFiles.value.length <= 1) return
    const currentIndex = openFiles.value.findIndex((f) => f.path === activeFilePath.value)
    const prevIndex = (currentIndex - 1 + openFiles.value.length) % openFiles.value.length
    activeFilePath.value = openFiles.value[prevIndex].path
  }

  // ==========================================================================
  // UI/Layout Actions
  // ==========================================================================

  function toggleFileTree() {
    showFileTree.value = !showFileTree.value
  }

  function toggleTerminal() {
    showTerminal.value = !showTerminal.value
  }

  function toggleTerminalPosition() {
    terminalPosition.value = terminalPosition.value === 'right' ? 'bottom' : 'right'
    _saveLayoutPreferences()
  }

  function setFileTreeWidth(width) {
    fileTreeWidth.value = Math.max(100, Math.min(400, width))
    _saveLayoutPreferences()
  }

  function setTerminalSize(size) {
    terminalSize.value = Math.max(100, Math.min(600, size))
    _saveLayoutPreferences()
  }

  // ==========================================================================
  // Auto-save Actions
  // ==========================================================================

  function setSaving(path, saving) {
    if (saving) {
      savingFiles.value.add(path)
    } else {
      savingFiles.value.delete(path)
    }
    savingFiles.value = new Set(savingFiles.value)
  }

  function isSaving(path) {
    return savingFiles.value.has(path)
  }

  function setAutoSaveEnabled(enabled) {
    autoSaveEnabled.value = enabled
    _saveLayoutPreferences()
  }

  // ==========================================================================
  // Persistence
  // ==========================================================================

  function _saveLayoutPreferences() {
    try {
      localStorage.setItem(
        'ide-layout',
        JSON.stringify({
          fileTreeWidth: fileTreeWidth.value,
          terminalSize: terminalSize.value,
          terminalPosition: terminalPosition.value,
          autoSaveEnabled: autoSaveEnabled.value,
        })
      )
    } catch (e) {
      console.warn('Failed to save IDE layout preferences:', e)
    }
  }

  function _loadLayoutPreferences() {
    try {
      const saved = localStorage.getItem('ide-layout')
      if (saved) {
        const prefs = JSON.parse(saved)
        if (prefs.fileTreeWidth) fileTreeWidth.value = prefs.fileTreeWidth
        if (prefs.terminalSize) terminalSize.value = prefs.terminalSize
        if (prefs.terminalPosition) terminalPosition.value = prefs.terminalPosition
        if (typeof prefs.autoSaveEnabled === 'boolean') autoSaveEnabled.value = prefs.autoSaveEnabled
      }
    } catch (e) {
      console.warn('Failed to load IDE layout preferences:', e)
    }
  }

  // Load preferences on store creation
  _loadLayoutPreferences()

  // ==========================================================================
  // Reset
  // ==========================================================================

  function $reset() {
    taskId.value = null
    containerName.value = null
    connected.value = false
    connectionType.value = 'task'
    rootPath.value = '/'
    expandedPaths.value = new Set()
    fileTree.value = {}
    loadingPaths.value = new Set()
    selectedPath.value = null
    selectedFileInfo.value = null
    openFiles.value = []
    activeFilePath.value = null
    savingFiles.value = new Set()
  }

  // ==========================================================================
  // Return
  // ==========================================================================

  return {
    // Connection State
    taskId,
    containerName,
    connected,
    connectionType,

    // File Tree State
    rootPath,
    expandedPaths,
    fileTree,
    loadingPaths,
    selectedPath,
    selectedFileInfo,

    // Open Files State
    openFiles,
    activeFilePath,

    // UI/Layout State
    fileTreeWidth,
    terminalSize,
    terminalPosition,
    showFileTree,
    showTerminal,

    // Auto-save State
    autoSaveEnabled,
    autoSaveDelay,
    savingFiles,

    // Computed
    activeFile,
    hasUnsavedChanges,
    openFilePaths,

    // Connection Actions
    setConnection,
    clearConnection,

    // File Tree Actions
    setRootPath,
    toggleExpanded,
    setExpanded,
    setLoading,
    isLoading,
    isExpanded,
    setSelectedPath,
    setSelectedFileInfo,

    // Open Files Actions
    openFile,
    closeFile,
    closeAllFiles,
    closeOtherFiles,
    setActiveFile,
    updateFileContent,
    markFileSaved,
    updateFileCursor,
    nextTab,
    prevTab,

    // UI/Layout Actions
    toggleFileTree,
    toggleTerminal,
    toggleTerminalPosition,
    setFileTreeWidth,
    setTerminalSize,

    // Auto-save Actions
    setSaving,
    isSaving,
    setAutoSaveEnabled,

    // Reset
    $reset,
  }
})
