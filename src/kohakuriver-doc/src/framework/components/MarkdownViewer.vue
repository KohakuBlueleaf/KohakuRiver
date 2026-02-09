<template>
  <div
    ref="markdownContainer"
    class="markdown-body markdown-container"
    v-html="renderedHTML" />
</template>

<script setup>
import { renderMarkdown } from '@/framework/utils/markdown.js'
import { useThemeStore } from '@/stores/theme'
import mermaid from 'mermaid'
import Panzoom from 'panzoom'

const themeStore = useThemeStore()

const props = defineProps({
  content: { type: String, default: '' },
  stripFrontmatter: { type: Boolean, default: true },
})

const markdownContainer = ref(null)
const renderedHTML = computed(() => renderMarkdown(props.content, { stripFrontmatter: props.stripFrontmatter }))
const isDark = computed(() => themeStore.isDark)

// Use Mermaid's built-in themes — they handle dark/light properly
const getMermaidConfig = (dark) => ({
  startOnLoad: false,
  securityLevel: 'loose',
  fontFamily: 'ui-sans-serif, system-ui, sans-serif',
  theme: dark ? 'dark' : 'default',
  logLevel: 'fatal',
})

mermaid.initialize(getMermaidConfig(isDark.value))

async function renderMermaidDiagrams() {
  await nextTick()
  if (!markdownContainer.value) return

  mermaid.initialize(getMermaidConfig(isDark.value))

  const mermaidBlocks = markdownContainer.value.querySelectorAll('pre code.language-mermaid')
  const existingWrappers = markdownContainer.value.querySelectorAll('.mermaid-wrapper')

  if (mermaidBlocks.length > 0) {
    for (let i = 0; i < mermaidBlocks.length; i++) {
      const block = mermaidBlocks[i]
      const code = block.textContent
      const pre = block.parentElement
      try {
        const wrapper = document.createElement('div')
        wrapper.className = 'mermaid-wrapper'
        wrapper.setAttribute('data-mermaid-code', code)
        pre.replaceWith(wrapper)
        await renderSingleDiagram(wrapper, code, i)
      } catch (err) {
        console.error('Mermaid rendering error:', err)
      }
    }
  } else if (existingWrappers.length > 0) {
    for (let i = 0; i < existingWrappers.length; i++) {
      const wrapper = existingWrappers[i]
      const code = wrapper.getAttribute('data-mermaid-code')
      if (code) {
        wrapper.querySelectorAll('.mermaid-diagram, .mermaid-controls').forEach((el) => el.remove())
        await renderSingleDiagram(wrapper, code, i)
      }
    }
  }
}

