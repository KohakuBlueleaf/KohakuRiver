"""
Terminal connect command for task/VPS containers.

Provides two connection modes:
1. Terminal mode (default): Raw terminal with full TTY support
2. IDE mode (--ide): Full TUI IDE with file tree, editor, and terminal

Cross-platform terminal support:
- POSIX (Linux/macOS): Uses termios/tty for raw mode
- Windows: Uses msvcrt for character input
"""

import asyncio
import json
import os
import signal
import sys
from typing import Annotated

import typer
import websockets
from websockets.exceptions import (
    ConnectionClosed,
    ConnectionClosedOK,
    ConnectionClosedError,
)

from kohakuriver.cli import client, config as cli_config
from kohakuriver.cli.output import console, print_error


# =============================================================================
# Platform Detection
# =============================================================================

IS_WINDOWS = sys.platform == "win32"

# Import platform-specific modules lazily to avoid import errors
if IS_WINDOWS:
    import msvcrt
else:
    import termios
    import tty


# =============================================================================
# Terminal Handling
# =============================================================================


class TerminalHandler:
    """
    Cross-platform terminal handler for raw mode input/output.

    Handles the differences between POSIX (termios/tty) and Windows (msvcrt)
    terminal control for interactive WebSocket terminal sessions.
    """

    def __init__(self):
        """Initialize terminal handler, saving original settings."""
        self._old_settings = None
        self._is_tty = sys.stdin.isatty()

    def enter_raw_mode(self) -> None:
        """
        Enter raw terminal mode.

        Raw mode sends all keystrokes directly without line buffering,
        allowing arrow keys, Ctrl+C, etc. to be forwarded to the container.
        """
        if not self._is_tty:
            return

        if IS_WINDOWS:
            # Windows doesn't need explicit raw mode setup for msvcrt
            pass
        else:
            # POSIX: Save settings and enter raw mode
            self._old_settings = termios.tcgetattr(sys.stdin)
            tty.setraw(sys.stdin.fileno())

    def exit_raw_mode(self) -> None:
        """Restore original terminal settings."""
        if not self._is_tty:
            return

        if IS_WINDOWS:
            # Windows: Nothing to restore
            pass
        else:
            # POSIX: Restore original settings
            if self._old_settings:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_settings)

    async def read_input(self) -> bytes:
        """
        Read raw input from terminal.

        Returns:
            Raw bytes from stdin, or empty bytes on EOF.
        """
        if IS_WINDOWS:
            return await self._read_input_windows()
        else:
            return await self._read_input_posix()

    async def _read_input_posix(self) -> bytes:
        """Read input on POSIX systems using os.read."""
        return await asyncio.to_thread(lambda: os.read(sys.stdin.fileno(), 1024))

    async def _read_input_windows(self) -> bytes:
        """
        Read input on Windows using msvcrt.

        Handles special keys (arrows, function keys) which return two bytes.
        """

        def read_windows():
            result = b""
            # Check if input is available
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                result = ch

                # Handle special keys (arrows, function keys, etc.)
                # They return \x00 or \xe0 followed by another byte
                if ch in (b"\x00", b"\xe0"):
                    if msvcrt.kbhit():
                        result += msvcrt.getch()

                # Convert Windows special keys to ANSI escape sequences
                result = _windows_key_to_ansi(result)

            return result

        # Poll for input with small delay to avoid busy waiting
        while True:
            data = await asyncio.to_thread(read_windows)
            if data:
                return data
            await asyncio.sleep(0.01)


