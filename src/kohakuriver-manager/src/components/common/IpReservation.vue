<script setup>
/**
 * IP Reservation Component
 *
 * Allows users to reserve a specific container IP address before task/VPS submission.
 * Features:
 * - Toggle to enable IP reservation mode
 * - Auto-fetch available IPs when node is selected
 * - Input for specific IP with validation
 * - Reserve button that returns a token
 * - Shows reservation status
 */

import { overlayAPI } from '@/utils/api/overlay'
import { useNotification } from '@/composables/useNotification'

const props = defineProps({
  // Selected runner/node hostname (required for reservation)
  runner: {
    type: String,
    default: null,
  },
  // Whether overlay network is enabled
  overlayEnabled: {
    type: Boolean,
    default: true,
  },
})

const emit = defineEmits(['update:token', 'update:reservedIp'])

const notify = useNotification()

// Component state
const enabled = ref(false)
const loading = ref(false)
const reserving = ref(false)
const ipInfo = ref(null)
const availableIps = ref([])
const selectedIp = ref('')
const reservedToken = ref(null)
const reservedIp = ref(null)
const errorMessage = ref('')

// Computed: is IP valid for reservation
const isValidIp = computed(() => {
  if (!selectedIp.value) return false
  // Check if IP matches IPv4 pattern
  const ipPattern = /^(\d{1,3}\.){3}\d{1,3}$/
  return ipPattern.test(selectedIp.value)
})

// Computed: is IP in available list
const isIpAvailable = computed(() => {
  if (!selectedIp.value || availableIps.value.length === 0) return true
  return availableIps.value.includes(selectedIp.value)
})

// Watch runner changes - refresh IP info
watch(
  () => props.runner,
  async (newRunner) => {
    if (newRunner && enabled.value) {
      await fetchIpInfo()
    } else {
      resetState()
    }
  }
)

// Watch enabled toggle
watch(enabled, async (isEnabled) => {
  if (isEnabled && props.runner) {
    await fetchIpInfo()
  } else if (!isEnabled) {
    // Release existing reservation if any
    if (reservedToken.value) {
      await releaseReservation()
    }
    resetState()
  }
})

// Fetch IP info and available IPs for the runner
async function fetchIpInfo() {
  if (!props.runner) return

  loading.value = true
  errorMessage.value = ''

  try {
    const [infoRes, availRes] = await Promise.all([
      overlayAPI.getRunnerIpInfo(props.runner),
      overlayAPI.getAvailableIps(props.runner, 50),
    ])

    ipInfo.value = infoRes.data
    availableIps.value = availRes.data.available_ips?.[props.runner] || []
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Failed to fetch IP info'
    console.error('Failed to fetch IP info:', e)
  } finally {
    loading.value = false
  }
}

// Reserve the selected IP
async function reserveIp() {
  if (!props.runner || !isValidIp.value) return

  reserving.value = true
  errorMessage.value = ''

  try {
    const ip = selectedIp.value || null
    const res = await overlayAPI.reserveIp(props.runner, ip, 300) // 5 min TTL

    reservedToken.value = res.data.token
    reservedIp.value = res.data.ip

    // Emit the token and IP to parent
    emit('update:token', reservedToken.value)
    emit('update:reservedIp', reservedIp.value)

    notify.success(`IP ${reservedIp.value} reserved (5 min TTL)`)

    // Refresh available IPs
    await fetchIpInfo()
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Failed to reserve IP'
    notify.error(errorMessage.value)
  } finally {
    reserving.value = false
  }
}

// Release current reservation
async function releaseReservation() {
  if (!reservedToken.value) return

  try {
    await overlayAPI.releaseIpReservation(reservedToken.value)
    notify.info('IP reservation released')
  } catch (e) {
    console.error('Failed to release reservation:', e)
  }

  reservedToken.value = null
  reservedIp.value = null
  emit('update:token', null)
  emit('update:reservedIp', null)
}

// Reset component state
function resetState() {
  ipInfo.value = null
  availableIps.value = []
  selectedIp.value = ''
  errorMessage.value = ''
}

// Handle IP input - auto-complete from suggestions
function handleIpSelect(ip) {
  selectedIp.value = ip
}

// Expose release method for parent to call on dialog close
defineExpose({
  releaseReservation,
  hasReservation: () => !!reservedToken.value,
})
</script>

