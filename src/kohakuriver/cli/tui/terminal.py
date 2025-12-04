"""
Terminal widget for TUI IDE.

Provides a terminal emulator connected via WebSocket:
- Full terminal emulation using pyte
- ANSI color and cursor support
- Input forwarding
- Terminal resize handling
"""

import asyncio
import json

import pyte
from rich.style import Style
from rich.text import Text
from textual import on, work
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static, Input, Button
from textual.containers import Horizontal

try:
    import websockets
    from websockets.exceptions import (
        ConnectionClosed,
        ConnectionClosedOK,
        ConnectionClosedError,
    )

    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False


# =============================================================================
# Color Mapping
# =============================================================================

# Map pyte color names to Rich color names
PYTE_TO_RICH_COLORS = {
    "black": "black",
    "red": "red",
    "green": "green",
    "brown": "yellow",
    "yellow": "yellow",
    "blue": "blue",
    "magenta": "magenta",
    "cyan": "cyan",
    "white": "white",
    "default": "default",
}


def pyte_char_to_rich_style(char: pyte.screens.Char) -> Style:
    """Convert pyte character attributes to Rich Style."""
    fg = PYTE_TO_RICH_COLORS.get(char.fg, "default")
    bg = PYTE_TO_RICH_COLORS.get(char.bg, "default")

    # Handle 256 colors (pyte uses strings like "0" to "255")
    if isinstance(char.fg, str) and char.fg.isdigit():
        fg = f"color({char.fg})"
    if isinstance(char.bg, str) and char.bg.isdigit():
        bg = f"color({char.bg})"

    return Style(
        color=fg if fg != "default" else None,
        bgcolor=bg if bg != "default" else None,
        bold=char.bold,
        italic=char.italics,
        underline=char.underscore,
        reverse=char.reverse,
        strike=char.strikethrough,
    )


# =============================================================================
# Terminal Screen Display
# =============================================================================