def _windows_key_to_ansi(key_bytes: bytes) -> bytes:
    """
    Convert Windows special key codes to ANSI escape sequences.

    Windows uses different codes for arrow keys, etc.
    This converts them to standard ANSI sequences that terminals understand.

    Args:
        key_bytes: Raw bytes from msvcrt.getch()

    Returns:
        ANSI escape sequence bytes, or original bytes if not a special key.
    """
    # Windows special key mappings (prefix \xe0 or \x00)
    windows_to_ansi = {
        # Arrow keys (with \xe0 prefix)
        b"\xe0H": b"\x1b[A",  # Up
        b"\xe0P": b"\x1b[B",  # Down
        b"\xe0M": b"\x1b[C",  # Right
        b"\xe0K": b"\x1b[D",  # Left
        # Arrow keys (with \x00 prefix - some terminals)
        b"\x00H": b"\x1b[A",  # Up
        b"\x00P": b"\x1b[B",  # Down
        b"\x00M": b"\x1b[C",  # Right
        b"\x00K": b"\x1b[D",  # Left
        # Home/End/Insert/Delete/PageUp/PageDown
        b"\xe0G": b"\x1b[H",  # Home
        b"\xe0O": b"\x1b[F",  # End
        b"\xe0R": b"\x1b[2~",  # Insert
        b"\xe0S": b"\x1b[3~",  # Delete
        b"\xe0I": b"\x1b[5~",  # Page Up
        b"\xe0Q": b"\x1b[6~",  # Page Down
        # Function keys (F1-F12)
        b"\x00;": b"\x1bOP",  # F1
        b"\x00<": b"\x1bOQ",  # F2
        b"\x00=": b"\x1bOR",  # F3
        b"\x00>": b"\x1bOS",  # F4
        b"\x00?": b"\x1b[15~",  # F5
        b"\x00@": b"\x1b[17~",  # F6
        b"\x00A": b"\x1b[18~",  # F7
        b"\x00B": b"\x1b[19~",  # F8
        b"\x00C": b"\x1b[20~",  # F9
        b"\x00D": b"\x1b[21~",  # F10
        b"\xe0\x85": b"\x1b[23~",  # F11
        b"\xe0\x86": b"\x1b[24~",  # F12
    }

    return windows_to_ansi.get(key_bytes, key_bytes)


# =============================================================================
# CLI Command
# =============================================================================

app = typer.Typer(help="Connect to container terminal")


@app.callback(invoke_without_command=True)
def connect(
    task_id: Annotated[str, typer.Argument(help="Task or VPS ID to connect to")],
    ide: Annotated[
        bool,
        typer.Option(
            "--ide",
            "-i",
            help="Open TUI IDE with file tree, editor, and terminal",
        ),
    ] = False,
):
    """
    Connect to a running container's terminal.

    Works with both VPS containers and running task containers.

    Modes:
    - Terminal (default): Raw terminal with full TTY support for vim, htop, etc.
    - IDE (--ide): Full TUI IDE with file tree, code editor, and terminal panel.

    Exit terminal by typing 'exit' or pressing Ctrl+D.
    Exit IDE by pressing Ctrl+Q.
    """
    try:
        # Validate task exists and is running
        task = client.get_task_status(task_id)

        if not task:
            print_error(f"Task {task_id} not found.")
            raise typer.Exit(1)

        task_type = task.get("task_type")
        if task_type not in ("vps", "command"):
            print_error(f"Task {task_id} is not a container task (type: {task_type})")
            raise typer.Exit(1)

        status = task.get("status")
        if status != "running":
            print_error(f"Task is not running (status: {status})")
            raise typer.Exit(1)

        if ide:
            # Run TUI IDE mode
            _run_ide_mode(task_id, task_type)
        else:
            # Run terminal mode
            console.print(f"[dim]Connecting to {task_type} {task_id}...[/dim]")
            asyncio.run(_run_terminal_session(task_id))

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


def _run_ide_mode(task_id: str, task_type: str) -> None:
    """
    Run the TUI IDE mode.

    Args:
        task_id: Task ID to connect to
        task_type: Type of task ('vps' or 'command')
    """
    try:
        from kohakuriver.cli.tui import IdeApp

        console.print(f"[dim]Starting IDE for {task_type} {task_id}...[/dim]")

        app = IdeApp(
            host=cli_config.HOST_ADDRESS,
            port=cli_config.HOST_PORT,
            task_id=task_id,
            task_type=task_type,
        )
        app.run()

    except ImportError as e:
        print_error(f"TUI IDE requires additional dependencies: {e}")
        print_error("Please ensure 'textual' is installed: pip install textual")
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"IDE error: {e}")
        raise typer.Exit(1)


# =============================================================================
# WebSocket Terminal Session
# =============================================================================


