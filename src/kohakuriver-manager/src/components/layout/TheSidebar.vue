<script setup>
import { useUIStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const uiStore = useUIStore()
const authStore = useAuthStore()

// Menu items with role requirements
// role: minimum role required to see this item
const allMenuItems = [
  { path: '/', icon: 'i-carbon-dashboard', label: 'Dashboard', role: 'anony' },
  { path: '/nodes', icon: 'i-carbon-bare-metal-server', label: 'Nodes', role: 'viewer' },
  { path: '/gpu', icon: 'i-carbon-chip', label: 'GPUs', role: 'viewer' },
  { path: '/tasks', icon: 'i-carbon-task', label: 'Tasks', role: 'viewer' },
  { path: '/vps', icon: 'i-carbon-virtual-machine', label: 'VPS', role: 'viewer' },
  { path: '/docker', icon: 'i-carbon-container-software', label: 'Docker', role: 'operator' },
  { path: '/stats', icon: 'i-carbon-chart-line', label: 'Statistics', role: 'viewer' },
  { path: '/admin', icon: 'i-carbon-user-admin', label: 'Admin', role: 'operator' },
]

const menuItems = computed(() => {
  return allMenuItems.filter((item) => authStore.hasRole(item.role))
})

async function handleLogout() {
  await authStore.logout()
  router.push('/login')
}

function handleLogin() {
  router.push('/login')
}

const isAnonymous = computed(() => authStore.role === 'anony')

const themeOptions = [
  { value: 'light', icon: 'i-carbon-sun' },
  { value: 'dark', icon: 'i-carbon-moon' },
  { value: 'system', icon: 'i-carbon-laptop' },
]

const currentThemeIcon = computed(() => {
  const option = themeOptions.find((o) => o.value === uiStore.theme)
  return option?.icon || 'i-carbon-laptop'
})

function cycleTheme() {
  const currentIndex = themeOptions.findIndex((o) => o.value === uiStore.theme)
  const nextIndex = (currentIndex + 1) % themeOptions.length
  uiStore.setTheme(themeOptions[nextIndex].value)
}

const isActive = (path) => {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

function navigateTo(path) {
  router.push(path)
  // Close mobile menu on navigation
  if (uiStore.isMobile) {
    uiStore.closeMobileMenu()
  }
}

function refresh() {
  router.go(0)
}
</script>

<template>
  <!-- Mobile Overlay -->
  <Transition name="fade">
    <div
      v-if="uiStore.isMobile && uiStore.mobileMenuOpen"
      class="fixed inset-0 bg-black/50 z-40 md:hidden"
      @click="uiStore.closeMobileMenu"></div>
  </Transition>

  <!-- Sidebar -->
  <aside
    class="fixed left-0 top-0 h-screen bg-app-sidebar text-gray-100 transition-all duration-300 z-50 flex flex-col"
    :class="[
      uiStore.isMobile
        ? uiStore.mobileMenuOpen
          ? 'translate-x-0 w-64'
          : '-translate-x-full w-64'
        : uiStore.sidebarCollapsed
          ? 'w-16'
          : 'w-64',
    ]">
    <!-- Logo -->
    <div class="h-16 flex items-center justify-between px-4 border-b border-gray-800">
      <div class="flex items-center gap-3">
        <img
          src="/favicon.svg"
          alt="KohakuRiver"
          class="w-8 h-8 flex-shrink-0" />
        <span
          v-if="!uiStore.sidebarCollapsed || uiStore.isMobile"
          class="font-semibold text-lg">
          KohakuRiver
        </span>
      </div>
      <!-- Close button for mobile -->
      <button
        v-if="uiStore.isMobile"
        @click="uiStore.closeMobileMenu"
        class="p-1 rounded hover:bg-gray-800">
        <span class="i-carbon-close text-xl"></span>
      </button>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 py-4 overflow-y-auto">
      <ul class="space-y-1 px-2">
        <li
          v-for="item in menuItems"
          :key="item.path">
          <button
            @click="navigateTo(item.path)"
            class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors"
            :class="
              isActive(item.path) ? 'bg-blue-600 text-white' : 'text-gray-400 hover:bg-gray-800 hover:text-white'
            ">
            <span
              :class="item.icon"
              class="text-xl flex-shrink-0"></span>
            <span
              v-if="!uiStore.sidebarCollapsed || uiStore.isMobile"
              class="truncate">
              {{ item.label }}
            </span>
          </button>
        </li>
      </ul>
    </nav>

    <!-- Footer -->
    <div class="p-3 border-t border-gray-800 space-y-2">
      <!-- User info (when auth enabled) -->
      <div
        v-if="authStore.authEnabled"
        class="px-2 py-2 text-sm">
        <!-- Show user info only if logged in (not anonymous) -->
        <div
          v-if="!isAnonymous && (!uiStore.sidebarCollapsed || uiStore.isMobile)"
          class="flex items-center gap-2 text-gray-300 mb-2">
          <span class="i-carbon-user text-lg"></span>
          <span class="truncate">{{ authStore.displayName }}</span>
          <span class="text-xs text-gray-500">({{ authStore.role }})</span>
        </div>
        <!-- Login button for anonymous -->
        <button
          v-if="isAnonymous"
          @click="handleLogin"
          class="w-full flex items-center justify-center gap-2 px-3 py-1.5 rounded-lg text-gray-400 hover:bg-gray-700 hover:text-white transition-colors text-sm"
          :title="uiStore.sidebarCollapsed && !uiStore.isMobile ? 'Login' : ''">
          <span class="i-carbon-login text-lg"></span>
          <span v-if="!uiStore.sidebarCollapsed || uiStore.isMobile">Login</span>
        </button>
        <!-- Logout button for authenticated users -->
        <button
          v-else
          @click="handleLogout"
          class="w-full flex items-center justify-center gap-2 px-3 py-1.5 rounded-lg text-gray-400 hover:bg-gray-700 hover:text-white transition-colors text-sm"
          :title="uiStore.sidebarCollapsed && !uiStore.isMobile ? 'Logout' : ''">
          <span class="i-carbon-logout text-lg"></span>
          <span v-if="!uiStore.sidebarCollapsed || uiStore.isMobile">Logout</span>
        </button>
      </div>

      <!-- Action buttons row -->
      <div class="flex items-center justify-center gap-2">
        <!-- Theme toggle -->
        <button
          @click="cycleTheme"
          class="flex items-center justify-center w-9 h-9 rounded-lg text-gray-400 hover:bg-gray-700 hover:text-white transition-colors"
          title="Toggle theme">
          <span
            :class="currentThemeIcon"
            class="text-lg"></span>
        </button>

        <!-- Refresh -->
        <button
          @click="refresh"
          class="flex items-center justify-center w-9 h-9 rounded-lg text-gray-400 hover:bg-gray-700 hover:text-white transition-colors"
          title="Refresh page">
          <span class="i-carbon-renew text-lg"></span>
        </button>
      </div>

      <!-- Collapse button - Desktop only -->
      <button
        v-if="!uiStore.isMobile"
        @click="uiStore.toggleSidebar"
        class="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-gray-400 hover:bg-gray-700 hover:text-white transition-colors">
        <span
          :class="uiStore.sidebarCollapsed ? 'i-carbon-chevron-right' : 'i-carbon-chevron-left'"
          class="text-lg"></span>
        <span v-if="!uiStore.sidebarCollapsed">Collapse</span>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
