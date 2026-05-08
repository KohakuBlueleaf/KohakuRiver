import { Terminal } from 'xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import 'xterm/css/xterm.css'

export function useTerminal() {
  const terminal = ref(null)
  const socket = ref(null)
  const fitAddon = ref(null)
  const connected = ref(false)
  const connecting = ref(false)
  const error = ref(null)

  function createTerminal(container, options = {}) {
    const defaultOptions = {
      cursorBlink: true,
      fontSize: 14,
      fontFamily: 'Consolas, Menlo, Monaco, "Courier New", monospace',
      theme: {
        background: '#1e1e1e',
        foreground: '#d4d4d4',
        cursor: '#d4d4d4',
        cursorAccent: '#1e1e1e',
        selection: 'rgba(255, 255, 255, 0.3)',
      },
    }

    terminal.value = new Terminal({ ...defaultOptions, ...options })
    fitAddon.value = new FitAddon()

    terminal.value.loadAddon(fitAddon.value)
    terminal.value.loadAddon(new WebLinksAddon())

    terminal.value.open(container)
    fitAddon.value.fit()

    return terminal.value
  }

  function connect(taskId, type = 'task') {
    if (connecting.value || connected.value) return

    connecting.value = true
    error.value = null

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/${type}/${taskId}/terminal`

    socket.value = new WebSocket(wsUrl)

    socket.value.onopen = () => {
      connected.value = true
      connecting.value = false
      terminal.value?.write('\x1b[32mConnected to terminal\x1b[0m\r\n')
      sendResize()
    }

    socket.value.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'output') {
          terminal.value?.write(msg.data)
        } else if (msg.type === 'error') {
          terminal.value?.write(`\r\n\x1b[31mError: ${msg.data}\x1b[0m\r\n`)
          error.value = msg.data
        }
      } catch {
        // Plain text output
        terminal.value?.write(event.data)
      }
    }

    socket.value.onclose = (event) => {
      connected.value = false
      connecting.value = false
      terminal.value?.write('\r\n\x1b[33mConnection closed\x1b[0m\r\n')
    }

    socket.value.onerror = (err) => {
      error.value = 'WebSocket connection failed'
      connecting.value = false
      console.error('WebSocket error:', err)
    }

    // Setup terminal input handler
    terminal.value?.onData((data) => {
      if (socket.value?.readyState === WebSocket.OPEN) {
        socket.value.send(JSON.stringify({ type: 'input', data }))
      }
    })
  }

  function connectToContainer(containerName) {
    if (connecting.value || connected.value) return

    connecting.value = true
    error.value = null

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/docker/host/containers/${containerName}/terminal`

    socket.value = new WebSocket(wsUrl)

    socket.value.onopen = () => {
      connected.value = true
      connecting.value = false
      terminal.value?.write('\x1b[32mConnected to container\x1b[0m\r\n')
      sendResize()
    }

    socket.value.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'output') {
          terminal.value?.write(msg.data)
        } else if (msg.type === 'error') {
          terminal.value?.write(`\r\n\x1b[31mError: ${msg.data}\x1b[0m\r\n`)
        }
      } catch {
        terminal.value?.write(event.data)
      }
    }

    socket.value.onclose = () => {
      connected.value = false
      connecting.value = false
      terminal.value?.write('\r\n\x1b[33mConnection closed\x1b[0m\r\n')
    }

    socket.value.onerror = (err) => {
      error.value = 'WebSocket connection failed'
      connecting.value = false
    }

    terminal.value?.onData((data) => {
      if (socket.value?.readyState === WebSocket.OPEN) {
        socket.value.send(JSON.stringify({ type: 'input', data }))
      }
    })
  }

  function sendResize() {
    if (socket.value?.readyState === WebSocket.OPEN && terminal.value) {
      socket.value.send(
        JSON.stringify({
          type: 'resize',
          rows: terminal.value.rows,
          cols: terminal.value.cols,
        })
      )
    }
  }

  function fit() {
    fitAddon.value?.fit()
    sendResize()
  }

  function disconnect() {
    if (socket.value) {
      socket.value.close()
      socket.value = null
    }
    connected.value = false
  }

  function dispose() {
    disconnect()
    if (terminal.value) {
      try {
        terminal.value.dispose()
      } catch (e) {
        // Ignore dispose errors - addon may not be fully loaded
        console.warn('Terminal dispose warning:', e.message)
      }
      terminal.value = null
    }
    fitAddon.value = null
  }

  function clear() {
    terminal.value?.clear()
  }

  function write(data) {
    terminal.value?.write(data)
  }

  return {
    terminal,
    connected,
    connecting,
    error,
    createTerminal,
    connect,
    connectToContainer,
    fit,
    disconnect,
    dispose,
    clear,
    write,
  }
}
