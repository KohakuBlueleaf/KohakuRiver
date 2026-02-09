<template>
  <div class="container-doc py-12">
    <h1 class="text-3xl font-bold mb-2">Documentation</h1>
    <p class="text-gray-600 dark:text-gray-400 mb-8">Browse the {{ siteConfig.name }} documentation by section.</p>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
      <router-link
        v-for="section in siteConfig.sections"
        :key="section.key"
        :to="`/docs/${section.key}`"
        class="doc-card group text-center">
        <div
          :class="[section.icon, section.color]"
          class="text-5xl mx-auto mb-4" />
        <h2 class="text-xl font-bold mb-2 group-hover:text-blue-600 dark:group-hover:text-blue-400">
          {{ section.title }}
        </h2>
        <p class="text-sm text-gray-600 dark:text-gray-400">{{ section.description }}</p>
      </router-link>
    </div>
  </div>
</template>

<script setup>
import siteConfig from '../../../site.config.js'
</script>