async function renderSingleDiagram(wrapper, code, index) {
  const id = `mermaid-${Date.now()}-${index}`
  const container = document.createElement('div')
  container.className = 'mermaid-diagram'
  container.id = id

  let svg
  try {
    const result = await mermaid.render(id, code)
    svg = result.svg
  } catch (err) {
    console.error('Mermaid render error:', err)
    container.innerHTML = `
      <div class="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded p-4 text-sm">
        <div class="font-semibold text-red-600 dark:text-red-400 mb-2">Diagram Syntax Error</div>
        <div class="text-red-700 dark:text-red-300 text-xs">This diagram has a syntax error and cannot be rendered.</div>
      </div>
    `
    wrapper.appendChild(container)
    return
  }

  container.innerHTML = svg
  const svgElement = container.querySelector('svg')
  if (svgElement) svgElement.style.backgroundColor = 'transparent'

  const controls = document.createElement('div')
  controls.className = 'mermaid-controls'
  controls.innerHTML = `
    <button class="mermaid-zoom-btn mermaid-zoom-in" title="Zoom In"><div class="i-carbon-zoom-in"></div></button>
    <button class="mermaid-zoom-btn mermaid-zoom-out" title="Zoom Out"><div class="i-carbon-zoom-out"></div></button>
    <button class="mermaid-zoom-btn mermaid-zoom-reset" title="Reset"><div class="i-carbon-zoom-reset"></div></button>
    <button class="mermaid-zoom-btn mermaid-fullscreen" title="Fullscreen"><div class="i-carbon-maximize"></div></button>
  `

  let panzoomInstance = null
  if (svgElement) {
    panzoomInstance = Panzoom(svgElement, { maxZoom: 3, minZoom: 0.3, bounds: false, boundsPadding: 0.1 })
    container.addEventListener('wheel', (e) => panzoomInstance.zoomWithWheel(e))
  }

  controls.querySelector('.mermaid-zoom-in').addEventListener('click', (e) => {
    e.stopPropagation()
    panzoomInstance?.zoomIn()
  })
  controls.querySelector('.mermaid-zoom-out').addEventListener('click', (e) => {
    e.stopPropagation()
    panzoomInstance?.zoomOut()
  })
  controls.querySelector('.mermaid-zoom-reset').addEventListener('click', (e) => {
    e.stopPropagation()
    if (panzoomInstance) {
      panzoomInstance.moveTo(0, 0)
      panzoomInstance.zoomAbs(0, 0, 1)
    }
  })
  controls.querySelector('.mermaid-fullscreen').addEventListener('click', (e) => {
    e.stopPropagation()
    if (!document.fullscreenElement) wrapper.requestFullscreen?.()
    else document.exitFullscreen?.()
  })

  wrapper.appendChild(controls)
  wrapper.appendChild(container)
}

watch(
  () => props.content,
  async () => {
    await nextTick()
    await renderMermaidDiagrams()
  },
  { flush: 'post' }
)

watch(isDark, (val) => {
  mermaid.initialize(getMermaidConfig(val))
  renderMermaidDiagrams()
})

onMounted(() => renderMermaidDiagrams())
</script>

<!-- UNSCOPED styles: v-html content has no scoped data attributes,
     so we use plain CSS with .markdown-body as namespace.
     This also makes .dark selector work without :global() hacks. -->
<style>
.markdown-container {
  max-width: 100%;
  overflow-x: auto;
}

.markdown-body {
  font-size: 15px;
  line-height: 1.7;
  word-wrap: break-word;
}

.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4,
.markdown-body h5,
.markdown-body h6 {
  margin-top: 24px;
  margin-bottom: 16px;
  font-weight: 600;
  line-height: 1.25;
}

.markdown-body h1 {
  font-size: 2em;
  border-bottom: 1px solid #eaecef;
  padding-bottom: 0.3em;
}

.markdown-body h2 {
  font-size: 1.5em;
  border-bottom: 1px solid #eaecef;
  padding-bottom: 0.3em;
}

.markdown-body h3 {
  font-size: 1.25em;
}

.markdown-body p {
  margin-top: 0;
  margin-bottom: 16px;
}

.markdown-body code {
  padding: 0.2em 0.4em;
  font-size: 85%;
  background-color: rgba(175, 184, 193, 0.2);
  border-radius: 6px;
  font-family: ui-monospace, 'Cascadia Code', 'Source Code Pro', Menlo, monospace;
}

.markdown-body pre {
  padding: 16px;
  overflow: auto;
  font-size: 85%;
  line-height: 1.45;
  background-color: #f6f8fa;
  border-radius: 6px;
  margin-bottom: 16px;
}

.markdown-body pre code,
.dark .markdown-body pre code {
  display: inline;
  padding: 0;
  margin: 0;
  overflow: visible;
  line-height: inherit;
  background-color: transparent;
  border: 0;
  font-size: inherit;
}

.markdown-body a {
  color: #0969da;
  text-decoration: none;
}

.markdown-body a:hover {
  text-decoration: underline;
}

.markdown-body ul,
.markdown-body ol {
  padding-left: 2em;
  margin-bottom: 16px;
  list-style: revert;
}

.markdown-body li {
  margin-bottom: 0.25em;
}

.markdown-body blockquote {
  padding: 0 1em;
  color: #57606a;
  border-left: 0.25em solid #d0d7de;
  margin-bottom: 16px;
}

