import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import VueRouter from 'unplugin-vue-router/vite'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { VueRouterAutoImports } from 'unplugin-vue-router'
import UnoCSS from 'unocss/vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [
    // File-based routing - must be before vue()
    VueRouter({
      routesFolder: 'src/pages',
      dts: 'src/typed-router.d.ts',
    }),
    vue(),
    // Auto-import Vue APIs, Pinia, Vue Router
    AutoImport({
      imports: [
        'vue',
        'pinia',
        VueRouterAutoImports,
        '@vueuse/core',
      ],
      resolvers: [ElementPlusResolver()],
      dts: 'src/auto-imports.d.ts',
      dirs: ['src/composables', 'src/stores'],
    }),
    // Auto-register components
    Components({
      dirs: ['src/components'],
      resolvers: [ElementPlusResolver()],
      dts: 'src/components.d.ts',
    }),
    // UnoCSS for atomic CSS
    UnoCSS(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      // API proxy to backend (backend now uses /api prefix natively)
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // WebSocket proxy (backend now uses /ws prefix natively)
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
