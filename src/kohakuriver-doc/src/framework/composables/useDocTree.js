import { parseFrontmatter } from '@/framework/utils/markdown.js'

/**
 * Composable for loading the doc tree from prebuild manifests.
 * Fetches manifests recursively, loads frontmatter from each .md file, caches result.
 */
export function useDocTree() {
  const tree = ref(null)
  const loading = ref(false)
  const error = ref(null)

  /** @type {Map<string, object>} path -> node cache */
  const nodeCache = new Map()

  /**
   * Format a filename or dirname into a human-readable title
   * @param {string} name
   * @returns {string}
   */
  function formatName(name) {
    return name
      .replace(/\.md$/, '')
      .replace(/-/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase())
  }

  /**
   * Recursively build tree from manifest
   * @param {string} basePath - URL path (e.g. "/documentation/guide")
   * @param {string} routePath - route path (e.g. "guide")
   * @returns {Promise<object>}
   */
  async function buildTree(basePath, routePath) {
    const manifestUrl = `${basePath}/.manifest.json`
    let manifest
    try {
      const res = await fetch(manifestUrl)
      if (!res.ok) return null
      const text = await res.text()
      if (text.trim().startsWith('<!')) return null
      manifest = JSON.parse(text)
    } catch {
      return null
    }

    const children = []

    // Process subdirectories first
    if (manifest.dirs) {
      const dirResults = await Promise.all(
        manifest.dirs.map((dir) => buildTree(`${basePath}/${dir}`, `${routePath}/${dir}`))
      )
      for (let i = 0; i < manifest.dirs.length; i++) {
        const dirNode = dirResults[i]
        if (dirNode) {
          children.push({
            type: 'dir',
            name: manifest.dirs[i],
            label: dirNode.label || formatName(manifest.dirs[i]),
            path: `/docs/${routePath}/${manifest.dirs[i]}`,
            children: dirNode.children || [],
            icon: dirNode.icon || 'i-carbon-folder',
          })
        }
      }
    }

    // Process files
    if (manifest.files) {
      const fileResults = await Promise.all(
        manifest.files.map(async (filename) => {
          try {
            const res = await fetch(`${basePath}/${filename}`)
            if (!res.ok) return null
            const text = await res.text()
            if (text.trim().startsWith('<!')) return null
            const meta = parseFrontmatter(text)
            const slug = filename.replace(/\.md$/, '')
            const node = {
              type: 'file',
              name: filename,
              label: meta.title || formatName(filename),
              description: meta.description || '',
              path: `/docs/${routePath}/${slug}`,
              icon: meta.icon || 'i-carbon-document',
            }
            nodeCache.set(node.path, node)
            return node
          } catch {
            return null
          }
        })
      )
      for (const node of fileResults) {
        if (node) children.push(node)
      }
    }

    return { children, label: formatName(routePath.split('/').pop() || ''), icon: 'i-carbon-folder' }
  }

  async function load() {
    if (tree.value || loading.value) return
    loading.value = true
    error.value = null
    try {
      const rootRes = await fetch('/documentation/.manifest.json')
      if (!rootRes.ok) throw new Error('No documentation manifest found')
      const rootManifest = await rootRes.json()

      const sections = []
      if (rootManifest.dirs) {
        const results = await Promise.all(rootManifest.dirs.map((dir) => buildTree(`/documentation/${dir}`, dir)))
        for (let i = 0; i < rootManifest.dirs.length; i++) {
          if (results[i]) {
            sections.push({
              type: 'dir',
              name: rootManifest.dirs[i],
              label: results[i].label || formatName(rootManifest.dirs[i]),
              path: `/docs/${rootManifest.dirs[i]}`,
              children: results[i].children || [],
              icon: results[i].icon || 'i-carbon-folder',
            })
          }
        }
      }
      tree.value = sections
    } catch (e) {
      error.value = e.message
      console.error('Failed to load doc tree:', e)
    } finally {
      loading.value = false
    }
  }

  /**
   * Find a node by its route path
   * @param {string} path
   * @returns {object|null}
   */
  function getNode(path) {
    return nodeCache.get(path) || null
  }

  /**
   * Find the section (top-level dir) that contains a given path
   * @param {string} path
   * @returns {object|null}
   */
  function getSection(path) {
    if (!tree.value) return null
    const segments = path.replace(/^\/docs\//, '').split('/')
    return tree.value.find((s) => s.name === segments[0]) || null
  }

  /**
   * Flatten tree into an ordered list of file nodes (depth-first).
   * Used for previous/next page navigation.
   * @returns {Array<object>}
   */
  function getFlatPages() {
    if (!tree.value) return []
    function walk(nodes) {
      const result = []
      for (const node of nodes) {
        if (node.type === 'file') {
          result.push(node)
        } else if (node.type === 'dir' && node.children) {
          result.push(...walk(node.children))
        }
      }
      return result
    }
    return walk(tree.value)
  }

  /**
   * Get previous and next pages relative to the given path.
   * @param {string} path
   * @returns {{ prev: object|null, next: object|null }}
   */
  function getAdjacentPages(path) {
    const pages = getFlatPages()
    const idx = pages.findIndex((p) => p.path === path)
    if (idx === -1) return { prev: null, next: null }
    return {
      prev: idx > 0 ? pages[idx - 1] : null,
      next: idx < pages.length - 1 ? pages[idx + 1] : null,
    }
  }

  return { tree, loading, error, load, getNode, getSection, getFlatPages, getAdjacentPages }
}
