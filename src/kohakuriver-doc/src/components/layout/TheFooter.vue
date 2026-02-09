<template>
  <footer class="border-t border-gray-200 dark:border-gray-700 py-8 mt-auto">
    <div class="container-doc text-center text-sm text-gray-500 dark:text-gray-400">
      <p>{{ siteConfig.name }} &mdash; Self-hosted cluster manager</p>
      <div class="flex items-center justify-center gap-4 mt-2">
        <a
          v-if="siteConfig.links?.github"
          :href="siteConfig.links.github"
          target="_blank"
          rel="noopener"
          class="hover:text-gray-900 dark:hover:text-white">
          GitHub
        </a>
        <router-link
          to="/docs"
          class="hover:text-gray-900 dark:hover:text-white">
          Documentation
        </router-link>
      </div>
    </div>
  </footer>
</template>

<script setup>
import siteConfig from '../../../site.config.js'
</script>
