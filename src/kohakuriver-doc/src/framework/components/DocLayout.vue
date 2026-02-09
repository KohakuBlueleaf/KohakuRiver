<template>
  <div class="flex min-h-[calc(100vh-3.5rem)]">
    <!-- Mobile sidebar toggle -->
    <button
      class="fixed bottom-4 right-4 z-50 lg:hidden w-12 h-12 rounded-full bg-blue-600 text-white shadow-lg flex items-center justify-center active:scale-95 transition-transform"
      @click="sidebarOpen = !sidebarOpen">
      <div
        :class="sidebarOpen ? 'i-carbon-close' : 'i-carbon-menu'"
        class="text-xl" />
    </button>

    <!-- Sidebar overlay (mobile) -->
    <Transition name="sidebar-backdrop">
      <div
        v-if="sidebarOpen"
        class="fixed inset-0 bg-black/40 z-30 lg:hidden"
        @click="sidebarOpen = false" />
    </Transition>

    <!-- Sidebar: fixed positioning so footer can never push it -->
    <div
      class="doc-sidebar-mobile fixed top-14 left-0 h-[calc(100vh-3.5rem)] transition-transform duration-200 ease-out lg:translate-x-0 lg:w-64 lg:shadow-none"
      :class="[sidebarOpen ? 'translate-x-0 z-40' : '-translate-x-full lg:translate-x-0 z-20']">
      <DocSidebar
        :section-tree="sectionTree"
        :current-path="currentPath"
        :loading="loading" />
    </div>

    <!-- Content area: left margin matches sidebar width on desktop -->
    <div class="doc-content lg:ml-64">
      <DocBreadcrumb :path="currentPath" />
      <slot />
    </div>
  </div>
</template>

<script setup>
import DocSidebar from './DocSidebar.vue'
import DocBreadcrumb from './DocBreadcrumb.vue'

defineProps({
  sectionTree: { type: Object, default: null },
  currentPath: { type: String, default: '' },
  loading: { type: Boolean, default: false },
})

const sidebarOpen = ref(false)
const route = useRoute()

watch(
  () => route.path,
  () => {
    sidebarOpen.value = false
  }
)
</script>

<style scoped>
.sidebar-backdrop-enter-active,
.sidebar-backdrop-leave-active {
  transition: opacity 0.2s ease;
}

.sidebar-backdrop-enter-from,
.sidebar-backdrop-leave-to {
  opacity: 0;
}
</style>
