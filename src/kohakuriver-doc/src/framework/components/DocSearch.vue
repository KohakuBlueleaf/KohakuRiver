<template>
  <Teleport to="body">
    <Transition name="search-fade">
      <div
        v-if="visible"
        class="fixed inset-0 z-50 flex items-start justify-center pt-[10vh]"
        @mousedown.self="close">
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-black/50 backdrop-blur-sm" />

        <!-- Modal -->
        <div
          ref="modalRef"
          class="relative w-full max-w-xl mx-4 bg-white dark:bg-gray-800 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          <!-- Search input -->
          <div class="flex items-center border-b border-gray-200 dark:border-gray-700 px-4">
            <div class="i-carbon-search text-gray-400 mr-3 text-lg shrink-0" />
            <input
              ref="inputRef"
              v-model="query"
              type="text"
              placeholder="Search documentation..."
              class="w-full py-3.5 bg-transparent text-gray-900 dark:text-white placeholder-gray-400 outline-none text-base"
              @keydown.escape="close"
              @keydown.down.prevent="moveSelection(1)"
              @keydown.up.prevent="moveSelection(-1)"
              @keydown.enter.prevent="navigateToSelected" />
            <kbd
              class="shrink-0 ml-2 px-1.5 py-0.5 text-xs text-gray-400 border border-gray-300 dark:border-gray-600 rounded">
              Esc
            </kbd>
          </div>

          <!-- Results -->
          <div class="max-h-80 overflow-y-auto overscroll-contain">
            <div
              v-if="!searchReady"
              class="px-4 py-8 text-center text-gray-400 text-sm">
              Loading search index...
            </div>
            <div
              v-else-if="query && !results.length"
              class="px-4 py-8 text-center text-gray-400 text-sm">
              No results for "{{ query }}"
            </div>
            <div
              v-else-if="!query"
              class="px-4 py-8 text-center text-gray-400 text-sm">
              Type to search across all documentation
            </div>
            <template v-else>
              <button
                v-for="(result, i) in results"
                :key="result.id"
                :ref="(el) => (itemRefs[i] = el)"
                class="w-full text-left px-4 py-3 flex items-start gap-3 border-b border-gray-100 dark:border-gray-700/50 last:border-0 transition-colors"
                :class="
                  i === selectedIndex ? 'bg-blue-50 dark:bg-blue-900/30' : 'hover:bg-gray-50 dark:hover:bg-gray-700/50'
                "
                @click="navigateTo(result)"
                @mouseenter="selectedIndex = i">
                <div class="i-carbon-document text-gray-400 mt-0.5 shrink-0" />
                <div class="min-w-0">
                  <div class="text-sm font-medium text-gray-900 dark:text-white truncate">
                    {{ result.title }}
                  </div>
                  <div
                    v-if="result.description"
                    class="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5">
                    {{ result.description }}
                  </div>
                  <div class="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                    {{ formatSection(result.section) }}
                  </div>
                </div>
              </button>
            </template>
          </div>

          <!-- Footer hint -->
          <div
            v-if="results.length"
            class="px-4 py-2 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/80 text-xs text-gray-400 flex gap-4">
            <span>
              <kbd class="px-1 border border-gray-300 dark:border-gray-600 rounded">↑↓</kbd>
              navigate
            </span>
            <span>
              <kbd class="px-1 border border-gray-300 dark:border-gray-600 rounded">↵</kbd>
              open
            </span>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { useSearch } from '@/framework/composables/useSearch.js'

const { init, search, ready: searchReady } = useSearch()

const visible = ref(false)
const query = ref('')
const selectedIndex = ref(0)
const inputRef = ref(null)
const modalRef = ref(null)
const itemRefs = ref([])

const router = useRouter()

const results = computed(() => search(query.value))

watch(query, () => {
  selectedIndex.value = 0
})

function open() {
  visible.value = true
  query.value = ''
  selectedIndex.value = 0
  init()
  nextTick(() => inputRef.value?.focus())
}

function close() {
  visible.value = false
}

function moveSelection(delta) {
  if (!results.value.length) return
  selectedIndex.value = (selectedIndex.value + delta + results.value.length) % results.value.length
  nextTick(() => itemRefs.value[selectedIndex.value]?.scrollIntoView?.({ block: 'nearest' }))
}

function navigateToSelected() {
  const result = results.value[selectedIndex.value]
  if (result) navigateTo(result)
}

function navigateTo(result) {
  close()
  router.push(result.path)
}

const sectionLabels = {
  guide: 'User Guide',
  dev: 'Developer Guide',
  'tech-report': 'Technical Report',
}

function formatSection(key) {
  return sectionLabels[key] || key
}

// Global keyboard shortcut
function handleGlobalKeydown(e) {
  // Ctrl+K or Cmd+K
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault()
    if (visible.value) close()
    else open()
  }
}

onMounted(() => {
  document.addEventListener('keydown', handleGlobalKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleGlobalKeydown)
})

defineExpose({ open, close })
</script>

<style scoped>
.search-fade-enter-active,
.search-fade-leave-active {
  transition: opacity 0.15s ease;
}

.search-fade-enter-from,
.search-fade-leave-to {
  opacity: 0;
}
</style>
