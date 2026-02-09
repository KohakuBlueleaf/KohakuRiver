import { defineConfig, presetAttributify, presetIcons } from 'unocss'
import { presetWind } from '@unocss/preset-wind3'

export default defineConfig({
  presets: [
    presetWind(),
    presetAttributify(),
    presetIcons({
      collections: {
        ep: () => import('@iconify-json/ep/icons.json', { with: { type: 'json' } }).then((i) => i.default),
        carbon: () =>
          import('@iconify-json/carbon/icons.json', { with: { type: 'json' } }).then((i) => i.default),
      },
      scale: 1.2,
      warn: false,
    }),
  ],
  shortcuts: {
    // Buttons
    btn: 'px-4 py-2 rounded cursor-pointer transition-colors',
    'btn-primary': 'btn bg-blue-500 text-white hover:bg-blue-600',
    'btn-secondary':
      'btn bg-gray-200 text-gray-800 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-200 dark:hover:bg-gray-600',

    // Cards
    card: 'bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 p-4',
    'card-hover': 'card hover:shadow-lg transition-all duration-200 cursor-pointer',

    // Layout
    'container-doc': 'max-w-7xl mx-auto px-4 sm:px-6',
    'doc-content': 'flex-1 min-w-0 px-4 py-6 sm:px-6 sm:py-8 lg:px-12',
    'doc-card': 'card-hover p-6',

    // Sidebar container — fixed position, solid bg
    'doc-sidebar-wrap':
      'w-64 border-r border-blue-100 dark:border-blue-950 overflow-y-auto bg-blue-50 dark:bg-gray-950',
    // Mobile sidebar: full-width drawer capped at 20rem
    'doc-sidebar-mobile':
      'w-[85vw] max-w-80 border-r border-blue-100 dark:border-blue-950 overflow-y-auto bg-blue-50 dark:bg-gray-950 shadow-xl lg:shadow-none',

    // Sidebar tree items — all use bg-transparent as base, min-h for touch targets
    'sidebar-item':
      'w-full flex items-center gap-1.5 px-2 py-2 lg:py-1.5 text-sm rounded transition-colors bg-transparent cursor-pointer',
    'sidebar-item-idle':
      'sidebar-item text-gray-700 dark:text-gray-300 hover:bg-blue-100/70 dark:hover:bg-blue-900/30 hover:text-blue-700 dark:hover:text-blue-300',
    'sidebar-item-ancestor':
      'sidebar-item text-blue-700 dark:text-blue-300 font-medium bg-blue-100/50 dark:bg-blue-900/25',
    'sidebar-item-active':
      'sidebar-item bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-200 font-medium',
    'sidebar-branch': 'ml-3 border-l border-blue-200 dark:border-blue-800/50 pl-1',

    // Prev/next navigation links
    'doc-nav-link':
      'flex-1 flex flex-col gap-1 px-4 py-3 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-blue-300 dark:hover:border-blue-700 transition-colors',
  },
  theme: {
    colors: {
      primary: {
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
    },
  },
  safelist: [
    // All frontmatter icons (dynamic :class, must be safelisted)
    'i-carbon-activity',
    'i-carbon-bare-metal-server',
    'i-carbon-book',
    'i-carbon-build-tool',
    'i-carbon-calendar',
    'i-carbon-catalog',
    'i-carbon-chip',
    'i-carbon-cloud',
    'i-carbon-cloud-app',
    'i-carbon-cloud-service-management',
    'i-carbon-code',
    'i-carbon-collaborate',
    'i-carbon-connect',
    'i-carbon-container-image',
    'i-carbon-container-software',
    'i-carbon-dashboard',
    'i-carbon-data-backup',
    'i-carbon-data-base',
    'i-carbon-data-format',
    'i-carbon-data-share',
    'i-carbon-data-vis-4',
    'i-carbon-debug',
    'i-carbon-document',
    'i-carbon-document-add',
    'i-carbon-download',
    'i-carbon-edge-node',
    'i-carbon-folder',
    'i-carbon-locked',
    'i-carbon-network-3',
    'i-carbon-network-3-reference',
    'i-carbon-network-4',
    'i-carbon-network-overlay',
    'i-carbon-paint-brush',
    'i-carbon-play',
    'i-carbon-port-input',
    'i-carbon-report',
    'i-carbon-restart',
    'i-carbon-rocket',
    'i-carbon-rule',
    'i-carbon-save',
    'i-carbon-security',
    'i-carbon-server-dns',
    'i-carbon-server-proxy',
    'i-carbon-settings',
    'i-carbon-settings-adjust',
    'i-carbon-task',
    'i-carbon-task-settings',
    'i-carbon-task-tools',
    'i-carbon-terminal',
    'i-carbon-user-admin',
    'i-carbon-virtual-machine',
    // UI icons (sidebar, mermaid controls, theme, spinner)
    'i-carbon-chevron-right',
    'i-carbon-chevron-down',
    'i-carbon-menu',
    'i-carbon-close',
    'i-carbon-zoom-in',
    'i-carbon-zoom-out',
    'i-carbon-zoom-reset',
    'i-carbon-maximize',
    'i-carbon-arrow-right',
    'i-carbon-circle-dash',
    'i-carbon-sun',
    'i-carbon-moon',
    // Dynamic color classes
    'text-blue-600',
    'text-purple-600',
    'text-green-600',
    'dark:text-blue-400',
    'dark:text-purple-400',
    'dark:text-green-400',
  ],
})
