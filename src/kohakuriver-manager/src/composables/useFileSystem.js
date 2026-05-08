import { filesystemAPI } from '@/utils/api'
import { useIdeStore } from '@/stores/ide'

// File size thresholds
const LARGE_FILE_THRESHOLD = 1024 * 1024 // 1 MB
const MAX_FILE_SIZE = 10 * 1024 * 1024 // 10 MB

// Binary file extensions
const BINARY_EXTENSIONS = new Set([
  'png',
  'jpg',
  'jpeg',
  'gif',
  'bmp',
  'ico',
  'webp',
  'svg',
  'tiff',
  'tif',
  'pdf',
  'doc',
  'docx',
  'xls',
  'xlsx',
  'ppt',
  'pptx',
  'odt',
  'ods',
  'odp',
  'zip',
  'tar',
  'gz',
  'bz2',
  'xz',
  '7z',
  'rar',
  'jar',
  'war',
  'exe',
  'dll',
  'so',
  'dylib',
  'bin',
  'dat',
  'db',
  'sqlite',
  'sqlite3',
  'mp3',
  'mp4',
  'avi',
  'mov',
  'mkv',
  'flv',
  'wav',
  'flac',
  'ogg',
  'webm',
  'woff',
  'woff2',
  'ttf',
  'otf',
  'eot',
  'pyc',
  'pyo',
  'class',
  'o',
  'obj',
  'a',
  'lib',
  'iso',
  'dmg',
  'img',
  'vmdk',
  'vdi',
])

/**
 * Check if a file is likely binary based on extension.
 */
function isBinaryFile(path) {
  const ext = path.split('.').pop()?.toLowerCase()
  return ext ? BINARY_EXTENSIONS.has(ext) : false
}

/**
 * Composable for filesystem operations inside containers.
 *
 * Provides methods to list, read, write, create, delete, and rename files.
 */
