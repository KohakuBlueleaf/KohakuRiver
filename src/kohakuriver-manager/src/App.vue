<script setup>
import { useUIStore } from '@/stores/ui'
import TheSidebar from '@/components/layout/TheSidebar.vue'
import GlobalLoading from '@/components/common/GlobalLoading.vue'

const route = useRoute()
const uiStore = useUIStore()

// Check if current route is an auth page (no sidebar layout)
const isAuthPage = computed(() => {
  return ['/login', '/register'].includes(route.path)
})

// Initialize UI store on mount
onMounted(() => {
  uiStore.init()
})
</script>

<template>
  <!-- Auth pages (login/register) - full page without sidebar -->
  <div
    v-if="isAuthPage"
    class="h-screen overflow-auto bg-app-page">
    <router-view v-slot="{ Component, route }">
      <component
        :is="Component"
        :key="route.path" />
    </router-view>
    <GlobalLoading />
  </div>

  <!-- Normal layout with sidebar -->
  <div
    v-else
    class="app-root h-screen overflow-hidden bg-app-page">
    <!-- Sidebar -->
    <TheSidebar />

    <!-- Main Content Area -->
    <div
      class="main-container h-screen transition-all duration-300"
      :class="[uiStore.isMobile ? 'ml-0' : uiStore.sidebarCollapsed ? 'ml-16' : 'ml-64']">
      <!-- Page Content -->
      <main class="main-content h-full overflow-auto p-4 md:p-6">
        <router-view v-slot="{ Component, route }">
          <component
            :is="Component"
            :key="route.path" />
        </router-view>
      </main>
    </div>

    <!-- Global Loading Indicator -->
    <GlobalLoading />
  </div>
</template>
