<template>
  <div>
    <!-- Directory node -->
    <div
      v-if="node.type === 'dir'"
      class="mb-0.5">
      <button
        :class="isAncestor ? 'sidebar-item-ancestor' : 'sidebar-item-idle'"
        @click="toggleExpand">
        <div
          :class="expanded ? 'i-carbon-chevron-down' : 'i-carbon-chevron-right'"
          class="w-3 h-3 shrink-0 text-blue-500 dark:text-blue-400" />
        <span class="truncate">{{ node.label }}</span>
      </button>
      <div
        v-show="expanded"
        class="sidebar-branch">
        <SidebarNode
          v-for="child in node.children"
          :key="child.path"
          :node="child"
          :current-path="currentPath"
          :depth="depth + 1" />
      </div>
    </div>

    <!-- File node -->
    <router-link
      v-else
      :to="node.path"
      class="mb-0.5"
      :class="isActive ? 'sidebar-item-active' : 'sidebar-item-idle'">
      <div class="w-3 h-3 shrink-0" />
      <span class="truncate">{{ node.label }}</span>
    </router-link>
  </div>
</template>

<script setup>
const props = defineProps({
  node: { type: Object, required: true },
  currentPath: { type: String, default: '' },
  depth: { type: Number, default: 0 },
})

const isActive = computed(() => props.currentPath === props.node.path)
const isAncestor = computed(() => props.currentPath.startsWith(props.node.path + '/'))

const expanded = ref(isAncestor.value || isActive.value)

watch(
  () => props.currentPath,
  () => {
    if (isAncestor.value || isActive.value) {
      expanded.value = true
    }
  }
)

function toggleExpand() {
  expanded.value = !expanded.value
}
</script>
