---
title: Frontend Conventions
description: JavaScript-only policy, Vue 3 Composition API patterns, and Element Plus usage
icon: i-carbon-paint-brush
---

# Frontend Conventions

This document covers coding conventions for both frontend applications: the Manager dashboard (`src/kohakuriver-manager/`) and the Documentation site (`src/kohakuriver-doc/`).

## JavaScript Only -- No TypeScript

The project uses **JavaScript exclusively**. This is a firm convention. When type information is needed, use JSDoc annotations:

```javascript
/**
 * @param {string} taskId - The task identifier
 * @returns {Promise<import('axios').AxiosResponse>}
 */
async function getTask(taskId) {
  return client.get(`/api/tasks/${taskId}`)
}
```

Do not add `.ts` files, `tsconfig.json`, or TypeScript-related dependencies.

## Vue 3 Composition API

All components use `<script setup>` syntax. The Options API is not used.

### Component Template

```vue
<template>
  <div class="my-component">
    <el-button @click="handleAction">{{ label }}</el-button>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'

const props = defineProps({
  taskId: { type: String, required: true },
})

const emit = defineEmits(['update'])

const loading = ref(false)
const label = computed(() => (loading.value ? 'Loading...' : 'Submit'))

async function handleAction() {
  loading.value = true
  try {
    // ...
    emit('update')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  // Initialization
})
</script>
```

### Auto-Imports

Both projects use `unplugin-auto-import` to auto-import Vue, Pinia, and vue-router APIs. You do not need to explicitly import `ref`, `computed`, `watch`, `onMounted`, etc.

```vue
<script setup>
// These are auto-imported -- no import statement needed
const count = ref(0)
const doubled = computed(() => count.value * 2)
</script>
```

## Element Plus

UI components come from [Element Plus](https://element-plus.org/). They are auto-registered via `unplugin-vue-components` with the `ElementPlusResolver`.

### Commonly Used Components

| Component                  | Usage                              |
| -------------------------- | ---------------------------------- |
| `el-button`                | Actions, submit buttons            |
| `el-table`                 | Data tables with sorting/filtering |
| `el-dialog`                | Modal dialogs                      |
| `el-form` + `el-form-item` | Form layouts with validation       |
| `el-select`                | Dropdown selectors                 |
| `el-tag`                   | Status badges, labels              |
| `el-card`                  | Content cards (VPS instances)      |
| `el-tabs`                  | Tabbed interfaces                  |
| `el-message`               | Toast notifications                |
| `el-loading`               | Loading indicators                 |

### Dark Mode

Element Plus dark mode is enabled via CSS variables:

```javascript
import 'element-plus/theme-chalk/dark/css-vars.css'
```

The `useUIStore` manages theme toggling.

## Pinia Store Pattern

Stores use the Composition API syntax with `defineStore`:

```javascript
import { defineStore } from 'pinia'

export const useTasksStore = defineStore('tasks', () => {
  // State
  const taskList = ref([])
  const loading = ref(false)

  // Getters
  const runningTasks = computed(() => taskList.value.filter((t) => t.status === 'running'))

  // Actions
  async function fetchTasks() {
    loading.value = true
    try {
      const { data } = await tasksAPI.list()
      taskList.value = data
    } finally {
      loading.value = false
    }
  }

  return { taskList, loading, runningTasks, fetchTasks }
})
```

### Loading State

For long operations, use the global loading store:

```javascript
const loadingStore = useLoadingStore()
const opId = `create-vps-${Date.now()}`
loadingStore.startLoading(opId, 'Creating VPS instance...')
try {
  await vpsAPI.create(data)
} finally {
  loadingStore.stopLoading(opId)
}
```

## API Client Pattern

All API calls go through the Axios client in `utils/api/client.js`. Domain modules export objects with method functions:

```javascript
export const vpsAPI = {
  list: () => client.get('/api/vps'),
  create: (data) => client.post('/api/vps', data),
  stop: (id) => client.post(`/api/vps/${id}/stop`),
}
```

## File-Based Routing

Pages in `src/pages/` map to routes automatically:

| File                    | Route    |
| ----------------------- | -------- |
| `pages/index.vue`       | `/`      |
| `pages/tasks/index.vue` | `/tasks` |
| `pages/vps/index.vue`   | `/vps`   |
| `pages/admin/index.vue` | `/admin` |

Sub-components that should NOT become routes live in `components/` subdirectories within each page folder (e.g., `pages/tasks/components/TaskDetailDialog.vue`).

## CSS / Styling

Both projects use **UnoCSS** for utility classes. Write styles inline in templates:

```html
<div class="flex items-center gap-2 p-4 bg-gray-100 dark:bg-gray-800"></div>
```

For component-scoped styles, use `<style scoped>`.

## Code Formatting

Prettier is configured for consistent formatting:

```bash
npm run format
```

This formats all `.js`, `.vue`, `.css`, and `.json` files.
