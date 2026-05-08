import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)

/**
 * Format bytes to human readable string
 * @param {number} bytes
 * @param {number} decimals
 */
export function formatBytes(bytes, decimals = 2) {
  if (bytes === 0 || bytes === null || bytes === undefined) return '0 B'

  const k = 1024
  const dm = decimals < 0 ? 0 : decimals
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']

  const i = Math.floor(Math.log(bytes) / Math.log(k))

  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i]
}

/**
 * Format date to readable string
 * @param {string|Date} date
 */
export function formatDate(date) {
  if (!date) return '-'
  return dayjs(date).format('YYYY-MM-DD HH:mm:ss')
}

/**
 * Format date to relative time (e.g., "5 minutes ago")
 * @param {string|Date} date
 */
export function formatRelativeTime(date) {
  if (!date) return '-'
  return dayjs(date).fromNow()
}

/**
 * Format duration in seconds to readable string
 * @param {number} seconds
 */
export function formatDuration(seconds) {
  if (!seconds || seconds < 0) return '-'

  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)

  if (hours > 0) {
    return `${hours}h ${minutes}m ${secs}s`
  } else if (minutes > 0) {
    return `${minutes}m ${secs}s`
  } else {
    return `${secs}s`
  }
}

/**
 * Format percentage with fixed decimals, handling NaN/null/undefined
 * @param {number} value
 * @param {number} decimals
 */
export function formatPercent(value, decimals = 1) {
  if (value === null || value === undefined || isNaN(value)) return '0.0%'
  return `${value.toFixed(decimals)}%`
}

/**
 * Format CPU cores count
 * @param {number} cores
 */
export function formatCores(cores) {
  if (!cores) return '-'
  return `${cores} ${cores === 1 ? 'core' : 'cores'}`
}

/**
 * Truncate string with ellipsis
 * @param {string} str
 * @param {number} maxLength
 */
export function truncate(str, maxLength = 50) {
  if (!str) return ''
  if (str.length <= maxLength) return str
  return str.slice(0, maxLength - 3) + '...'
}

/**
 * Format task ID for display (truncate if too long)
 * @param {string|number} taskId
 */
export function formatTaskId(taskId) {
  if (!taskId) return '-'
  const str = String(taskId)
  if (str.length <= 8) return str
  return str.slice(0, 4) + '...' + str.slice(-4)
}

/**
 * Format required GPUs array
 * @param {Array} requiredGpus
 */
export function formatRequiredGpus(requiredGpus) {
  if (!requiredGpus) return '-'
  if (!Array.isArray(requiredGpus) || requiredGpus.length === 0) return '-'
  try {
    const allGpuIds = requiredGpus.flat()
    if (allGpuIds.length === 0) return '-'
    return allGpuIds.join(', ')
  } catch {
    return '-'
  }
}
