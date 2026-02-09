<template>
  <header
    class="sticky top-0 z-30 bg-white/80 dark:bg-gray-800/80 backdrop-blur border-b border-gray-200 dark:border-gray-700">
    <div class="container-doc flex items-center justify-between h-14">
      <!-- Logo / Home -->
      <router-link
        to="/"
        class="flex items-center gap-2 font-bold text-lg text-gray-900 dark:text-white hover:opacity-80">
        <div class="i-carbon-flow text-blue-600 dark:text-blue-400 text-xl" />
        <span>{{ siteConfig.name }}</span>
      </router-link>

      <!-- Nav -->
      <nav class="flex items-center gap-4">
        <!-- Search trigger -->
        <button
          class="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-400 bg-gray-100 dark:bg-gray-700/60 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600/60 transition-colors"
          @click="searchRef?.open()">
          <div class="i-carbon-search text-sm" />
          <span class="hidden sm:inline">Search</span>
          <kbd class="hidden sm:inline text-xs text-gray-400 ml-1">{{ shortcutKey }}K</kbd>
        </button>

        <router-link
          to="/docs"
          class="text-sm text-gray-600 dark:text-gray-300 hover:text-blue-600 dark:hover:text-blue-400">
          Documentation
        </router-link>
        <a
          v-if="siteConfig.links?.github"
          :href="siteConfig.links.github"
          target="_blank"
          rel="noopener"
          class="text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white">
          <div class="i-carbon-logo-github text-xl" />
        </a>
        <button
          class="text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white p-1"
          title="Toggle dark mode"
          @click="themeStore.toggle()">
          <div
            :class="themeStore.isDark ? 'i-carbon-sun' : 'i-carbon-moon'"
            class="text-lg" />
        </button>
      </nav>
    </div>
  </header>

  <DocSearch ref="searchRef" />
</template>

<script setup>
import siteConfig from '../../../site.config.js'
import { useThemeStore } from '@/stores/theme'
import DocSearch from '@/framework/components/DocSearch.vue'

const themeStore = useThemeStore()
const searchRef = ref(null)
const shortcutKey = navigator.platform?.includes('Mac') ? '\u2318' : 'Ctrl+'
</script>