async def _run_terminal_session(task_id: str):
    """
    Run interactive WebSocket terminal session with full TTY support.

    Supports:
    - Arrow keys, escape sequences
    - Ctrl+C (sent to container, not local)
    - TUI apps like vim, htop, nano, screen
    - Exit by typing 'exit' command in shell

    Args:
        task_id: The task ID to connect to.
    """
    # Construct WebSocket URL
    ws_url = f"ws://{cli_config.HOST_ADDRESS}:{cli_config.HOST_PORT}/ws/task/{task_id}/terminal"

    console.print(f"[dim]Connecting to {ws_url}...[/dim]")

    terminal = TerminalHandler()

    try:
        async with websockets.connect(ws_url) as websocket:
            # Send initial terminal size - server waits for this before starting I/O
            await _send_terminal_size(websocket)

            # Wait for server acknowledgment
            try:
                await asyncio.wait_for(websocket.recv(), timeout=3.0)
            except asyncio.TimeoutError:
                pass

            # Enter raw mode for full TTY forwarding
            terminal.enter_raw_mode()

            # Set up resize handling (POSIX only)
            resize_queue = asyncio.Queue()
            _setup_resize_handler(resize_queue)

            # Create concurrent tasks
            tasks = [
                asyncio.create_task(_receive_messages(websocket)),
                asyncio.create_task(_send_input(websocket, terminal)),
                asyncio.create_task(_send_resize(websocket, resize_queue)),
            ]

            # Wait for any task to complete (connection closed, etc.)
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )

            # Cancel remaining tasks
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    except OSError as e:
        print_error(f"Connection error: {e}")
    except Exception as e:
        print_error(f"WebSocket error: {e}")
    finally:
        terminal.exit_raw_mode()
        _cleanup_resize_handler()
        console.print("\r\n[dim]Disconnected.[/dim]")


async def _send_terminal_size(websocket) -> None:
    """Send current terminal size to the server."""
    if sys.stdout.isatty():
        try:
            size = os.get_terminal_size()
            resize_msg = {
                "type": "resize",
                "rows": size.lines,
                "cols": size.columns,
            }
            await websocket.send(json.dumps(resize_msg))
        except OSError:
            pass


def _setup_resize_handler(resize_queue: asyncio.Queue) -> None:
    """
    Set up terminal resize signal handler (POSIX only).

    Args:
        resize_queue: Queue to put resize events into.
    """
    if IS_WINDOWS:
        # Windows doesn't have SIGWINCH
        return

    def handle_resize(signum, frame):
        if sys.stdout.isatty():
            try:
                size = os.get_terminal_size()
                resize_queue.put_nowait((size.lines, size.columns))
            except Exception:
                pass

    if hasattr(signal, "SIGWINCH"):
        signal.signal(signal.SIGWINCH, handle_resize)


def _cleanup_resize_handler() -> None:
    """Reset resize signal handler to default."""
    if not IS_WINDOWS and hasattr(signal, "SIGWINCH"):
        signal.signal(signal.SIGWINCH, signal.SIG_DFL)


async def _receive_messages(websocket) -> None:
    """
    Receive messages from the WebSocket and write to stdout.

    Args:
        websocket: Active WebSocket connection.
    """
    try:
        while True:
            message_text = await websocket.recv()
            try:
                message = json.loads(message_text)
                if message.get("type") == "output" and message.get("data"):
                    # Write directly to stdout fd (works in raw mode)
                    os.write(
                        sys.stdout.fileno(),
                        message["data"].encode("utf-8", errors="replace"),
                    )
                elif message.get("type") == "error" and message.get("data"):
                    os.write(
                        sys.stdout.fileno(),
                        f"\r\nERROR: {message['data']}\r\n".encode(),
                    )
            except json.JSONDecodeError:
                os.write(sys.stdout.fileno(), message_text.encode())
    except (ConnectionClosedOK, ConnectionClosedError, ConnectionClosed):
        pass
    except Exception:
        pass


async def _send_input(websocket, terminal: TerminalHandler) -> None:
    """
    Read raw input from stdin and send to WebSocket.

    Args:
        websocket: Active WebSocket connection.
        terminal: Terminal handler for reading input.
    """
    try:
        while True:
            data = await terminal.read_input()
            if not data:
                # EOF
                break

            # Send all input including Ctrl+C (\x03), arrow keys, etc.
            message = {
                "type": "input",
                "data": data.decode("utf-8", errors="replace"),
            }
            await websocket.send(json.dumps(message))
    except (ConnectionClosed, ConnectionClosedOK, ConnectionClosedError):
        pass
    except Exception:
        pass


async def _send_resize(websocket, resize_queue: asyncio.Queue) -> None:
    """
    Send resize messages from queue to WebSocket.

    Args:
        websocket: Active WebSocket connection.
        resize_queue: Queue of (rows, cols) tuples.
    """
    try:
        while True:
            rows, cols = await resize_queue.get()
            msg = {"type": "resize", "rows": rows, "cols": cols}
            await websocket.send(json.dumps(msg))
    except Exception:
        pass
