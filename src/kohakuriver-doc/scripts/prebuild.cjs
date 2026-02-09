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
}

main()
