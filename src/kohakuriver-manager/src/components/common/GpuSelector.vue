<script setup>
/**
 * GPU Selector Component
 *
 * Shared component for selecting GPUs across cluster nodes.
 * Used by both Task and VPS creation forms.
 *
 * Features:
 * - Displays online nodes with GPU info in collapsible panels
 * - Allows selecting GPUs from a single node only
 * - Disables other nodes once a GPU is selected on one node
 * - Shows GPU stats (memory, utilization, temperature)
 *
 * @example
 * <GpuSelector
 *   :online-nodes="clusterStore.onlineNodes"
 *   v-model="form.selectedGpus"
 *   v-model:expanded-nodes="expandedGpuNodes"
 *   ref="gpuSelectorRef"
 * />
 *
 * // Parent can call exposed methods:
 * gpuSelectorRef.value.getSelectedGpuInfo()
 * gpuSelectorRef.value.initializeGpuSelections()
 */

/**
 * @typedef {Object} GpuInfo
 * @property {number} gpu_id
 * @property {string} [name]
 * @property {number} [memory_total_mib]
 * @property {number} [gpu_utilization]
 * @property {number} [temperature]
 * @property {number} [vm_task_id] - If set, GPU is reserved by a VM VPS
 * @property {boolean} [vfio_bound] - If true, GPU is bound to VFIO driver
 */

/**
 * @typedef {Object} NodeInfo
 * @property {string} hostname
 * @property {GpuInfo[]} [gpu_info]
 */

const props = defineProps({
  /**
   * Array of online nodes from the cluster store.
   * @type {NodeInfo[]}
   */
  onlineNodes: {
    type: Array,
    required: true,
  },
  /**
   * The selected GPUs object: { hostname: [gpu_id1, ...] }
   * Used with v-model.
   * @type {Object<string, number[]>}
   */
  modelValue: {
    type: Object,
    required: true,
  },
  /**
   * Array of expanded node panel names (hostnames).
   * Used with v-model:expanded-nodes.
   * @type {string[]}
   */
  expandedNodes: {
    type: Array,
    default: () => [],
  },
})

const emit = defineEmits(['update:modelValue', 'update:expandedNodes'])

/**
 * Nodes that are online and have GPU info available.
 * @type {import('vue').ComputedRef<NodeInfo[]>}
 */
const nodesWithGpus = computed(() => {
  return props.onlineNodes.filter((n) => n.gpu_info && n.gpu_info.length > 0)
})

/**
 * Local proxy for the selectedGpus object.
 * Syncs with parent via v-model (modelValue / update:modelValue).
 */
const selectedGpus = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

/**
 * Local proxy for the expanded collapse panels.
 * Syncs with parent via v-model:expanded-nodes.
 */
const localExpandedNodes = computed({
  get: () => props.expandedNodes,
  set: (val) => emit('update:expandedNodes', val),
})

/**
 * Check if another GPU node is already selected (for disabling other nodes).
 * Only one node can have GPUs selected at a time.
 *
 * @param {string} hostname - The hostname to check
 * @returns {boolean} True if a different node already has GPUs selected
 */
function isAnotherGpuNodeSelected(hostname) {
  const selectedNode = Object.keys(selectedGpus.value).find(
    (h) => selectedGpus.value[h] && selectedGpus.value[h].length > 0
  )
  return selectedNode !== undefined && selectedNode !== hostname
}

/**
 * Get the selected GPU node hostname and GPU IDs.
 *
 * @returns {{ hostname: string, gpuIds: number[] } | null}
 *   The selected node hostname and GPU IDs, or null if nothing selected.
 */
function getSelectedGpuInfo() {
  for (const hostname in selectedGpus.value) {
    if (selectedGpus.value[hostname] && selectedGpus.value[hostname].length > 0) {
      return { hostname, gpuIds: selectedGpus.value[hostname] }
    }
  }
  return null
}

/**
 * Initialize the selectedGpus object with empty arrays for each GPU node.
 * Call this when enabling GPU selection mode.
 */
function initializeGpuSelections() {
  /** @type {Object<string, number[]>} */
  const gpus = {}
  for (const node of nodesWithGpus.value) {
    gpus[node.hostname] = []
  }
  emit('update:modelValue', gpus)
}

/**
 * Count available (non-reserved) GPUs on a node.
 *
 * @param {NodeInfo} node
 * @returns {number}
 */
function getAvailableGpuCount(node) {
  return (node.gpu_info || []).filter((g) => !g.vm_task_id && !g.vfio_bound).length
}

/**
 * Format MiB value to a human-readable GPU memory string.
 *
 * @param {number} mib - Memory in MiB
 * @returns {string} Formatted memory string (e.g., "24 GB" or "512 MB")
 */
