<script setup>
import { useDocTree } from '@/framework/composables/useDocTree.js'
import DocLayout from '@/framework/components/DocLayout.vue'
import DocCardGrid from '@/framework/components/DocCardGrid.vue'
import MarkdownPage from '@/framework/components/MarkdownPage.vue'
import siteConfig from '../../../site.config.js'

const route = useRoute()
const { tree, loading: treeLoading, load: loadTree, getSection, getAdjacentPages } = useDocTree()

const content = ref('')
const isDirectory = ref(false)
const dirChildren = ref([])
const docLoading = ref(true)

const currentPath = computed(() => route.path)

const sectionTree = computed(() => {
  if (!tree.value) return null
  return getSection(route.path)
})

const adjacentPages = computed(() => {
  if (!tree.value || isDirectory.value) return { prev: null, next: null }
  return getAdjacentPages(route.path)
})

function parseFrontmatter(markdown) {
  const match = markdown.match(/^---\s*\n([\s\S]*?)\n---\s*\n/)
  if (!match) return { title: null, description: null, icon: null }
  const meta = {}
  for (const line of match[1].split('\n')) {
    const [key, ...parts] = line.split(':')
    if (key && parts.length) meta[key.trim()] = parts.join(':').trim()
  }
  return { title: meta.title || null, description: meta.description || null, icon: meta.icon || null }
}

async function loadDoc() {
  docLoading.value = true
  const pathSegments = route.path.split('/').filter(Boolean)

  // /docs root — show section cards from site.config
  if (pathSegments.length === 1 && pathSegments[0] === 'docs') {
    isDirectory.value = true
    dirChildren.value = siteConfig.sections.map((s) => ({
      path: `/docs/${s.key}`,
      label: s.title,
      description: s.description,
      icon: s.icon,
    }))
    docLoading.value = false
    return
  }

  const docPath = pathSegments.slice(1).join('/')

  try {
    // Try as markdown file
    const fileRes = await fetch(`/documentation/${docPath}.md`)
    if (fileRes.ok) {
      const text = await fileRes.text()
      if (!text.trim().startsWith('<!')) {
        content.value = text
        isDirectory.value = false
        docLoading.value = false
        return
      }
    }

    // Try as directory
    const manifestRes = await fetch(`/documentation/${docPath}/.manifest.json`)
    if (manifestRes.ok) {
      const manifestText = await manifestRes.text()
      if (!manifestText.trim().startsWith('<!')) {
        const manifest = JSON.parse(manifestText)
        const children = []

        // Subdirectories
        if (manifest.dirs) {
          for (const dir of manifest.dirs) {
            children.push({
              path: `/docs/${docPath}/${dir}`,
              label: dir.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
              description: '',
              icon: 'i-carbon-folder',
              type: 'dir',
            })
          }
        }

        // Files — fetch frontmatter
        if (manifest.files) {
          const fileNodes = await Promise.all(
            manifest.files.map(async (filename) => {
              try {
                const res = await fetch(`/documentation/${docPath}/${filename}`)
                const text = await res.text()
                if (text.trim().startsWith('<!')) return null
                const meta = parseFrontmatter(text)
                return {
                  path: `/docs/${docPath}/${filename.replace(/\.md$/, '')}`,
                  label:
                    meta.title ||
                    filename
                      .replace(/\.md$/, '')
                      .replace(/-/g, ' ')
                      .replace(/\b\w/g, (c) => c.toUpperCase()),
                  description: meta.description || '',
                  icon: meta.icon || 'i-carbon-document',
                  type: 'file',
                }
              } catch {
                return null
              }
            })
          )
          children.push(...fileNodes.filter(Boolean))
        }

        dirChildren.value = children
        isDirectory.value = true
        docLoading.value = false
        return
      }
    }

    // Not found
    content.value = '# Not Found\n\nThis documentation page does not exist yet.'
    isDirectory.value = false
  } catch (e) {
    content.value = `# Error\n\n${e.message}`
    isDirectory.value = false
  }

  docLoading.value = false
}

// Load tree + doc
onMounted(() => {
  loadTree()
  loadDoc()
})

watch(
  () => route.path,
  () => {
    loadDoc()
    window.scrollTo({ top: 0, behavior: 'instant' })
  }
)
</script>

<template>
  <div
    v-if="docLoading && treeLoading"
    class="flex items-center justify-center py-24">
    <div class="i-carbon-circle-dash animate-spin text-4xl text-gray-400" />
  </div>

  <DocLayout
    v-else
    :section-tree="sectionTree"
    :current-path="currentPath"
    :loading="treeLoading">
    <!-- Directory listing -->
    <DocCardGrid
      v-if="isDirectory"
      :title="
        route.path
          .split('/')
          .filter(Boolean)
          .pop()
          ?.replace(/-/g, ' ')
          .replace(/\b\w/g, (c) => c.toUpperCase()) || 'Documentation'
      "
      :items="dirChildren" />

    <!-- Markdown content + prev/next nav -->
    <template v-else>
      <MarkdownPage :content="content" />

      <!-- Previous / Next navigation -->
      <nav
        v-if="adjacentPages.prev || adjacentPages.next"
        class="flex flex-col sm:flex-row items-stretch gap-3 sm:gap-4 mt-8 sm:mt-12 pt-6 border-t border-gray-200 dark:border-gray-700">
        <router-link
          v-if="adjacentPages.prev"
          :to="adjacentPages.prev.path"
          class="doc-nav-link group">
          <span class="text-xs text-gray-500 dark:text-gray-400">Previous</span>
          <span
            class="text-blue-600 dark:text-blue-400 group-hover:text-blue-700 dark:group-hover:text-blue-300 font-medium">
            &larr; {{ adjacentPages.prev.label }}
          </span>
        </router-link>

        <div
          v-else
          class="flex-1" />

        <router-link
          v-if="adjacentPages.next"
          :to="adjacentPages.next.path"
          class="doc-nav-link group text-right">
          <span class="text-xs text-gray-500 dark:text-gray-400">Next</span>
          <span
            class="text-blue-600 dark:text-blue-400 group-hover:text-blue-700 dark:group-hover:text-blue-300 font-medium">
            {{ adjacentPages.next.label }} &rarr;
          </span>
        </router-link>
      </nav>
    </template>
  </DocLayout>
</template>
