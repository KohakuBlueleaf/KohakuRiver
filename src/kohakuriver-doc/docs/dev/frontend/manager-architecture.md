---
title: Manager Architecture
description: Web dashboard application architecture including pages, stores, components, and API layer
icon: i-carbon-dashboard
---

# Manager Architecture

The Manager is a Vue.js 3 web dashboard at `src/kohakuriver-manager/`. It provides a browser-based interface for managing the KohakuRiver cluster.

## Tech Stack

| Layer      | Technology                                   |
| ---------- | -------------------------------------------- |
| Framework  | Vue.js 3 (Composition API, `<script setup>`) |
| UI Library | Element Plus                                 |
| State      | Pinia                                        |
| Routing    | vue-router with file-based auto-routes       |
| HTTP       | Axios                                        |
| Terminal   | xterm.js                                     |
| Charts     | Plotly.js                                    |
| CSS        | UnoCSS                                       |
| Build      | Vite (rolldown-vite)                         |

## Project Structure

```
src/kohakuriver-manager/src/
  main.js                    # App bootstrap, router, auth guard
  App.vue                    # Root component (header, sidebar, router-view)

  pages/                     # File-based routing
    index.vue                # Home / overview
    login/index.vue          # Login page
    register/index.vue       # Registration page
    nodes/index.vue          # Node list and monitoring
    gpu/index.vue            # GPU utilization dashboard
    tasks/index.vue          # Task list, submit, detail
    vps/index.vue            # VPS management (cards, create)
    docker/index.vue         # Docker image/container management
    stats/index.vue          # Cluster statistics
    admin/index.vue          # Admin panel (users, approvals, invitations)

  components/
    common/                  # Shared components
      EmptyState.vue         # No-data placeholder
      GlobalLoading.vue      # Full-screen loading overlay
      ResourceBar.vue        # CPU/memory usage bar
      StatusBadge.vue        # Status indicator (colored dot + label)
      GpuSelector.vue        # GPU picker with node grouping
      IpReservation.vue      # IP reservation form
    layout/
      TheHeader.vue          # Top navigation bar
      TheSidebar.vue         # Left sidebar menu
    terminal/
      TerminalModal.vue      # xterm.js terminal in modal
    vps/
      PortForwardDialog.vue  # Port forward configuration
    ide/                     # Web IDE components
      IdeLayout.vue          # IDE layout container
      IdeContent.vue         # Main content area
      IdeModal.vue           # IDE in modal
      IdeOverlay.vue         # IDE overlay mode
      EditorTerminalSplit.vue
      common/
        SplitPane.vue        # Resizable split container
        IdeStatusBar.vue     # Editor status bar
      editor/
        EditorPane.vue       # Editor content area
        EditorTabs.vue       # File tab bar
        MonacoEditor.vue     # Monaco editor wrapper
      file-tree/
        FileTree.vue         # File tree sidebar
        FileTreeNode.vue     # Tree node component
        useFileTreeOps.js    # Tree operations composable
      terminal/
        TerminalPane.vue     # Terminal panel

  stores/                    # Pinia stores
    auth.js                  # Authentication state, login/logout
    cluster.js               # Cluster overview data
    tasks.js                 # Task list and operations
    vps.js                   # VPS list and lifecycle
    docker.js                # Docker images and containers
    ide.js                   # IDE editor state
    loading.js               # Global loading indicator
    ui.js                    # UI preferences (theme, sidebar)

  utils/
    api/
      client.js              # Axios instance with interceptors
      index.js               # API module aggregator
      tasks.js               # Task API calls
      vps.js                 # VPS API calls
      nodes.js               # Node API calls
      docker.js              # Docker API calls
      auth.js                # Auth API calls
      overlay.js             # Overlay/IP reservation API
      filesystem.js          # Filesystem API calls
    format.js                # Number/date/byte formatters
    constants.js             # Status colors, type labels
    fileIcons.js             # File extension to icon mapping
    randomName.js            # Random name generator for VPS

  composables/               # Vue composables
    useTerminal.js           # xterm.js lifecycle
    usePolling.js            # Periodic data refresh
    useNotification.js       # Toast notifications
    useAutoSave.js           # Editor auto-save
    useFileSystem.js         # Filesystem operations
    useFileWatcher.js        # File change detection
```

## Routing and Auth Guard

Routes are auto-generated from the `pages/` directory via `unplugin-vue-router`. The auth guard in `main.js` checks roles before navigation:

```javascript
const routeRoles = {
  '/': 'anony',
  '/login': null,
  '/nodes': 'viewer',
  '/tasks': 'viewer',
  '/docker': 'operator',
  '/admin': 'operator',
}
```

If auth is disabled on the host, all routes are accessible.

## Pinia Stores

### Pattern

All stores use the Composition API syntax:

```javascript
export const useVpsStore = defineStore('vps', () => {
  const vpsList = ref([])
  const loading = ref(false)

  const activeVps = computed(() => vpsList.value.filter((v) => ['running', 'paused'].includes(v.status)))

  async function fetchVpsList() {
    loading.value = true
    try {
      const { data } = await vpsAPI.list()
      vpsList.value = data
    } finally {
      loading.value = false
    }
  }

  return { vpsList, loading, activeVps, fetchVpsList }
})
```

### Store Responsibilities

| Store     | Key State                     | Purpose                                  |
| --------- | ----------------------------- | ---------------------------------------- |
| `auth`    | `user`, `role`, `authEnabled` | Login, logout, session init, role checks |
| `cluster` | `nodes`, `tasks`              | Aggregated cluster overview              |
| `tasks`   | `taskList`, `currentTask`     | Task CRUD, filtering, pagination         |
| `vps`     | `vpsList`, `creating`         | VPS lifecycle with loading states        |
| `docker`  | `images`, `containers`        | Docker resource management               |
| `ide`     | `openFiles`, `activeFile`     | Editor state for web IDE                 |
| `loading` | `operations`                  | Global loading indicator for long ops    |
| `ui`      | `theme`, `sidebarCollapsed`   | UI preferences                           |

## API Layer

The API client (`utils/api/client.js`) creates an Axios instance with:

- Base URL from environment or window location
- Cookie-based auth (credentials included)
- Response interceptor for 401 handling

Domain-specific modules export functions:

```javascript
// utils/api/vps.js
export const vpsAPI = {
  list: () => client.get('/api/vps'),
  listActive: () => client.get('/api/vps/active'),
  create: (data) => client.post('/api/vps', data),
  stop: (id) => client.post(`/api/vps/${id}/stop`),
  restart: (id) => client.post(`/api/vps/${id}/restart`),
  pause: (id) => client.post(`/api/vps/${id}/pause`),
  resume: (id) => client.post(`/api/vps/${id}/resume`),
}
```

## Key Pages

### VPS Page (`pages/vps/index.vue`)

Displays VPS instances as cards with status indicators, resource usage, and action buttons. The create dialog supports both Docker and QEMU backends with backend-specific options (VM image, disk size, GPU passthrough).

### Tasks Page (`pages/tasks/index.vue`)

Filterable task list with detail dialog showing stdout/stderr output. Submit dialog for creating new command tasks.

### Admin Page (`pages/admin/index.vue`)

Tab-based admin panel with sub-components: `UsersTab`, `ApprovalsTab`, `InvitationsTab`, `VmInstancesTab`.
