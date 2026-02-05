<script setup>
/**
 * Registration Page
 *
 * Handles new user registration with invitation token.
 */

import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const username = ref('')
const password = ref('')
const confirmPassword = ref('')
const displayName = ref('')
const invitationToken = ref(route.query.token || '')
const isLoading = ref(false)
const errorMessage = ref('')

// Redirect if already authenticated
watchEffect(() => {
  if (authStore.isAuthenticated && !authStore.isLoading) {
    router.push('/')
  }
})

async function handleRegister() {
  // Validation
  if (!username.value || !password.value || !invitationToken.value) {
    errorMessage.value = 'Please fill in all required fields'
    return
  }

  if (username.value.length < 3) {
    errorMessage.value = 'Username must be at least 3 characters'
    return
  }

  if (password.value.length < 8) {
    errorMessage.value = 'Password must be at least 8 characters'
    return
  }

  if (password.value !== confirmPassword.value) {
    errorMessage.value = 'Passwords do not match'
    return
  }

  isLoading.value = true
  errorMessage.value = ''

  const result = await authStore.register(
    username.value,
    password.value,
    displayName.value || username.value,
    invitationToken.value
  )

  if (result.success) {
    router.push('/')
  } else {
    errorMessage.value = result.error
  }

  isLoading.value = false
}
</script>

<template>
  <div class="min-h-full py-8 flex items-center justify-center bg-app-bg">
    <div class="w-full max-w-md p-8">
      <!-- Logo -->
      <div class="text-center mb-8">
        <img
          src="/favicon.svg"
          alt="KohakuRiver"
          class="w-16 h-16 mx-auto mb-4" />
        <h1 class="text-2xl font-bold text-app-text">KohakuRiver</h1>
        <p class="text-app-text-muted mt-2">Create your account</p>
      </div>

      <!-- Registration Form -->
      <form
        @submit.prevent="handleRegister"
        class="space-y-5 bg-app-card p-6 rounded-lg shadow-lg">
        <!-- Error Message -->
        <div
          v-if="errorMessage"
          class="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-500 text-sm">
          {{ errorMessage }}
        </div>

        <!-- Invitation Token -->
        <div>
          <label
            for="token"
            class="block text-sm font-medium text-app-text mb-2">
            Invitation Token
            <span class="text-red-500">*</span>
          </label>
          <input
            id="token"
            v-model="invitationToken"
            type="text"
            required
            class="w-full px-4 py-2 bg-app-bg border border-app-border rounded-lg text-app-text focus:ring-2 focus:ring-blue-500 focus:border-transparent font-mono text-sm"
            placeholder="Enter your invitation token" />
        </div>

        <!-- Username -->
        <div>
          <label
            for="username"
            class="block text-sm font-medium text-app-text mb-2">
            Username
            <span class="text-red-500">*</span>
          </label>
          <input
            id="username"
            v-model="username"
            type="text"
            autocomplete="username"
            required
            minlength="3"
            maxlength="50"
            class="w-full px-4 py-2 bg-app-bg border border-app-border rounded-lg text-app-text focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            placeholder="Choose a username" />
        </div>

        <!-- Display Name -->
        <div>
          <label
            for="displayName"
            class="block text-sm font-medium text-app-text mb-2">
            Display Name
          </label>
          <input
            id="displayName"
            v-model="displayName"
            type="text"
            maxlength="100"
            class="w-full px-4 py-2 bg-app-bg border border-app-border rounded-lg text-app-text focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            placeholder="Your display name (optional)" />
        </div>

        <!-- Password -->
        <div>
          <label
            for="password"
            class="block text-sm font-medium text-app-text mb-2">
            Password
            <span class="text-red-500">*</span>
          </label>
          <input
            id="password"
            v-model="password"
            type="password"
            autocomplete="new-password"
            required
            minlength="8"
            class="w-full px-4 py-2 bg-app-bg border border-app-border rounded-lg text-app-text focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            placeholder="Create a password (min 8 characters)" />
        </div>

        <!-- Confirm Password -->
        <div>
          <label
            for="confirmPassword"
            class="block text-sm font-medium text-app-text mb-2">
            Confirm Password
            <span class="text-red-500">*</span>
          </label>
          <input
            id="confirmPassword"
            v-model="confirmPassword"
            type="password"
            autocomplete="new-password"
            required
            class="w-full px-4 py-2 bg-app-bg border border-app-border rounded-lg text-app-text focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            placeholder="Confirm your password" />
        </div>

        <!-- Submit Button -->
        <button
          type="submit"
          :disabled="isLoading"
          class="w-full py-2 px-4 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
          <span v-if="isLoading">Creating account...</span>
          <span v-else>Create Account</span>
        </button>

        <!-- Login Link -->
        <p class="text-center text-sm text-app-text-muted">
          Already have an account?
          <router-link
            to="/login"
            class="text-blue-500 hover:text-blue-400">
            Sign in
          </router-link>
        </p>
      </form>
    </div>
  </div>
</template>

<style scoped>
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
