#!/usr/bin/env node
/**
 * Generic prebuild script for doc site framework.
 * Recursively copies docs/ -> public/documentation/ with manifest generation.
 *
 * Ordering: If a directory contains `_order.json`, it defines the order of
 * files and subdirectories. Format: ["intro.md", "setup", "advanced.md", ...]
 * Items not listed in _order.json are appended alphabetically at the end.
 * _order.json itself is NOT copied to the output.
 */

const fs = require('fs')
const path = require('path')

const rootDir = path.join(__dirname, '..')
const docsSourceDir = path.join(rootDir, 'docs')
const publicDir = path.join(rootDir, 'public')
const docsPublicDir = path.join(publicDir, 'documentation')

/**
 * Apply ordering from _order.json if it exists.
 * @param {string} sourceDir
 * @param {string[]} items - unordered list of filenames/dirnames
 * @returns {string[]} ordered list
 */
function applyOrder(sourceDir, items) {
  const orderFile = path.join(sourceDir, '_order.json')
  if (!fs.existsSync(orderFile)) return items.sort()

  try {
    const order = JSON.parse(fs.readFileSync(orderFile, 'utf-8'))
    const orderSet = new Set(order)
    const ordered = order.filter((name) => items.includes(name))
    const remaining = items.filter((name) => !orderSet.has(name)).sort()
    return [...ordered, ...remaining]
  } catch (e) {
    console.warn(`  Warning: invalid _order.json in ${sourceDir}: ${e.message}`)
    return items.sort()
  }
}

/**
 * Recursively copy directory and generate manifests
 * @returns {{ files: string[], dirs: string[] }} manifest for this directory
 */
function copyDirRecursive(sourceDir, destDir) {
  if (!fs.existsSync(sourceDir)) {
    console.warn(`  Warning: source not found: ${sourceDir}`)
    return { files: [], dirs: [] }
  }

  if (!fs.existsSync(destDir)) {
    fs.mkdirSync(destDir, { recursive: true })
  }

  const entries = fs.readdirSync(sourceDir, { withFileTypes: true })
  const rawFiles = []
  const rawDirs = []

  for (const entry of entries) {
    // Skip _order.json — it's metadata, not content
    if (entry.name === '_order.json') continue

    const sourcePath = path.join(sourceDir, entry.name)
    const destPath = path.join(destDir, entry.name)

    if (entry.isDirectory()) {
      const childManifest = copyDirRecursive(sourcePath, destPath)
      // Only include directories that have content
      if (childManifest.files.length > 0 || childManifest.dirs.length > 0) {
        rawDirs.push(entry.name)
      }
    } else if (entry.isFile() && entry.name.endsWith('.md')) {
      fs.copyFileSync(sourcePath, destPath)
      rawFiles.push(entry.name)
    }
  }

  // Apply ordering
  const files = applyOrder(sourceDir, rawFiles)
  const dirs = applyOrder(sourceDir, rawDirs)

  // Write manifest
  const manifest = { files, dirs }
  fs.writeFileSync(path.join(destDir, '.manifest.json'), JSON.stringify(manifest, null, 2))

  const rel = path.relative(rootDir, destDir)
  if (files.length > 0 || dirs.length > 0) {
    console.log(`  ${rel}/: ${files.length} files, ${dirs.length} dirs`)
  }

  return manifest
}

// =============================================================================
// Search Index Generation
// =============================================================================

/**
 * Strip YAML frontmatter from markdown
 * @param {string} text
 * @returns {string}
 */
function stripFrontmatter(text) {
  return text.replace(/^---\s*\n[\s\S]*?\n---\s*\n/, '')
}

/**
 * Parse YAML frontmatter into { title, description }
 * @param {string} text
 * @returns {{ title: string|null, description: string|null }}
 */
function parseFrontmatter(text) {
  const match = text.match(/^---\s*\n([\s\S]*?)\n---\s*\n/)
  if (!match) return { title: null, description: null }
  const meta = {}
  for (const line of match[1].split('\n')) {
    const [key, ...parts] = line.split(':')
    if (key && parts.length) {
      meta[key.trim()] = parts.join(':').trim()
    }
  }
  return { title: meta.title || null, description: meta.description || null }
}

/**
 * Convert markdown to plain text for search indexing.
 * Strips syntax but keeps readable content.
 * @param {string} md
 * @returns {string}
 */
