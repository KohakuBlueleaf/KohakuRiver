"""
Code editor widget for TUI IDE.

Provides a text editor with:
- Syntax highlighting
- Line numbers
- Dirty state tracking
- Tab management
- Save functionality
"""

from dataclasses import dataclass
from pathlib import Path

import httpx
from textual import on, work
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static, TextArea, TabbedContent, TabPane, Button, Label


# =============================================================================
# Language Detection
# =============================================================================

EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".pyw": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".lua": "lua",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".md": "markdown",
    ".markdown": "markdown",
    ".sql": "sql",
    ".dockerfile": "dockerfile",
    ".makefile": "makefile",
    ".mk": "makefile",
}


def detect_language(filename: str) -> str | None:
    """
    Detect language from filename for syntax highlighting.

    Returns None for unknown languages (TextArea will use plain text).
    """
    name_lower = filename.lower()

    if name_lower == "dockerfile":
        return "dockerfile"
    if name_lower in ("makefile", "gnumakefile"):
        return "makefile"

    ext = Path(filename).suffix.lower()
    return EXTENSION_TO_LANGUAGE.get(ext)


# =============================================================================
# Open File Data
# =============================================================================


@dataclass
class OpenFile:
    """Represents an open file in the editor."""

    path: str
    name: str
    content: str = ""
    original_content: str = ""
    language: str | None = None
    encoding: str = "utf-8"

    @property
    def is_dirty(self) -> bool:
        """Check if file has unsaved changes."""
        return self.content != self.original_content


# =============================================================================
# Editor Pane
# =============================================================================