function formatGpuMemory(mib) {
  if (!mib) return ''
  if (mib >= 1024) {
    return `${(mib / 1024).toFixed(0)} GB`
  }
  return `${mib.toFixed(0)} MB`
}

/**
 * Handle checkbox group change for a specific node.
 * Emits the updated selectedGpus object to the parent.
 *
 * @param {string} hostname - The node hostname whose GPUs changed
 * @param {number[]} gpuIds - The new array of selected GPU IDs for this node
 */
function handleGpuChange(hostname, gpuIds) {
  const updated = { ...selectedGpus.value, [hostname]: gpuIds }
  emit('update:modelValue', updated)
}

defineExpose({
  getSelectedGpuInfo,
  initializeGpuSelections,
})
</script>

<template>
  <div class="gpu-selector">
    <div class="gpu-selection-container">
      <el-empty
        v-if="nodesWithGpus.length === 0"
        description="No online nodes with GPUs"
        :image-size="60" />
      <el-collapse
        v-else
        v-model="localExpandedNodes">
        <el-collapse-item
          v-for="node in nodesWithGpus"
          :key="node.hostname"
          :name="node.hostname">
          <template #title>
            <span class="font-medium">{{ node.hostname }}</span>
            <span class="text-muted text-xs ml-2">
              ({{ getAvailableGpuCount(node) }}/{{ node.gpu_info.length }} GPUs available)
            </span>
          </template>
          <el-checkbox-group
            :model-value="selectedGpus[node.hostname] || []"
            :disabled="isAnotherGpuNodeSelected(node.hostname)"
            class="gpu-checkbox-grid"
            @update:model-value="handleGpuChange(node.hostname, $event)">
            <el-checkbox
              v-for="gpu in node.gpu_info"
              :key="gpu.gpu_id"
              :value="gpu.gpu_id"
              :disabled="!!gpu.vm_task_id || (gpu.vfio_bound && !gpu.vm_task_id)"
              border
              class="gpu-checkbox"
              :class="{ 'gpu-reserved': !!gpu.vm_task_id || gpu.vfio_bound }">
              <div class="gpu-checkbox-content">
                <span class="font-medium">GPU {{ gpu.gpu_id }}: {{ gpu.name || 'Unknown' }}</span>
                <span
                  v-if="gpu.vm_task_id"
                  class="gpu-reserved-tag">
                  Reserved by VM #{{ gpu.vm_task_id }}
                </span>
                <span
                  v-else-if="gpu.vfio_bound"
                  class="gpu-reserved-tag">
                  VFIO Bound
                </span>
                <span class="gpu-stats">
                  {{ formatGpuMemory(gpu.memory_total_mib) }}
                  <template v-if="gpu.gpu_utilization != null">| Util: {{ gpu.gpu_utilization }}%</template>
                  <template v-if="gpu.temperature != null">| Temp: {{ gpu.temperature }}°C</template>
                </span>
              </div>
            </el-checkbox>
          </el-checkbox-group>
        </el-collapse-item>
      </el-collapse>
    </div>
    <el-alert
      v-if="!getSelectedGpuInfo()"
      title="Select at least one GPU on a single node"
      type="info"
      show-icon
      :closable="false"
      class="mt-2" />
  </div>
</template>

<style scoped>
/* GPU Selection Styles */
.gpu-selection-container {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  padding: 8px;
  min-height: 80px;
  max-height: 300px;
  overflow-y: auto;
  width: 100%;
}

.gpu-checkbox-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.gpu-checkbox {
  margin: 0 !important;
  width: 100%;
  overflow: hidden;
}

:deep(.gpu-checkbox .el-checkbox__label) {
  overflow: hidden;
  width: 100%;
}

.gpu-checkbox-content {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  font-size: 0.85em;
  line-height: 1.4;
  overflow: hidden;
  width: 100%;
}

.gpu-checkbox-content > .font-medium {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  width: 100%;
}

.gpu-stats {
  font-size: 0.75em;
  color: var(--el-text-color-secondary);
}

.gpu-reserved {
  opacity: 0.6;
}

.gpu-reserved-tag {
  font-size: 0.7em;
  color: var(--el-color-warning);
  font-weight: 600;
}

:deep(.el-collapse) {
  border: none;
}

:deep(.el-collapse-item__header) {
  font-size: 0.9em;
  padding: 0 8px;
  background: transparent;
}

:deep(.el-collapse-item__content) {
  padding: 12px 8px;
}

:deep(.el-checkbox.is-bordered) {
  padding: 8px 10px !important;
  height: auto !important;
}
</style>