<template>
  <div class="ip-reservation">
    <!-- Enable Toggle -->
    <div class="flex items-center gap-2 mb-3">
      <el-switch
        v-model="enabled"
        :disabled="!overlayEnabled || !runner" />
      <span class="text-sm">Reserve specific container IP</span>
      <el-tooltip
        v-if="!overlayEnabled"
        content="Overlay network is not enabled"
        placement="top">
        <span class="i-carbon-information text-gray-400"></span>
      </el-tooltip>
      <el-tooltip
        v-else-if="!runner"
        content="Select a target node first"
        placement="top">
        <span class="i-carbon-information text-gray-400"></span>
      </el-tooltip>
    </div>

    <!-- IP Reservation UI (when enabled) -->
    <div
      v-if="enabled && runner"
      class="ip-reservation-content">
      <!-- Loading state -->
      <div
        v-if="loading"
        class="text-center py-4">
        <el-icon class="is-loading text-2xl text-blue-500"><i class="i-carbon-renew"></i></el-icon>
        <p class="text-sm text-muted mt-2">Loading IP info...</p>
      </div>

      <!-- IP Info Panel -->
      <div
        v-else-if="ipInfo"
        class="space-y-3">
        <!-- Subnet info -->
        <div class="p-3 bg-app-surface rounded-lg text-sm">
          <div class="grid grid-cols-2 gap-2">
            <div>
              <span class="text-muted">Subnet:</span>
              <span class="ml-2 font-mono">{{ ipInfo.subnet }}</span>
            </div>
            <div>
              <span class="text-muted">Available:</span>
              <span class="ml-2 text-green-500">{{ ipInfo.available }}</span>
              <span class="text-muted">/ {{ ipInfo.total_ips }}</span>
            </div>
          </div>
        </div>

        <!-- Reserved IP display (if already reserved) -->
        <div
          v-if="reservedIp"
          class="p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg">
          <div class="flex items-center justify-between">
            <div>
              <span class="text-green-700 dark:text-green-300 font-medium">
                <span class="i-carbon-checkmark-filled mr-1"></span>
                Reserved: {{ reservedIp }}
              </span>
              <p class="text-xs text-green-600 dark:text-green-400 mt-1">Token will be used when submitting</p>
            </div>
            <el-button
              size="small"
              type="danger"
              text
              @click="releaseReservation">
              Release
            </el-button>
          </div>
        </div>

        <!-- IP Selection (if not reserved yet) -->
        <div
          v-else
          class="space-y-2">
          <div class="flex gap-2">
            <el-autocomplete
              v-model="selectedIp"
              :fetch-suggestions="
                (query, cb) => cb(availableIps.filter((ip) => ip.includes(query)).map((ip) => ({ value: ip })))
              "
              placeholder="Enter IP or select from available"
              clearable
              class="flex-1"
              :class="{ 'is-error': selectedIp && !isIpAvailable }"
              @select="(item) => handleIpSelect(item.value)">
              <template #prefix>
                <span class="i-carbon-network-3"></span>
              </template>
            </el-autocomplete>
            <el-button
              type="primary"
              :loading="reserving"
              :disabled="!isValidIp"
              @click="reserveIp">
              Reserve
            </el-button>
          </div>

          <!-- Validation message -->
          <div
            v-if="selectedIp && !isIpAvailable"
            class="text-xs text-red-500">
            <span class="i-carbon-warning mr-1"></span>
            This IP may be in use or reserved
          </div>

          <!-- Quick select available IPs -->
          <div
            v-if="availableIps.length > 0"
            class="text-xs">
            <span class="text-muted">Quick select:</span>
            <div class="flex flex-wrap gap-1 mt-1">
              <el-tag
                v-for="ip in availableIps.slice(0, 8)"
                :key="ip"
                size="small"
                class="cursor-pointer hover:bg-blue-100 dark:hover:bg-blue-900"
                @click="selectedIp = ip">
                {{ ip }}
              </el-tag>
              <span
                v-if="availableIps.length > 8"
                class="text-muted">
                +{{ availableIps.length - 8 }} more
              </span>
            </div>
          </div>
        </div>

        <!-- Error message -->
        <el-alert
          v-if="errorMessage"
          :title="errorMessage"
          type="error"
          show-icon
          :closable="false"
          class="mt-2" />
      </div>

      <!-- No overlay allocation -->
      <div
        v-else-if="errorMessage"
        class="p-3 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg text-sm">
        <span class="i-carbon-warning text-yellow-500 mr-1"></span>
        {{ errorMessage }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.ip-reservation-content {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  padding: 12px;
}

:deep(.el-autocomplete.is-error .el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}
</style>
