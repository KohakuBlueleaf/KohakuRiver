<template>
  <div>
    <!-- Hero -->
    <section class="py-12 sm:py-16 lg:py-24 text-center">
      <div class="container-doc">
        <div class="i-carbon-flow text-5xl sm:text-6xl text-blue-600 dark:text-blue-400 mx-auto mb-4 sm:mb-6" />
        <h1 class="text-3xl sm:text-4xl lg:text-5xl font-bold mb-3 sm:mb-4">{{ siteConfig.name }}</h1>
        <p class="text-lg sm:text-xl text-gray-600 dark:text-gray-400 mb-6 sm:mb-8 max-w-2xl mx-auto">
          {{ siteConfig.tagline }}
        </p>
        <router-link
          to="/docs/guide/introduction/what-is-kohakuriver"
          class="btn-primary inline-flex items-center gap-2 text-base sm:text-lg px-5 py-2.5 sm:px-6 sm:py-3">
          Get Started
          <div class="i-carbon-arrow-right" />
        </router-link>
      </div>
    </section>

    <!-- Section cards -->
    <section class="py-8 sm:py-12 bg-white dark:bg-gray-800/50">
      <div class="container-doc">
        <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 sm:gap-6 max-w-5xl mx-auto">
          <router-link
            v-for="section in siteConfig.sections"
            :key="section.key"
            :to="`/docs/${section.key}`"
            class="doc-card group text-center">
            <div
              :class="[section.icon, section.color]"
              class="text-4xl sm:text-5xl mx-auto mb-3 sm:mb-4" />
            <h2 class="text-lg sm:text-xl font-bold mb-2 group-hover:text-blue-600 dark:group-hover:text-blue-400">
              {{ section.title }}
            </h2>
            <p class="text-sm text-gray-600 dark:text-gray-400">{{ section.description }}</p>
          </router-link>
        </div>
      </div>
    </section>

    <!-- Quick links -->
    <section class="py-8 sm:py-12">
      <div class="container-doc max-w-3xl mx-auto">
        <h2 class="text-xl sm:text-2xl font-bold text-center mb-6 sm:mb-8">Quick Links</h2>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <router-link
            v-for="link in quickLinks"
            :key="link.path"
            :to="link.path"
            class="card-hover flex items-center gap-3 p-4">
            <div
              :class="link.icon"
              class="text-2xl text-blue-600 dark:text-blue-400 shrink-0" />
            <div>
              <div class="font-medium">{{ link.title }}</div>
              <div class="text-xs text-gray-500 dark:text-gray-400">{{ link.desc }}</div>
            </div>
          </router-link>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import siteConfig from '../../site.config.js'

const quickLinks = [
  {
    title: 'Installation',
    desc: 'Get up and running',
    icon: 'i-carbon-download',
    path: '/docs/guide/getting-started/installation',
  },
  {
    title: 'First Cluster',
    desc: 'Set up host + runner',
    icon: 'i-carbon-assembly-cluster',
    path: '/docs/guide/getting-started/first-cluster',
  },
  { title: 'CLI Reference', desc: 'Command-line tools', icon: 'i-carbon-terminal', path: '/docs/guide/cli/overview' },
  {
    title: 'Architecture',
    desc: 'System design deep-dive',
    icon: 'i-carbon-chart-network',
    path: '/docs/tech-report/architecture/system-design',
  },
]
</script>
