import MiniSearch from 'minisearch'

/**
 * Composable for full-text search over the documentation.
 * Loads a prebuild-generated JSON index, initializes MiniSearch,
 * and provides a reactive search function.
 */
export function useSearch() {
  /** @type {import('vue').Ref<MiniSearch|null>} */
  const engine = ref(null)
  const loading = ref(false)
  const ready = ref(false)

  async function init() {
    if (engine.value || loading.value) return
    loading.value = true
    try {
      const res = await fetch('/search-index.json')
      if (!res.ok) throw new Error(`Failed to fetch search index: ${res.status}`)
      const docs = await res.json()

      const ms = new MiniSearch({
        fields: ['title', 'description', 'body'],
        storeFields: ['title', 'description', 'path', 'section'],
        searchOptions: {
          boost: { title: 3, description: 2 },
          fuzzy: 0.2,
          prefix: true,
        },
      })
      ms.addAll(docs)
      engine.value = ms
      ready.value = true
    } catch (e) {
      console.error('Search init failed:', e)
    } finally {
      loading.value = false
    }
  }

  /**
   * Search documentation.
   * @param {string} query
   * @param {number} [limit=20]
   * @returns {Array<{ id: string, title: string, description: string, path: string, section: string, score: number }>}
   */
  function search(query, limit = 20) {
    if (!engine.value || !query.trim()) return []
    return engine.value.search(query).slice(0, limit)
  }

  return { init, search, ready, loading }
}
