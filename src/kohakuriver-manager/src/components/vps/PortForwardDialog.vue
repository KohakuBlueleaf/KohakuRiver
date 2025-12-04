<script setup>
/**
 * PortForwardDialog - Dialog for port forwarding information and commands.
 *
 * Shows users how to use the CLI to forward ports from their VPS/task
 * containers to their local machine.
 */

import { useNotification } from '@/composables/useNotification'

const props = defineProps({
  /**
   * Whether the dialog is visible
   */
  visible: {
    type: Boolean,
    default: false,
  },
  /**
   * Task/VPS ID to forward from
   */
  taskId: {
    type: [Number, String],
    required: true,
  },
  /**
   * Task status (only show if running)
   */
  status: {
    type: String,
    default: 'running',
  },
})

const emit = defineEmits(['update:visible', 'close'])

const notify = useNotification()

// Form data
const forwardForm = ref({
  remotePort: 8080,
  localPort: null, // null means same as remote
  protocol: 'tcp',
})

// Computed CLI command
const cliCommand = computed(() => {
  const localPort = forwardForm.value.localPort || forwardForm.value.remotePort
  const proto = forwardForm.value.protocol === 'udp' ? ' --proto udp' : ''
  const localPortArg = forwardForm.value.localPort ? ` -l ${forwardForm.value.localPort}` : ''
  return `kohakuriver forward ${props.taskId} ${forwardForm.value.remotePort}${localPortArg}${proto}`
})

// Example commands for common ports
const commonPorts = [
  { port: 80, name: 'HTTP', description: 'Web server' },
  { port: 443, name: 'HTTPS', description: 'Secure web server' },
  { port: 8080, name: 'Alt HTTP', description: 'Development server' },
  { port: 3000, name: 'Node.js', description: 'Node/React dev server' },
  { port: 5000, name: 'Flask', description: 'Python Flask' },
  { port: 8000, name: 'Django', description: 'Python Django' },
  { port: 3306, name: 'MySQL', description: 'MySQL database' },
  { port: 5432, name: 'PostgreSQL', description: 'PostgreSQL database' },
  { port: 6379, name: 'Redis', description: 'Redis cache' },
  { port: 27017, name: 'MongoDB', description: 'MongoDB database' },
]

/**
 * Copy command to clipboard.
 */
async function copyCommand() {
  try {
    await navigator.clipboard.writeText(cliCommand.value)
    notify.success('Command copied to clipboard')
  } catch (err) {
    // Fallback for non-secure contexts
    const textarea = document.createElement('textarea')
    textarea.value = cliCommand.value
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    notify.success('Command copied to clipboard')
  }
}

/**
 * Set port from quick select.
 */
function selectPort(port) {
  forwardForm.value.remotePort = port
}

/**
 * Close the dialog.
 */
function handleClose() {
  emit('update:visible', false)
  emit('close')
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="Port Forwarding"
    width="550px"
    @update:model-value="$emit('update:visible', $event)"
    @close="handleClose">
    <div class="space-y-4">
      <!-- Info message -->
      <el-alert
        type="info"
        :closable="false"
        show-icon>
        <template #title>Forward container ports to your local machine</template>
        <p class="text-sm mt-1">
          Use the KohakuRiver CLI to create a local proxy that forwards traffic to services running inside your
          container.
        </p>
      </el-alert>

      <!-- Port configuration -->
      <el-form
        :model="forwardForm"
        label-position="top"
        size="default">
        <div class="grid grid-cols-2 gap-4">
          <el-form-item label="Container Port">
            <el-input-number
              v-model="forwardForm.remotePort"
              :min="1"
              :max="65535"
              controls-position="right"
              class="w-full" />
          </el-form-item>

          <el-form-item label="Local Port (optional)">
            <el-input-number
              v-model="forwardForm.localPort"
              :min="1"
              :max="65535"
              :placeholder="String(forwardForm.remotePort)"
              controls-position="right"
              class="w-full" />
          </el-form-item>
        </div>

        <el-form-item label="Protocol">
          <el-radio-group v-model="forwardForm.protocol">
            <el-radio value="tcp">TCP</el-radio>
            <el-radio value="udp">UDP</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>

      <!-- Quick port selection -->
      <div class="quick-ports">
        <p class="text-sm text-muted mb-2">Common ports:</p>
        <div class="port-chips">
          <el-tag
            v-for="item in commonPorts"
            :key="item.port"
            :type="forwardForm.remotePort === item.port ? 'primary' : 'info'"
            effect="plain"
            size="small"
            class="port-chip"
            @click="selectPort(item.port)">
            {{ item.port }} ({{ item.name }})
          </el-tag>
        </div>
      </div>

      <!-- Generated command -->
      <div class="command-section">
        <p class="text-sm font-medium mb-2">CLI Command:</p>
        <div class="command-box">
          <code class="command-text">{{ cliCommand }}</code>
          <el-button
            type="primary"
            size="small"
            @click="copyCommand">
            <span class="i-carbon-copy mr-1" />
            Copy
          </el-button>
        </div>
      </div>

      <!-- Usage instructions -->
      <el-collapse>
        <el-collapse-item
          title="How to use"
          name="instructions">
          <div class="text-sm space-y-2 text-muted">
            <p>1. Open a terminal on your local machine</p>
            <p>2. Run the command above (keep it running)</p>
            <p>
              3. Access the forwarded port at
              <code>localhost:{{ forwardForm.localPort || forwardForm.remotePort }}</code>
            </p>
            <p>4. Press Ctrl+C to stop forwarding</p>
            <el-divider />
            <p><strong>Examples:</strong></p>
            <ul class="list-disc list-inside">
              <li>
                Forward web server:
                <code>kohakuriver forward {{ taskId }} 80 -l 8080</code>
              </li>
              <li>
                Forward database:
                <code>kohakuriver forward {{ taskId }} 5432</code>
              </li>
              <li>
                Forward UDP (e.g., DNS):
                <code>kohakuriver forward {{ taskId }} 53 --proto udp</code>
              </li>
            </ul>
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>

    <template #footer>
      <div class="flex justify-end gap-2">
        <el-button @click="handleClose">Close</el-button>
        <el-button
          type="primary"
          @click="copyCommand">
          <span class="i-carbon-copy mr-1" />
          Copy Command
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.quick-ports {
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
}

.port-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.port-chip {
  cursor: pointer;
  transition: all 0.2s;
}

.port-chip:hover {
  transform: translateY(-1px);
}

.command-section {
  padding: 12px;
  background: var(--el-bg-color-page);
  border-radius: 8px;
  border: 1px solid var(--el-border-color-light);
}

.command-box {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  background: #1e1e1e;
  border-radius: 6px;
}

.command-text {
  flex: 1;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  color: #4ec9b0;
  word-break: break-all;
}

:deep(.el-collapse-item__header) {
  font-size: 13px;
  font-weight: 500;
}

:deep(.el-collapse-item__content) {
  padding-bottom: 12px;
}

code {
  padding: 2px 6px;
  background: var(--el-fill-color);
  border-radius: 4px;
  font-family: monospace;
  font-size: 12px;
}
</style>
