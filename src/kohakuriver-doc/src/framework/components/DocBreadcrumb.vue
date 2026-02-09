<template>
  <nav
    v-if="crumbs.length > 0"
    class="flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400 mb-4 sm:mb-6 overflow-x-auto scrollbar-hide whitespace-nowrap -mx-4 px-4 sm:mx-0 sm:px-0">
    <router-link
      to="/docs"
      class="hover:text-blue-600 dark:hover:text-blue-400 shrink-0">
      Docs
    </router-link>
    <template
      v-for="(crumb, i) in crumbs"
      :key="crumb.path">
      <div class="i-carbon-chevron-right w-3 h-3 mx-1 shrink-0" />
      <router-link
        v-if="i < crumbs.length - 1"
        :to="crumb.path"
        class="hover:text-blue-600 dark:hover:text-blue-400 shrink-0">
        {{ crumb.label }}
      </router-link>
      <span
        v-else
        class="text-gray-900 dark:text-gray-100 font-medium shrink-0">
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
