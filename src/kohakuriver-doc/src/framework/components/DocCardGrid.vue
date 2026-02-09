<template>
  <div>
    <h1 class="text-3xl font-bold mb-2">{{ title }}</h1>
    <p
      v-if="description"
      class="text-gray-600 dark:text-gray-400 mb-8">
      {{ description }}
    </p>

    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <router-link
        v-for="item in items"
        :key="item.path"
        :to="item.path"
        class="doc-card group">
        <div class="flex items-start gap-3">
          <div
            :class="item.icon || 'i-carbon-document'"
            class="text-2xl text-blue-600 dark:text-blue-400 shrink-0 mt-0.5" />
          <div>
            <h3
              class="font-semibold text-gray-900 dark:text-gray-100 group-hover:text-blue-600 dark:group-hover:text-blue-400 mb-1">
              {{ item.label }}
            </h3>
            <p
              v-if="item.description"
              class="text-sm text-gray-500 dark:text-gray-400 line-clamp-2">
              {{ item.description }}
            </p>
          </div>
        </div>
      </router-link>
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  items: { type: Array, default: () => [] },
})
</script>
