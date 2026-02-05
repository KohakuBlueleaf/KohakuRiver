import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import { routes } from 'vue-router/auto-routes'
import App from './App.vue'

// UnoCSS
import 'virtual:uno.css'

// Element Plus styles
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'

// Custom styles
import './styles/main.css'

// Create router with auto-generated routes
const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Create Pinia store
const pinia = createPinia()

// Create app
const app = createApp(App)

// Use plugins
app.use(pinia)
app.use(router)

// Initialize stores
import { useUIStore } from './stores/ui'
import { useAuthStore } from './stores/auth'

// Route role requirements
const routeRoles = {
  '/': 'anony',
  '/login': null, // No role required (auth pages)
  '/register': null,
  '/nodes': 'viewer',
  '/gpu': 'viewer',
  '/tasks': 'viewer',
  '/vps': 'viewer',
  '/docker': 'operator',
  '/stats': 'viewer',
  '/admin': 'operator',
}

function getRequiredRole(path) {
  // Check exact match first
  if (routeRoles[path] !== undefined) return routeRoles[path]
  // Check prefix match for nested routes
  for (const [route, role] of Object.entries(routeRoles)) {
    if (route !== '/' && path.startsWith(route)) return role
  }
  return 'viewer' // Default to viewer for unknown routes
}

// Auth guard - check authentication before navigation
router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()

  // Initialize auth on first navigation
  if (authStore.isLoading && !authStore.user) {
    await authStore.init()
  }

  // Auth pages (login/register)
  const authPages = ['/login', '/register']
  const isAuthPage = authPages.includes(to.path)

  // If auth is disabled, allow all routes
  if (!authStore.authEnabled) {
    return next()
  }

  // If logged in (not anony) and trying to access login/register, redirect home
  if (authStore.isAuthenticated && isAuthPage) {
    return next('/')
  }

  // Check role requirements for the route
  const requiredRole = getRequiredRole(to.path)
  if (requiredRole && !authStore.hasRole(requiredRole)) {
    // User doesn't have required role
    if (authStore.role === 'anony') {
      // Anonymous user trying to access protected route - redirect to login
      return next({ path: '/login', query: { redirect: to.fullPath } })
    } else {
      // Logged in but insufficient role - redirect home
      return next('/')
    }
  }

  next()
})

router.isReady().then(() => {
  const uiStore = useUIStore()
  uiStore.init()
})

// Mount app
app.mount('#app')