function markdownToPlainText(md) {
  return (
    md
      // Remove code blocks (including mermaid, language-tagged)
      .replace(/```[\s\S]*?```/g, '')
      // Remove inline code
      .replace(/`([^`]+)`/g, '$1')
      // Remove images
      .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
      // Convert links to just text
      .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
      // Remove heading markers
      .replace(/^#{1,6}\s+/gm, '')
      // Remove bold/italic markers
      .replace(/\*{1,3}([^*]+)\*{1,3}/g, '$1')
      .replace(/_{1,3}([^_]+)_{1,3}/g, '$1')
      // Remove horizontal rules
      .replace(/^[-*_]{3,}\s*$/gm, '')
      // Remove HTML tags
      .replace(/<[^>]+>/g, '')
      // Remove table separators
      .replace(/^\|[-:| ]+\|$/gm, '')
      // Clean table rows to just text
      .replace(/\|/g, ' ')
      // Remove blockquote markers
      .replace(/^>\s?/gm, '')
      // Remove list markers
      .replace(/^[\s]*[-*+]\s+/gm, '')
      .replace(/^[\s]*\d+\.\s+/gm, '')
      // Collapse whitespace
      .replace(/\n{3,}/g, '\n\n')
      .replace(/[ \t]+/g, ' ')
      .trim()
  )
}

/**
 * Recursively collect all markdown files for the search index.
 * @param {string} sourceDir
 * @param {string} routePath - e.g. "guide/setup"
 * @param {string[]} sectionParts - breadcrumb trail ["guide", "setup"]
 * @returns {Array<{ id: string, path: string, title: string, description: string, section: string, body: string }>}
 */
function collectSearchDocuments(sourceDir, routePath, sectionParts) {
  if (!fs.existsSync(sourceDir)) return []

  const entries = fs.readdirSync(sourceDir, { withFileTypes: true })
  const docs = []

  for (const entry of entries) {
    if (entry.name === '_order.json') continue

    const sourcePath = path.join(sourceDir, entry.name)

    if (entry.isDirectory()) {
      const childRoute = routePath ? `${routePath}/${entry.name}` : entry.name
      docs.push(
        ...collectSearchDocuments(sourcePath, childRoute, [...sectionParts, entry.name])
      )
    } else if (entry.isFile() && entry.name.endsWith('.md')) {
      const raw = fs.readFileSync(sourcePath, 'utf-8')
      const meta = parseFrontmatter(raw)
      const body = markdownToPlainText(stripFrontmatter(raw))
      const slug = entry.name.replace(/\.md$/, '')
      const docPath = `/docs/${routePath}/${slug}`

      docs.push({
        id: docPath,
        path: docPath,
        title: meta.title || formatNameForSearch(entry.name),
        description: meta.description || '',
        section: sectionParts[0] || '',
        body,
      })
    }
  }

  return docs
}

/**
 * Format filename as title (fallback when no frontmatter title)
 * @param {string} name
 * @returns {string}
 */
function formatNameForSearch(name) {
  return name
    .replace(/\.md$/, '')
    .replace(/-/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

/**
 * Build and write the search index JSON.
 */
function buildSearchIndex() {
  console.log('\nSearch index: building...')
  const docs = collectSearchDocuments(docsSourceDir, '', [])

  const indexPath = path.join(publicDir, 'search-index.json')
  fs.writeFileSync(indexPath, JSON.stringify(docs))

  const sizeKB = (fs.statSync(indexPath).size / 1024).toFixed(1)
  console.log(`Search index: ${docs.length} documents, ${sizeKB} KB`)
}

// =============================================================================
// Main
// =============================================================================

function main() {
  console.log('Prebuild: copying docs/ -> public/documentation/\n')

  // Clean existing
  if (fs.existsSync(docsPublicDir)) {
    fs.rmSync(docsPublicDir, { recursive: true })
  }
  fs.mkdirSync(docsPublicDir, { recursive: true })

  if (!fs.existsSync(docsSourceDir)) {
    console.error('Error: docs/ directory not found')
    process.exit(1)
  }

  const rootManifest = copyDirRecursive(docsSourceDir, docsPublicDir)
  console.log(`\nDone: ${rootManifest.files.length} root files, ${rootManifest.dirs.length} sections`)

  // Build search index
  buildSearchIndex()
}

main()
