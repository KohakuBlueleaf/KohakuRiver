<script setup>
/**
 * Login Page
 *
 * Handles user authentication via username/password.
 */

import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const username = ref('')
const password = ref('')
const isLoading = ref(false)
const errorMessage = ref('')

// Redirect if already authenticated
watchEffect(() => {
  if (authStore.isAuthenticated && !authStore.isLoading) {
    const redirect = route.query.redirect || '/'
    router.push(redirect)
  }
})

async function handleLogin() {
  if (!username.value || !password.value) {
    errorMessage.value = 'Please enter username and password'
    return
  }

  isLoading.value = true
  errorMessage.value = ''

  const result = await authStore.login(username.value, password.value)

  if (result.success) {
    const redirect = route.query.redirect || '/'
    router.push(redirect)
  } else {
    errorMessage.value = result.error
  }

  isLoading.value = false
}
</script>

<template>
  <div class="h-full flex items-center justify-center bg-app-bg">
    <div class="w-full max-w-md p-8">
      <!-- Logo -->
      <div class="text-center mb-8">
        <img
          src="/favicon.svg"
          alt="KohakuRiver"
          class="w-16 h-16 mx-auto mb-4" />
        <h1 class="text-2xl font-bold text-app-text">KohakuRiver</h1>
        <p class="text-app-text-muted mt-2">Sign in to your account</p>
      </div>

      <!-- Login Form -->
      <form
        @submit.prevent="handleLogin"
        class="space-y-6 bg-app-card p-6 rounded-lg shadow-lg">
        <!-- Error Message -->
        <div
          v-if="errorMessage"
          class="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-500 text-sm">
          {{ errorMessage }}
        </div>

        <!-- Username -->
        <div>
          <label
            for="username"
            class="block text-sm font-medium text-app-text mb-2">
            Username
          </label>
          <input
            id="username"
            v-model="username"
            type="text"
            autocomplete="username"
            required
            class="w-full px-4 py-2 bg-app-bg border border-app-border rounded-lg text-app-text focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            placeholder="Enter your username" />
        </div>

        <!-- Password -->
        <div>
          <label
            for="password"
            class="block text-sm font-medium text-app-text mb-2">
            Password
          </label>
          <input
            id="password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            required
            class="w-full px-4 py-2 bg-app-bg border border-app-border rounded-lg text-app-text focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            placeholder="Enter your password" />
        </div>

        <!-- Submit Button -->
        <button
          type="submit"
          :disabled="isLoading"
          class="w-full py-2 px-4 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
          <span v-if="isLoading">Signing in...</span>
          <span v-else>Sign In</span>
        </button>

        <!-- Register Link -->
        <p class="text-center text-sm text-app-text-muted">
          Have an invitation?
          <router-link
            to="/register"
            class="text-blue-500 hover:text-blue-400">
            Create an account
          </router-link>
        </p>
      </form>
    </div>
  </div>
</template>

<style scoped>
/* Use app theme variables */
.bg-app-bg {
  background-color: var(--bg-color, #1a1a2e);
}

.bg-app-card {
  background-color: var(--card-bg, #16213e);
}

.text-app-text {
  color: var(--text-color, #eee);
}

.text-app-text-muted {
  color: var(--text-muted, #888);
}

.border-app-border {
  border-color: var(--border-color, #333);
}
</style>