class EditorPane(Widget):
    """
    Multi-tab code editor pane.

    Features:
    - Open multiple files in tabs
    - Syntax highlighting
    - Save with Ctrl+S
    - Close tabs
    - Dirty state tracking
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True, priority=True),
        Binding("ctrl+w", "close_tab", "Close Tab", show=False),
    ]

    DEFAULT_CSS = """
    EditorPane {
        height: 100%;
        width: 100%;
    }

    EditorPane > #editor-empty {
        height: 100%;
        width: 100%;
        content-align: center middle;
        color: $text-muted;
    }

    EditorPane > #editor-tabs {
        height: 100%;
        width: 100%;
    }

    EditorPane TabbedContent {
        height: 100%;
    }

    EditorPane ContentSwitcher {
        height: 1fr;
    }

    EditorPane TabPane {
        height: 100%;
        padding: 0;
    }

    EditorPane TextArea {
        height: 100%;
        width: 100%;
    }
    """

    # -------------------------------------------------------------------------
    # Messages
    # -------------------------------------------------------------------------

    class FileSaveRequested(Message):
        def __init__(self, path: str, content: str) -> None:
            self.path = path
            self.content = content
            super().__init__()

    class FileCloseRequested(Message):
        def __init__(self, path: str, is_dirty: bool) -> None:
            self.path = path
            self.is_dirty = is_dirty
            super().__init__()

    class ActiveFileChanged(Message):
        def __init__(self, path: str | None, name: str | None) -> None:
            self.path = path
            self.name = name
            super().__init__()

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------

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
        self._http_client: httpx.AsyncClient | None = None

        self._open_files: dict[str, OpenFile] = {}
        self._active_path: str | None = None
        self._text_areas: dict[str, TextArea] = {}

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def compose(self):
        """Compose the editor pane."""
        yield Static(
            "No files open\n\nDouble-click a file in the tree to edit",
            id="editor-empty",
        )
        yield TabbedContent(id="editor-tabs")

    async def on_mount(self) -> None:
        """Initialize HTTP client."""
        self._http_client = httpx.AsyncClient(timeout=30.0)
        # Hide content, show empty state
        self.query_one("#editor-tabs").display = False

    async def on_unmount(self) -> None:
        """Cleanup."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    # -------------------------------------------------------------------------
    # API
    # -------------------------------------------------------------------------

    def _get_api_url(self, endpoint: str) -> str:
        return f"http://{self._host}:{self._port}/api/fs/{self._task_id}/{endpoint}"

    async def _read_file(self, path: str) -> tuple[str, str, bool]:
        """Read file content. Returns (content, encoding, is_binary)."""
        if not self._http_client:
            return "", "utf-8", False

        try:
            response = await self._http_client.get(
                self._get_api_url("read"),
                params={"path": path, "encoding": "utf-8", "limit": "10485760"},
            )
            response.raise_for_status()
            data = response.json()
            return (
                data.get("content", ""),
                data.get("encoding", "utf-8"),
                data.get("is_binary", False),
            )
        except Exception as e:
            self.notify(f"Failed to read file: {e}", severity="error")
            return "", "utf-8", False

    async def _write_file(self, path: str, content: str) -> bool:
        """Write file content."""
        if not self._http_client:
            return False

        try:
            response = await self._http_client.post(
                self._get_api_url("write"),
                json={"path": path, "content": content, "encoding": "utf-8"},
            )
            response.raise_for_status()
            return True
        except Exception as e:
            self.notify(f"Failed to save file: {e}", severity="error")
            return False

    # -------------------------------------------------------------------------
    # Utility
    # -------------------------------------------------------------------------

    @staticmethod
    def _path_to_id(path: str) -> str:
        """Convert path to valid widget ID."""
        # Use absolute value of hash to avoid negative numbers
        return f"tab-{abs(hash(path))}"

    def _update_visibility(self) -> None:
        """Update visibility of empty state vs content."""
        has_files = len(self._open_files) > 0
        self.query_one("#editor-empty").display = not has_files
        self.query_one("#editor-tabs").display = has_files

    # -------------------------------------------------------------------------
    # Event Handlers
    # -------------------------------------------------------------------------

    @on(TabbedContent.TabActivated)
    def on_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Handle tab switch."""
        event.stop()
        # Find which file this tab belongs to
        for path, file in self._open_files.items():
            if self._path_to_id(path) == event.pane.id:
                self._active_path = path
                self.post_message(self.ActiveFileChanged(path, file.name))
                break

    @on(TextArea.Changed)
    def on_text_changed(self, event: TextArea.Changed) -> None:
        """Handle text content change."""
        event.stop()
        # Find which file this textarea belongs to
        for path, text_area in self._text_areas.items():
            if text_area is event.text_area:
                if path in self._open_files:
                    self._open_files[path].content = text_area.text
                    # Update tab label to show dirty indicator
                    self._update_tab_label(path)
                break

    # -------------------------------------------------------------------------
    # Public Methods
    # -------------------------------------------------------------------------

    async def open_file(self, path: str, name: str) -> bool:
        """Open a file in the editor."""
        # Check if already open
        if path in self._open_files:
            self._active_path = path
            try:
                tabs = self.query_one("#editor-tabs", TabbedContent)
                tabs.active = self._path_to_id(path)
            except Exception:
                pass
            self.post_message(self.ActiveFileChanged(path, name))
            return True

        # Read file content
        content, encoding, is_binary = await self._read_file(path)

        if is_binary:
            self.notify("Cannot edit binary files", severity="warning")
            return False

        # Create file entry
        language = detect_language(name)
        file = OpenFile(
            path=path,
            name=name,
            content=content,
            original_content=content,
            language=language,
            encoding=encoding,
        )
        self._open_files[path] = file
        self._active_path = path

        # Create tab with text area
        tab_id = self._path_to_id(path)
        tabs = self.query_one("#editor-tabs", TabbedContent)

        # Create the tab pane
        pane = TabPane(name, id=tab_id)
        await tabs.add_pane(pane)

        # Create text area with content and syntax highlighting
        text_area = TextArea(
            content,
            language=language,
            theme="vscode_dark",
            show_line_numbers=True,
            tab_behavior="indent",
        )
        self._text_areas[path] = text_area

        # Mount text area in pane
        await pane.mount(text_area)

        # Switch to new tab
        tabs.active = tab_id

        # Update visibility
        self._update_visibility()

        self.post_message(self.ActiveFileChanged(path, name))
        return True

    async def save_file(self, path: str | None = None) -> bool:
        """Save a file."""
        if path is None:
            path = self._active_path

        if not path or path not in self._open_files:
            return False

        file = self._open_files[path]

        # Get content from text area
        if path in self._text_areas:
            content = self._text_areas[path].text
        else:
            content = file.content

        # Write to server
        success = await self._write_file(path, content)

        if success:
            file.content = content
            file.original_content = content
            self._update_tab_label(path)
            self.notify(f"Saved {file.name}", severity="information")
        else:
            self.notify(f"Failed to save {file.name}", severity="error")

        return success

    async def close_file(self, path: str | None = None, force: bool = False) -> bool:
        """Close a file."""
        if path is None:
            path = self._active_path

        if not path or path not in self._open_files:
            return False

        file = self._open_files[path]

        if file.is_dirty and not force:
            self.post_message(self.FileCloseRequested(path, True))
            return False

        # Remove from tracking
        del self._open_files[path]
        if path in self._text_areas:
            del self._text_areas[path]

        # Remove tab
        tab_id = self._path_to_id(path)
        try:
            tabs = self.query_one("#editor-tabs", TabbedContent)
            pane = self.query_one(f"#{tab_id}", TabPane)
            await tabs.remove_pane(pane.id)
        except Exception:
            pass

        # Update active path
        if self._active_path == path:
            if self._open_files:
                self._active_path = next(iter(self._open_files.keys()))
                new_file = self._open_files[self._active_path]
                self.post_message(
                    self.ActiveFileChanged(self._active_path, new_file.name)
                )
            else:
                self._active_path = None
                self.post_message(self.ActiveFileChanged(None, None))

        # Update visibility
        self._update_visibility()

        return True

    def _update_tab_label(self, path: str) -> None:
        """Update tab label to show dirty indicator."""
        if path not in self._open_files:
            return

        file = self._open_files[path]
        tab_id = self._path_to_id(path)

        try:
            tabs = self.query_one("#editor-tabs", TabbedContent)
            # Textual's TabbedContent doesn't have a direct way to update labels
            # The dirty state will be reflected in status bar instead
        except Exception:
            pass

    def get_active_file(self) -> OpenFile | None:
        """Get currently active file."""
        if self._active_path:
            return self._open_files.get(self._active_path)
        return None

    def has_unsaved_changes(self) -> bool:
        """Check if any files have unsaved changes."""
        return any(f.is_dirty for f in self._open_files.values())

    def get_dirty_files(self) -> list[OpenFile]:
        """Get list of files with unsaved changes."""
        return [f for f in self._open_files.values() if f.is_dirty]

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    async def action_save(self) -> None:
        """Action: save current file."""
        await self.save_file()

    async def action_close_tab(self) -> None:
        """Action: close current tab."""
        await self.close_file()