class TerminalScreen(Static):
    """
    Terminal screen display using pyte for emulation.

    Renders the pyte screen buffer as Rich Text with colors.
    """

    DEFAULT_CSS = """
    TerminalScreen {
        height: 1fr;
        width: 100%;
        background: #1e1e1e;
        color: #d4d4d4;
        overflow-y: auto;
        padding: 0;
    }
    """

    def __init__(
        self,
        rows: int = 24,
        cols: int = 80,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__("", name=name, id=id, classes=classes)
        self._rows = rows
        self._cols = cols
        self._screen = pyte.Screen(cols, rows)
        self._stream = pyte.Stream(self._screen)

    def resize_terminal(self, rows: int, cols: int) -> None:
        """Resize the terminal emulator."""
        self._rows = rows
        self._cols = cols
        self._screen.resize(rows, cols)

    def feed(self, data: str) -> None:
        """Feed data to the terminal emulator and refresh display."""
        self._stream.feed(data)
        self._refresh_display()

    def clear(self) -> None:
        """Clear the terminal."""
        self._screen.reset()
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Render the pyte screen buffer as Rich Text."""
        lines = []

        for y in range(self._screen.lines):
            line = Text()
            buffer = self._screen.buffer[y]

            for x in range(self._screen.columns):
                char = buffer[x]
                style = pyte_char_to_rich_style(char)
                line.append(char.data or " ", style=style)

            # Strip trailing spaces but keep at least empty line
            line.rstrip()
            lines.append(line)

        # Remove trailing empty lines
        while lines and not lines[-1].plain.strip():
            lines.pop()

        # Combine all lines
        result = Text("\n").join(lines) if lines else Text("")
        self.update(result)

    def get_size(self) -> tuple[int, int]:
        """Get current terminal size (rows, cols)."""
        return self._rows, self._cols


# =============================================================================
# Terminal Widget
# =============================================================================


class TerminalWidget(Widget):
    """
    Terminal widget with WebSocket connection.

    Features:
    - Full terminal emulation via pyte
    - ANSI color and cursor support
    - Input/output handling
    - Resize events
    """

    BINDINGS = [
        Binding("ctrl+l", "clear", "Clear", show=True),
    ]

    DEFAULT_CSS = """
    TerminalWidget {
        height: 100%;
        width: 100%;
    }

    TerminalWidget > #term-header {
        height: 1;
        width: 100%;
        background: #333;
        padding: 0 1;
    }

    TerminalWidget > #term-header > .term-title {
        width: 1fr;
    }

    TerminalWidget > #term-header > .term-status {
        width: auto;
    }

    TerminalWidget > #term-header > .term-status.connected {
        color: #4caf50;
    }

    TerminalWidget > #term-header > .term-status.disconnected {
        color: #f44336;
    }

    TerminalWidget > #term-screen {
        height: 1fr;
        width: 100%;
    }

    TerminalWidget > #term-input-row {
        height: 3;
        width: 100%;
        dock: bottom;
    }

    TerminalWidget > #term-input-row > #term-input {
        width: 1fr;
    }

    TerminalWidget > #term-input-row > #term-send {
        width: auto;
        min-width: 8;
    }
    """

    connected: reactive[bool] = reactive(False)
    connecting: reactive[bool] = reactive(False)

    class ConnectionStatusChanged(Message):
        """Posted when connection status changes."""

        def __init__(self, connected: bool, connecting: bool = False) -> None:
            self.connected = connected
            self.connecting = connecting
            super().__init__()

    def __init__(
        self,
        host: str,
        port: int,
        task_id: str,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)

        self._host = host
        self._port = port
        self._task_id = task_id

        self._websocket = None
        self._screen: TerminalScreen | None = None
        self._input: Input | None = None
        self._status: Static | None = None

    def compose(self):
        """Compose the terminal widget."""
        with Horizontal(id="term-header"):
            yield Static("Terminal", classes="term-title")
            self._status = Static("●", classes="term-status disconnected")
            yield self._status

        # Default size, will be resized on mount
        self._screen = TerminalScreen(rows=24, cols=80, id="term-screen")
        yield self._screen

        with Horizontal(id="term-input-row"):
            self._input = Input(placeholder="Command...", id="term-input")
            yield self._input
            yield Button("Send", variant="primary", id="term-send")

    async def on_mount(self) -> None:
        """Connect when mounted."""
        # Delay connect to allow layout to settle
        self.set_timer(0.1, self._delayed_connect)

    def _delayed_connect(self) -> None:
        """Connect after layout has settled."""
        # Resize terminal to fit widget
        self._resize_screen()

        if HAS_WEBSOCKETS:
            self.do_connect()
        else:
            self._write_message("[No WebSocket library]")

    async def on_unmount(self) -> None:
        """Disconnect when unmounted."""
        await self._disconnect()

    def _resize_screen(self) -> None:
        """Resize terminal screen to fit widget."""
        if self._screen:
            # Get the actual screen widget size if available
            try:
                screen_size = self._screen.size
                # Use content region which is more accurate
                cols = max(20, screen_size.width)
                rows = max(5, screen_size.height)
            except Exception:
                # Fallback to widget size minus header/input
                rows = max(5, self.size.height - 4)
                cols = max(20, self.size.width - 2)

            self._screen.resize_terminal(rows, cols)

    def _get_ws_url(self) -> str:
        """Build WebSocket URL."""
        return f"ws://{self._host}:{self._port}/ws/task/{self._task_id}/terminal"

    @work(exclusive=True, group="terminal-connect")
    async def do_connect(self) -> None:
        """Connect to terminal WebSocket."""
        self.connecting = True
        self.connected = False
        self._update_status_display()
        self._write_message("Connecting...")

        try:
            self._websocket = await websockets.connect(self._get_ws_url())

            # Send terminal size
            await self._send_resize()

            # Wait for acknowledgment
            try:
                ack = await asyncio.wait_for(self._websocket.recv(), timeout=3.0)
                # Process any initial output
                self._handle_message(ack)
            except asyncio.TimeoutError:
                pass

            self.connecting = False
            self.connected = True
            self._update_status_display()
            self.post_message(self.ConnectionStatusChanged(True))

            # Receive loop
            await self._receive_loop()

        except Exception as e:
            self.connecting = False
            self.connected = False
            self._update_status_display()
            self._write_message(f"Connection failed: {e}")
            self.post_message(self.ConnectionStatusChanged(False))

    async def _disconnect(self) -> None:
        """Disconnect from WebSocket."""
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception:
                pass
            self._websocket = None

        self.connected = False
        self.connecting = False
        self._update_status_display()

    async def _receive_loop(self) -> None:
        """Receive messages from WebSocket."""
        if not self._websocket:
            return

        try:
            async for message in self._websocket:
                self._handle_message(message)
        except (ConnectionClosed, ConnectionClosedOK, ConnectionClosedError):
            pass
        except Exception as e:
            self._write_message(f"Error: {e}")
        finally:
            self.connected = False
            self._update_status_display()
            self._write_message("Disconnected")
            self.post_message(self.ConnectionStatusChanged(False))

    def _handle_message(self, message: str) -> None:
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "output" and data.get("data"):
                if self._screen:
                    self._screen.feed(data["data"])
            elif msg_type == "error" and data.get("data"):
                self._write_message(f"ERROR: {data['data']}")

        except json.JSONDecodeError:
            # Raw data, feed directly
            if self._screen:
                self._screen.feed(message)

    async def _send_input(self, text: str) -> None:
        """Send input to terminal."""
        if not self._websocket or not self.connected:
            return

        try:
            # Send with newline for command execution
            message = {"type": "input", "data": text + "\n"}
            await self._websocket.send(json.dumps(message))
        except Exception as e:
            self._write_message(f"Send error: {e}")

    async def _send_resize(self) -> None:
        """Send terminal resize."""
        if not self._websocket or not self._screen:
            return

        try:
            rows, cols = self._screen.get_size()
            message = {"type": "resize", "rows": rows, "cols": cols}
            await self._websocket.send(json.dumps(message))
        except Exception:
            pass

    def _write_message(self, text: str) -> None:
        """Write a status message to the terminal."""
        if self._screen:
            self._screen.feed(f"\r\n*** {text} ***\r\n")

    def _update_status_display(self) -> None:
        """Update the status indicator."""
        if self._status:
            self._status.remove_class("connected", "disconnected")
            if self.connected:
                self._status.update("●")
                self._status.add_class("connected")
            else:
                self._status.update("●")
                self._status.add_class("disconnected")

    @on(Input.Submitted, "#term-input")
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        event.stop()
        if self._input and self._input.value:
            cmd = self._input.value
            self._input.value = ""
            await self._send_input(cmd)

    @on(Button.Pressed, "#term-send")
    async def on_send_pressed(self, event: Button.Pressed) -> None:
        """Handle send button."""
        event.stop()
        if self._input and self._input.value:
            cmd = self._input.value
            self._input.value = ""
            await self._send_input(cmd)

    async def on_resize(self, event) -> None:
        """Handle resize."""
        self._resize_screen()
        if self.connected:
            await self._send_resize()

    def action_clear(self) -> None:
        """Clear the terminal."""
        if self._screen:
            self._screen.clear()
