<template>
  <article class="max-w-4xl">
    <MarkdownViewer :content="content" />
  </article>
</template>

<script setup>
import MarkdownViewer from '@/framework/components/MarkdownViewer.vue'

defineProps({
  content: { type: String, required: true },
})
</script>

<style scoped>
article :deep(.markdown-body h1:first-child) {
  margin-top: 0;
}
</style>
