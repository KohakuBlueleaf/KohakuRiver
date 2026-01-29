import { defineConfig, presetUno, presetAttributify, presetIcons } from 'unocss'
import { readFileSync } from 'fs'
import { dirname, join } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Load icon collections synchronously
function loadIconCollection(name) {
  try {
    const path = join(__dirname, 'node_modules', `@iconify-json/${name}`, 'icons.json')
    return JSON.parse(readFileSync(path, 'utf-8'))
  } catch (e) {
    console.warn(`Failed to load icon collection ${name}:`, e.message)
    return {}
  }
}

export default defineConfig({
  presets: [
    presetUno(),
    presetAttributify(),
    presetIcons({
      collections: {
        ep: loadIconCollection('ep'),
        carbon: loadIconCollection('carbon'),
        mdi: loadIconCollection('mdi'),
      },
      scale: 1.2,
      extraProperties: {
        display: 'inline-block',
        'vertical-align': 'middle',
      },
    }),
  ],
  shortcuts: {
    // App-level backgrounds (for consistent theming with custom colors)
    'bg-app-page': 'bg-app-page dark:bg-app-page-dark',         // Main page background
    'bg-app-sidebar': 'bg-app-sidebar dark:bg-app-sidebar-dark', // Sidebar
    'bg-app-card': 'bg-app-card dark:bg-app-card-dark',         // Cards
    'bg-app-surface': 'bg-app-surface dark:bg-app-surface-dark', // Surfaces inside cards
    'bg-app-header': 'bg-app-card dark:bg-app-page-dark',       // Header
    'bg-app-inset': 'bg-app-inset dark:bg-app-inset-dark',     // Inset elements (progress bars, panels)

    // Layout
    'page-container': 'p-6 max-w-full min-h-screen',
    'page-title': 'text-2xl font-bold mb-6 text-gray-800 dark:text-white',
    'section-title': 'text-lg font-semibold mb-4 text-gray-700 dark:text-gray-200',

    // Cards
    'card': 'bg-app-card rounded-lg shadow-md p-2 border border-gray-200 dark:border-gray-600',
    'card-hover': 'card hover:shadow-lg transition-shadow duration-200',
    'card-header': 'flex items-center justify-between mb-4',
    'card-title': 'font-semibold text-gray-800 dark:text-gray-200',

    // Buttons
    'btn': 'px-4 py-2 rounded-md cursor-pointer transition-all duration-200 inline-flex items-center justify-center gap-2 font-medium disabled:opacity-50 disabled:cursor-not-allowed',
    'btn-sm': 'px-3 py-1.5 text-sm rounded',
    'btn-primary': 'btn bg-blue-600 text-white hover:bg-blue-700 active:bg-blue-800',
    'btn-success': 'btn bg-green-600 text-white hover:bg-green-700 active:bg-green-800',
    'btn-warning': 'btn bg-yellow-500 text-white hover:bg-yellow-600 active:bg-yellow-700',
    'btn-danger': 'btn bg-red-600 text-white hover:bg-red-700 active:bg-red-800',
    'btn-ghost': 'btn bg-transparent text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700',
    'btn-outline': 'btn border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700',

    // Status badges
    'badge': 'px-2.5 py-1 rounded-full text-xs font-medium inline-flex items-center gap-1',
    'badge-success': 'badge bg-green-100 text-green-800 dark:bg-green-900/50 dark:text-green-300',
    'badge-warning': 'badge bg-yellow-100 text-yellow-800 dark:bg-yellow-900/50 dark:text-yellow-300',
    'badge-danger': 'badge bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-300',
    'badge-info': 'badge bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-300',
    'badge-gray': 'badge bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300',

    // Grid layouts
    'grid-cards': 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4',
    'grid-cards-fixed': 'flex flex-wrap gap-4',
    'grid-stats': 'grid grid-cols-2 md:grid-cols-4 gap-4',
    'grid-2': 'grid grid-cols-1 md:grid-cols-2 gap-4',
    'grid-3': 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4',

    // Stats
    'stat-card': 'card text-center py-6',
    'stat-value': 'text-3xl font-bold text-gray-900 dark:text-white',
    'stat-label': 'text-sm text-gray-500 dark:text-gray-400 mt-1',
    'stat-icon': 'w-12 h-12 mx-auto mb-3 text-blue-500',

    // Table
    'table-container': 'overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700',
    'table': 'w-full text-sm text-left text-gray-700 dark:text-gray-300',
    'table-header': 'bg-app-surface text-xs uppercase tracking-wider',
    'table-row': 'border-b border-gray-200 dark:border-gray-700 hover:bg-app-surface transition-colors',
    'table-cell': 'px-4 py-3',

    // Forms
    'input': 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all',
    'label': 'block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1',
    'form-group': 'mb-4',

    // Sidebar
    'sidebar': 'w-64 bg-gray-900 text-gray-100 min-h-screen flex flex-col',
    'sidebar-collapsed': 'w-16',
    'sidebar-item': 'flex items-center gap-3 px-4 py-3 hover:bg-gray-800 transition-colors cursor-pointer',
    'sidebar-item-active': 'sidebar-item bg-blue-600 hover:bg-blue-700',

    // Utility
    'flex-center': 'flex items-center justify-center',
    'flex-between': 'flex items-center justify-between',
    'text-muted': 'text-gray-500 dark:text-gray-400',
    'divider': 'border-t border-gray-200 dark:border-gray-700',

    // Progress bar
    'progress-bar': 'h-2 bg-app-inset rounded-full overflow-hidden',
    'progress-fill': 'h-full bg-blue-500 rounded-full transition-all duration-300',

    // Terminal
    'terminal': 'bg-gray-900 text-gray-100 font-mono text-sm rounded-lg overflow-hidden',
  },
  theme: {
    colors: {
      primary: {
        DEFAULT: '#3b82f6',
        50: '#eff6ff',
        100: '#dbeafe',
        200: '#bfdbfe',
        300: '#93c5fd',
        400: '#60a5fa',
        500: '#3b82f6',
        600: '#2563eb',
        700: '#1d4ed8',
        800: '#1e40af',
        900: '#1e3a8a',
      },
      // Custom app colors for distinct UI layers (flat naming for UnoCSS)
      // Light mode: white cards on light gray page - use DARKER inset colors
      'app-sidebar': '#1e293b',      // slate-800 - darkest
      'app-page': '#f1f5f9',         // slate-100 - main background
      'app-card': '#ffffff',         // white - cards
      'app-surface': '#f1f5f9',      // slate-100 - surfaces inside cards (darker than card)
      'app-inset': '#e2e8f0',        // slate-200 - inset elements (progress bg, panels)
      // Dark mode: dark cards on darker page - use BRIGHTER inset colors for contrast
      'app-sidebar-dark': '#0f172a',  // slate-900
      'app-page-dark': '#1e293b',     // slate-800
      'app-card-dark': '#334155',     // slate-700
      'app-surface-dark': '#475569',  // slate-600 - surfaces inside cards (brighter than card)
      'app-inset-dark': '#64748b',    // slate-500 - inset elements (brighter for contrast)
    },
  },
  safelist: [
    // Ensure status colors are always available
    'bg-green-500', 'bg-yellow-500', 'bg-red-500', 'bg-blue-500', 'bg-gray-500',
    'text-green-500', 'text-yellow-500', 'text-red-500', 'text-blue-500', 'text-gray-500',
    // File tree icon colors
    'text-amber-500', 'text-cyan-500', 'text-yellow-500', 'text-blue-400', 'text-blue-500',
    'text-green-500', 'text-orange-500', 'text-pink-500', 'text-gray-300', 'text-gray-400',
    'text-purple-400',
    // File icons (for dynamic file tree icons)
    'i-carbon-document-blank', 'i-carbon-folder', 'i-carbon-folder-open', 'i-carbon-link',
    'i-carbon-help', 'i-carbon-logo-javascript', 'i-carbon-typescript', 'i-carbon-logo-python',
    'i-carbon-logo-vue', 'i-carbon-json', 'i-carbon-document', 'i-carbon-code',
    'i-carbon-table-split', 'i-carbon-html', 'i-carbon-css', 'i-carbon-terminal',
    'i-carbon-settings', 'i-carbon-logo-github', 'i-carbon-container-software',
    'i-carbon-image', 'i-carbon-zip', 'i-carbon-application', 'i-carbon-data-base',
    'i-carbon-build-tool', 'i-carbon-package', 'i-carbon-locked', 'i-carbon-report',
    'i-carbon-document-pdf', 'i-carbon-spreadsheet', 'i-carbon-presentation-file',
    'i-carbon-video', 'i-carbon-music', 'i-carbon-book', 'i-carbon-license',
    'i-carbon-list-numbered',
    // Context menu icons
    'i-carbon-document-add', 'i-carbon-folder-add', 'i-carbon-edit',
    'i-carbon-trash-can', 'i-carbon-copy', 'i-carbon-refresh',
  ],
})
