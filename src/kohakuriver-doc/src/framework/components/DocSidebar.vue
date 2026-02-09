<template>
  <aside class="doc-sidebar py-4 px-3">
    <div
      v-if="loading"
      class="text-center py-8">
      <div class="i-carbon-circle-dash animate-spin text-xl text-gray-400" />
    </div>

    <template v-else-if="sectionTree">
      <div class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3 px-2">
        {{ sectionTree.label }}
      </div>
      <SidebarNode
        v-for="child in sectionTree.children"
        :key="child.path"
        :node="child"
        :current-path="currentPath"
        :depth="0" />
    </template>
  </aside>
</template>

<script setup>
import SidebarNode from './SidebarNode.vue'

defineProps({
  sectionTree: { type: Object, default: null },
  currentPath: { type: String, default: '' },
  loading: { type: Boolean, default: false },
})
</script>
