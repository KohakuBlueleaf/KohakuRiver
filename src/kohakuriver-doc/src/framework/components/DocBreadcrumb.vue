<template>
  <nav
    v-if="crumbs.length > 0"
    class="flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400 mb-6">
    <router-link
      to="/docs"
      class="hover:text-blue-600 dark:hover:text-blue-400">
      Docs
    </router-link>
    <template
      v-for="(crumb, i) in crumbs"
      :key="crumb.path">
      <div class="i-carbon-chevron-right w-3 h-3 mx-1" />
      <router-link
        v-if="i < crumbs.length - 1"
        :to="crumb.path"
        class="hover:text-blue-600 dark:hover:text-blue-400">
        {{ crumb.label }}
      </router-link>
      <span
        v-else
        class="text-gray-900 dark:text-gray-100 font-medium">
        {{ crumb.label }}
      </span>
    </template>
  </nav>
</template>

<script setup>
const props = defineProps({
  path: { type: String, default: '' },
})

const crumbs = computed(() => {
  const segments = props.path
    .replace(/^\/docs\/?/, '')
    .split('/')
    .filter(Boolean)
  return segments.map((seg, i) => ({
    label: seg.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
    path: '/docs/' + segments.slice(0, i + 1).join('/'),
  }))
})
</script>