export function useFileSystem() {
  const ideStore = useIdeStore()

  const loading = ref(false)
  const error = ref(null)

  /**
   * Get the current task ID from the IDE store.
   */
  function getTaskId() {
    const taskId = ideStore.taskId
    if (!taskId) {
      throw new Error('No task connected')
    }
    return taskId
  }

  /**
   * List directory contents.
   * @param {string} path - Directory path
   * @param {boolean} showHidden - Include hidden files
   * @returns {Promise<Array>} - Array of file entries
   */
  async function listDirectory(path = '/', showHidden = false) {
    const taskId = getTaskId()

    loading.value = true
    error.value = null
    ideStore.setLoading(path, true)

    try {
      const { data } = await filesystemAPI.listDirectory(taskId, path, showHidden)
      return data.entries || []
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      console.error('Failed to list directory:', e)
      throw e
    } finally {
      loading.value = false
      ideStore.setLoading(path, false)
    }
  }

  /**
   * Read file contents.
   * @param {string} path - File path
   * @param {string} encoding - Output encoding ('utf-8' or 'base64')
   * @returns {Promise<{content: string, encoding: string, size: number, truncated: boolean}>}
   */
  async function readFile(path, encoding = 'utf-8') {
    const taskId = getTaskId()

    loading.value = true
    error.value = null

    try {
      const { data } = await filesystemAPI.readFile(taskId, path, encoding)
      return data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      console.error('Failed to read file:', e)
      throw e
    } finally {
      loading.value = false
    }
  }

  /**
   * Write file contents.
   * @param {string} path - File path
   * @param {string} content - File content
   * @param {object} options - Additional options
   * @returns {Promise<{path: string, size: number, success: boolean}>}
   */
  async function writeFile(path, content, options = {}) {
    const taskId = getTaskId()

    loading.value = true
    error.value = null
    ideStore.setSaving(path, true)

    try {
      const { data } = await filesystemAPI.writeFile(taskId, path, content, options)

      // Mark file as saved in store
      ideStore.markFileSaved(path, content)

      return data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      console.error('Failed to write file:', e)
      throw e
    } finally {
      loading.value = false
      ideStore.setSaving(path, false)
    }
  }

  /**
   * Create a directory.
   * @param {string} path - Directory path
   * @param {boolean} parents - Create parent directories
   * @returns {Promise<{message: string, path: string}>}
   */
  async function createDirectory(path, parents = true) {
    const taskId = getTaskId()

    loading.value = true
    error.value = null

    try {
      const { data } = await filesystemAPI.mkdir(taskId, path, parents)
      return data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      console.error('Failed to create directory:', e)
      throw e
    } finally {
      loading.value = false
    }
  }

  /**
   * Create a new file with optional content.
   * @param {string} path - File path
   * @param {string} content - Initial content
   * @returns {Promise<{path: string, size: number, success: boolean}>}
   */
  async function createFile(path, content = '') {
    return writeFile(path, content, { createParents: true })
  }

  /**
   * Delete a file or directory.
   * @param {string} path - Path to delete
   * @param {boolean} recursive - Delete directories recursively
   * @returns {Promise<{message: string, path: string}>}
   */
  async function deleteItem(path, recursive = false) {
    const taskId = getTaskId()

    loading.value = true
    error.value = null

    try {
      const { data } = await filesystemAPI.deleteItem(taskId, path, recursive)

      // Close the file if it's open
      ideStore.closeFile(path)

      return data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      console.error('Failed to delete item:', e)
      throw e
    } finally {
      loading.value = false
    }
  }

  /**
   * Rename or move a file/directory.
   * @param {string} source - Source path
   * @param {string} destination - Destination path
   * @param {boolean} overwrite - Overwrite if destination exists
   * @returns {Promise<{message: string, source: string, destination: string}>}
   */
  async function renameItem(source, destination, overwrite = false) {
    const taskId = getTaskId()

    loading.value = true
    error.value = null

    try {
      const { data } = await filesystemAPI.rename(taskId, source, destination, overwrite)

      // Update the file path if it's open
      const openFile = ideStore.openFiles.find((f) => f.path === source)
      if (openFile) {
        openFile.path = destination
        openFile.name = destination.split('/').pop() || destination
        if (ideStore.activeFilePath === source) {
          ideStore.activeFilePath = destination
        }
      }

      return data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      console.error('Failed to rename item:', e)
      throw e
    } finally {
      loading.value = false
    }
  }

  /**
   * Get file/directory metadata.
   * @param {string} path - Path to stat
   * @returns {Promise<{path: string, type: string, size: number, mtime: string, permissions: string, owner: string, is_readable: boolean, is_writable: boolean, is_binary: boolean}>}
   */
  async function stat(path) {
    const taskId = getTaskId()

    loading.value = true
    error.value = null

    try {
      const { data } = await filesystemAPI.stat(taskId, path)
      return data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      console.error('Failed to stat path:', e)
      throw e
    } finally {
      loading.value = false
    }
  }

  /**
   * Open a file in the editor.
   * Reads the file content and adds it to open files.
   * Handles binary file warnings and large file confirmations.
   * @param {string} path - File path
   * @param {number} fileSize - Optional file size in bytes (from file entry)
   * @returns {Promise<object|null>} - The opened file object or null if cancelled
   */
  async function openFileInEditor(path, fileSize = 0) {
    // Check if already open
    const existing = ideStore.openFiles.find((f) => f.path === path)
    if (existing) {
      ideStore.setActiveFile(path)
      return existing
    }

    // Check for binary files
    if (isBinaryFile(path)) {
      ElMessage.warning({
        message: 'Binary files cannot be displayed in the editor',
        duration: 3000,
      })
      return null
    }

    // Check for very large files
    if (fileSize > MAX_FILE_SIZE) {
      ElMessage.error({
        message: `File is too large (${formatFileSize(fileSize)}). Maximum supported size is ${formatFileSize(MAX_FILE_SIZE)}.`,
        duration: 5000,
      })
      return null
    }

    // Warn about large files
    if (fileSize > LARGE_FILE_THRESHOLD) {
      try {
        await ElMessageBox.confirm(
          `This file is ${formatFileSize(fileSize)}. Loading large files may affect performance. Continue?`,
          'Large File Warning',
          {
            confirmButtonText: 'Open',
            cancelButtonText: 'Cancel',
            type: 'warning',
          }
        )
      } catch {
        return null // User cancelled
      }
    }

    // Read file content
    const fileData = await readFile(path)

    // Check if file is binary based on content (server may detect this)
    if (fileData.is_binary) {
      ElMessage.warning({
        message: 'This file appears to be binary and cannot be displayed',
        duration: 3000,
      })
      return null
    }

    // Detect language from extension
    const language = detectLanguage(path)

    // Open in editor
    return ideStore.openFile(path, fileData.content, language, fileData.encoding)
  }

  /**
   * Format file size for display.
   */
  function formatFileSize(bytes) {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  /**
   * Save the currently active file.
   * @returns {Promise<object|null>}
   */
  async function saveActiveFile() {
    const file = ideStore.activeFile
    if (!file?.isDirty) return null

    return writeFile(file.path, file.content, { encoding: file.encoding })
  }

  /**
   * Save all dirty files.
   * @returns {Promise<Array>}
   */
  async function saveAllFiles() {
    const dirtyFiles = ideStore.openFiles.filter((f) => f.isDirty)
    const results = await Promise.all(dirtyFiles.map((f) => writeFile(f.path, f.content, { encoding: f.encoding })))
    return results
  }

  return {
    // State
    loading,
    error,

    // Directory operations
    listDirectory,

    // File operations
    readFile,
    writeFile,
    createFile,
    deleteItem,
    renameItem,
    stat,

    // Directory operations
    createDirectory,

    // Editor integration
    openFileInEditor,
    saveActiveFile,
    saveAllFiles,
  }
}

/**
 * Detect language from file extension.
 */
function detectLanguage(path) {
  const ext = path.split('.').pop()?.toLowerCase()

  const languageMap = {
    js: 'javascript',
    jsx: 'javascript',
    mjs: 'javascript',
    cjs: 'javascript',
    ts: 'typescript',
    tsx: 'typescript',
    mts: 'typescript',
    py: 'python',
    vue: 'html',
    json: 'json',
    md: 'markdown',
    css: 'css',
    scss: 'scss',
    less: 'less',
    html: 'html',
    htm: 'html',
    xml: 'xml',
    sh: 'shell',
    bash: 'shell',
    zsh: 'shell',
    yaml: 'yaml',
    yml: 'yaml',
    toml: 'ini',
    ini: 'ini',
    sql: 'sql',
    go: 'go',
    rs: 'rust',
    java: 'java',
    c: 'c',
    cpp: 'cpp',
    h: 'c',
    hpp: 'cpp',
    rb: 'ruby',
    php: 'php',
    swift: 'swift',
    kt: 'kotlin',
    r: 'r',
    R: 'r',
    lua: 'lua',
    pl: 'perl',
    ex: 'elixir',
    exs: 'elixir',
    erl: 'erlang',
    hs: 'haskell',
    clj: 'clojure',
    scala: 'scala',
    dockerfile: 'dockerfile',
    makefile: 'makefile',
  }

  return languageMap[ext] || 'plaintext'
}
