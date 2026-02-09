import MarkdownIt from 'markdown-it'
import DOMPurify from 'isomorphic-dompurify'
import hljs from 'highlight.js/lib/core'

// Import only the languages you need (reduces bundle size)
import javascript from 'highlight.js/lib/languages/javascript'
import python from 'highlight.js/lib/languages/python'
import go from 'highlight.js/lib/languages/go'
import rust from 'highlight.js/lib/languages/rust'
import shell from 'highlight.js/lib/languages/shell'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'
import markdown from 'highlight.js/lib/languages/markdown'
import css from 'highlight.js/lib/languages/css'
import sql from 'highlight.js/lib/languages/sql'
import ini from 'highlight.js/lib/languages/ini'
import dockerfile from 'highlight.js/lib/languages/dockerfile'

// Register languages
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('js', javascript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('go', go)
hljs.registerLanguage('rust', rust)
hljs.registerLanguage('shell', shell)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('json', json)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('html', xml)
hljs.registerLanguage('yaml', yaml)
hljs.registerLanguage('yml', yaml)
hljs.registerLanguage('markdown', markdown)
hljs.registerLanguage('md', markdown)
hljs.registerLanguage('css', css)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('ini', ini)
hljs.registerLanguage('toml', ini)
hljs.registerLanguage('dockerfile', dockerfile)

/**
 * Create markdown renderer with XSS protection and syntax highlighting
 */
const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  breaks: true,
  highlight: function (code, lang) {
    // Use highlight.js for syntax highlighting
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(code, { language: lang }).value
      } catch (e) {
        console.error('Highlight error:', e)
      }
    }
    // Fallback to plain code
    return md.utils.escapeHtml(code)
  },
})

/**
 * Add support for GitHub-style task lists
 * Converts - [ ] and - [x] to checkboxes
 */
md.core.ruler.after('inline', 'task-lists', function (state) {
  const tokens = state.tokens
  for (let i = 0; i < tokens.length; i++) {
    if (tokens[i].type !== 'inline') continue

    const children = tokens[i].children
    for (let j = 0; j < children.length; j++) {
      const token = children[j]
      if (token.type !== 'text') continue

      const content = token.content
      const match = content.match(/^\[([ xX])\]\s+/)
      if (!match) continue

      const isChecked = match[1].toLowerCase() === 'x'
      const checkbox = new state.Token('html_inline', '', 0)
      checkbox.content = `<input type="checkbox" disabled ${isChecked ? 'checked' : ''} class="task-list-checkbox"> `

      const remainingText = new state.Token('text', '', 0)
      remainingText.content = content.slice(match[0].length)

      children.splice(j, 1, checkbox, remainingText)
      break
    }
  }
  return true
})

/**
 * Sanitize HTML with blacklist approach
 * @param {string} html - Raw HTML to sanitize
 * @returns {string} - Sanitized HTML
 */
export function sanitizeHTML(html) {
  if (!html) return ''

  return DOMPurify.sanitize(html, {
    FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'applet', 'meta', 'link', 'base', 'form'],
    FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover', 'onfocus', 'onblur', 'onchange', 'onsubmit'],
    ALLOW_DATA_ATTR: true,
    ALLOW_UNKNOWN_PROTOCOLS: false,
    SANITIZE_DOM: true,
    KEEP_CONTENT: true,
    USE_PROFILES: { html: true, svg: true },
  })
}

/**
 * Strip YAML frontmatter from markdown content
 * @param {string} markdown
 * @returns {string}
 */
export function stripYAMLFrontmatter(markdown) {
  if (!markdown) return ''
  return markdown.replace(/^---\s*\n([\s\S]*?\n)?---\s*\n/, '')
}

/**
 * Parse YAML frontmatter into an object
 * @param {string} markdown
 * @returns {{ title: string|null, description: string|null, icon: string|null }}
 */
export function parseFrontmatter(markdown) {
  if (!markdown) return { title: null, description: null, icon: null }
  const match = markdown.match(/^---\s*\n([\s\S]*?)\n---\s*\n/)
  if (!match) return { title: null, description: null, icon: null }
  const meta = {}
  for (const line of match[1].split('\n')) {
    const [key, ...parts] = line.split(':')
    if (key && parts.length) {
      meta[key.trim()] = parts.join(':').trim()
    }
  }
  return {
    title: meta.title || null,
    description: meta.description || null,
    icon: meta.icon || null,
  }
}

/**
 * Render markdown to safe HTML
 * @param {string} markdown
 * @param {{ stripFrontmatter?: boolean }} options
 * @returns {string}
 */
export function renderMarkdown(markdown, options = {}) {
  if (!markdown) return ''

  const { stripFrontmatter = false } = options

  try {
    let content = stripFrontmatter ? stripYAMLFrontmatter(markdown) : markdown
    let rawHTML = md.render(content)
    return sanitizeHTML(rawHTML)
  } catch (err) {
    console.error('Markdown rendering error:', err)
    return ''
  }
}

export default md