.markdown-body table {
  border-collapse: collapse;
  width: 100%;
  margin-bottom: 16px;
}

.markdown-body table th,
.markdown-body table td {
  padding: 6px 13px;
  border: 1px solid #d0d7de;
}

.markdown-body table th {
  font-weight: 600;
  background-color: #f6f8fa;
}

.markdown-body img {
  max-width: 100%;
  height: auto;
}

.markdown-body hr {
  height: 0.25em;
  padding: 0;
  margin: 24px 0;
  background-color: #d0d7de;
  border: 0;
}

.markdown-body input[type='checkbox'].task-list-checkbox {
  margin-right: 0.5em;
  vertical-align: middle;
  pointer-events: none;
}

.markdown-body li:has(> input[type='checkbox'].task-list-checkbox) {
  list-style-type: none;
}

/* ===== Dark mode ===== */
.dark .markdown-body h1,
.dark .markdown-body h2 {
  border-bottom-color: rgba(255, 255, 255, 0.1);
}

.dark .markdown-body pre {
  background-color: rgba(0, 0, 0, 0.3);
}

.dark .markdown-body code {
  background-color: rgba(255, 255, 255, 0.1);
}

.dark .markdown-body table th {
  background-color: rgba(0, 0, 0, 0.3);
}

.dark .markdown-body table th,
.dark .markdown-body table td {
  border-color: rgba(255, 255, 255, 0.1);
}

.dark .markdown-body blockquote {
  color: #8b949e;
  border-left-color: rgba(255, 255, 255, 0.2);
}

.dark .markdown-body a {
  color: #58a6ff;
}

.dark .markdown-body hr {
  background-color: rgba(255, 255, 255, 0.1);
}

/* ===== Mermaid ===== */
.markdown-body .mermaid-wrapper {
  position: relative;
  margin: 24px 0;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
  background-color: #ffffff;
  overflow: hidden;
}

.dark .markdown-body .mermaid-wrapper {
  border-color: #374151;
  background-color: #1f2937;
}

.markdown-body .mermaid-wrapper svg {
  background: transparent !important;
}

.markdown-body .mermaid-wrapper:fullscreen {
  background-color: white;
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100vh;
  padding: 20px;
  align-items: center;
  justify-content: center;
}

.dark .markdown-body .mermaid-wrapper:fullscreen {
  background-color: #111827;
}

.markdown-body .mermaid-controls {
  position: absolute;
  top: 12px;
  right: 12px;
  display: flex;
  gap: 4px;
  z-index: 10;
  background-color: rgba(255, 255, 255, 0.95);
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 4px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.dark .markdown-body .mermaid-controls {
  background-color: rgba(31, 41, 55, 0.95);
  border-color: #4b5563;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.5);
}

.markdown-body .mermaid-zoom-btn {
  width: 32px;
  height: 32px;
  border: none;
  background-color: transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  color: #4b5563;
  transition: all 0.2s;
}

.markdown-body .mermaid-zoom-btn:hover {
  background-color: rgba(59, 130, 246, 0.15);
  color: #3b82f6;
}

.dark .markdown-body .mermaid-zoom-btn {
  color: #d1d5db;
}

.dark .markdown-body .mermaid-zoom-btn:hover {
  background-color: rgba(59, 130, 246, 0.3);
  color: #60a5fa;
}

.markdown-body .mermaid-zoom-btn div {
  width: 20px;
  height: 20px;
}

.markdown-body .mermaid-diagram {
  text-align: center;
  overflow: visible;
  min-height: 200px;
  max-height: 600px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: grab;
}

.markdown-body .mermaid-diagram:active {
  cursor: grabbing;
}

.markdown-body .mermaid-diagram svg {
  max-width: 100%;
  max-height: 600px;
  width: auto;
  height: auto;
}

.markdown-body .mermaid-wrapper:fullscreen .mermaid-diagram {
  max-height: none;
  max-width: none;
  width: 100%;
  height: 100%;
  flex: 1;
}
</style>
