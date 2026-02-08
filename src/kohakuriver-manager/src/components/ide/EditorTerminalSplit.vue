<script setup>
/**
 * EditorTerminalSplit - Editor and optional terminal split pane.
 *
 * Renders the editor alongside a terminal panel (when visible),
 * with the split direction driven by the terminal position setting.
 * Extracted from IdeLayout to eliminate template duplication.
 */

import { useIdeStore } from '@/stores/ide'
import SplitPane from './common/SplitPane.vue'
import EditorPane from './editor/EditorPane.vue'
import TerminalPane from './terminal/TerminalPane.vue'

const props = defineProps({
  /**
   * Task ID to connect to
   */
  taskId: {
    type: [Number, String],
    required: true,
  },
  /**
   * Connection type: 'task' or 'container'
   */
  type: {
    type: String,
    default: 'task',
  },
  /**
   * Container name (for host containers)
   */
  containerName: {
    type: String,
    default: null,
  },
})

const emit = defineEmits(['terminal-connected', 'terminal-disconnected'])

const ideStore = useIdeStore()

// Refs
const editorRef = ref(null)
const terminalRef = ref(null)

/** @type {import('vue').ComputedRef<{direction: string, minSize: number, maxSize: number, storageKey: string}>} */
const terminalSplitConfig = computed(() => {
  const right = ideStore.terminalPosition === 'right'
  return {
    direction: right ? 'horizontal' : 'vertical',
    minSize: right ? 200 : 100,
    maxSize: right ? 600 : 400,
    storageKey: right ? 'ide-terminal-right' : 'ide-terminal-bottom',
  }
})

/**
 * Handle terminal connected event.
 */
function handleTerminalConnected() {
  emit('terminal-connected')
}

/**
 * Handle terminal disconnected event.
 */
function handleTerminalDisconnected() {
  emit('terminal-disconnected')
}

// Expose child refs so parent can access editor/terminal
defineExpose({
  editorRef,
  terminalRef,
})
</script>

<template>
  <SplitPane
    v-if="ideStore.showTerminal"
    :direction="terminalSplitConfig.direction"
    :initial-size="ideStore.terminalSize"
    :min-size="terminalSplitConfig.minSize"
    :max-size="terminalSplitConfig.maxSize"
    :storage-key="terminalSplitConfig.storageKey"
    :reverse="true"
    @update:size="ideStore.setTerminalSize">
    <template #first>
      <EditorPane ref="editorRef" />
    </template>
    <template #second>
      <TerminalPane
        ref="terminalRef"
        :task-id="taskId"
        :type="type"
        :container-name="containerName"
        @connected="handleTerminalConnected"
        @disconnected="handleTerminalDisconnected" />
    </template>
  </SplitPane>
  <EditorPane
    v-else
    ref="editorRef" />
</template>
