"""
Main TUI IDE application.

Provides a terminal-based IDE with:
- File tree browser (left panel)
- Code editor with tabs (center/right panel)
- Terminal emulator (right/bottom panel or as tab)
- 3 layout modes
- Panel resize shortcuts

Layout Modes:
1. Side-by-side: File | Editor | Terminal (horizontal)
2. Tabbed: File | [Editor Tab | Terminal Tab]
3. Stacked: File | Editor (top) / Terminal (bottom)
"""

import asyncio
from enum import Enum

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Static,
    Footer,
    Header,
    Button,
    Input,
    Label,
    TabbedContent,
    TabPane,
)

from kohakuriver.cli.tui.file_tree import FileTreeWidget
from kohakuriver.cli.tui.editor import EditorPane
from kohakuriver.cli.tui.terminal import TerminalWidget


# =============================================================================
# Layout Mode
# =============================================================================


class LayoutMode(Enum):
    """IDE layout modes."""

    SIDE_BY_SIDE = "side"  # File | Editor | Terminal
    TABBED = "tabbed"  # File | [Editor | Terminal] tabs
    STACKED = "stacked"  # File | Editor / Terminal (vertical)


# =============================================================================
# Confirmation Dialog
# =============================================================================


class ConfirmDialog(ModalScreen[bool]):
    """Modal confirmation dialog."""

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }

    ConfirmDialog > #dialog {
        width: 60;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    ConfirmDialog > #dialog > #title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    ConfirmDialog > #dialog > #message {
        margin-bottom: 1;
    }

    ConfirmDialog > #dialog > #buttons {
        height: 3;
        align: center middle;
    }

    ConfirmDialog > #dialog > #buttons > Button {
        margin: 0 1;
    }
    """

    def __init__(self, title: str, message: str) -> None:
        self._title = title
        self._message = message
        super().__init__()

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label(self._title, id="title")
            yield Label(self._message, id="message")
            with Horizontal(id="buttons"):
                yield Button("Yes", variant="primary", id="yes")
                yield Button("No", variant="default", id="no")

    @on(Button.Pressed, "#yes")
    def on_yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def on_no(self) -> None:
        self.dismiss(False)

    def key_escape(self) -> None:
        self.dismiss(False)

    def key_enter(self) -> None:
        self.dismiss(True)


# =============================================================================
# Input Dialog
# =============================================================================


class InputDialog(ModalScreen[str | None]):
    """Modal input dialog."""

    DEFAULT_CSS = """
    InputDialog {
        align: center middle;
    }

    InputDialog > #dialog {
        width: 60;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    InputDialog > #dialog > #title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    InputDialog > #dialog > Input {
        margin-bottom: 1;
    }

    InputDialog > #dialog > #buttons {
        height: 3;
        align: center middle;
    }

    InputDialog > #dialog > #buttons > Button {
        margin: 0 1;
    }
    """

    def __init__(self, title: str, placeholder: str = "") -> None:
        self._title = title
        self._placeholder = placeholder
        super().__init__()

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label(self._title, id="title")
            yield Input(placeholder=self._placeholder, id="input")
            with Horizontal(id="buttons"):
                yield Button("OK", variant="primary", id="ok")
                yield Button("Cancel", variant="default", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#input", Input).focus()

    @on(Button.Pressed, "#ok")
    def on_ok(self) -> None:
        value = self.query_one("#input", Input).value
        self.dismiss(value if value else None)

    @on(Button.Pressed, "#cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def on_input_submitted(self) -> None:
        value = self.query_one("#input", Input).value
        self.dismiss(value if value else None)

    def key_escape(self) -> None:
        self.dismiss(None)


# =============================================================================
# Status Bar
# =============================================================================


class StatusBar(Static):
    """Status bar showing current file info, layout mode, and connection status."""

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__("")
        self._file_name: str | None = None
        self._is_dirty: bool = False
        self._connected: bool = False
        self._layout_mode: LayoutMode = LayoutMode.SIDE_BY_SIDE

    def update_file(self, name: str | None, is_dirty: bool = False) -> None:
        self._file_name = name
        self._is_dirty = is_dirty
        self._refresh_display()

    def update_connection(self, connected: bool) -> None:
        self._connected = connected
        self._refresh_display()

    def update_layout(self, mode: LayoutMode) -> None:
        self._layout_mode = mode
        self._refresh_display()

    def _refresh_display(self) -> None:
        parts = []

        # Connection status
        if self._connected:
            parts.append("● Connected")
        else:
            parts.append("○ Disconnected")

        # Layout mode
        mode_names = {
            LayoutMode.SIDE_BY_SIDE: "Side-by-Side",
            LayoutMode.TABBED: "Tabbed",
            LayoutMode.STACKED: "Stacked",
        }
        parts.append(f"[{mode_names[self._layout_mode]}]")

        # File info
        if self._file_name:
            dirty = "● " if self._is_dirty else ""
            parts.append(f"{dirty}{self._file_name}")

        parts.append("Ctrl+L: Layout")

        self.update(" │ ".join(parts))


# =============================================================================
# Main IDE App
# =============================================================================


class IdeApp(App):
    """
    Main TUI IDE application with 3 layout modes.

    Layout Modes (Ctrl+L to cycle):
    1. Side-by-side: File | Editor | Terminal
    2. Tabbed: File | [Editor Tab | Terminal Tab]
    3. Stacked: File | Editor (top) / Terminal (bottom)

    Panel Resize:
    - Ctrl+Alt+Left/Right: Resize file tree width
    - Ctrl+Alt+Up/Down: Resize terminal height (stacked mode)
    - Ctrl+Shift+Left/Right: Resize editor/terminal split (side-by-side)
    """

    CSS = """
    /* Main layout */
    #main-container {
        width: 100%;
        height: 1fr;
    }

    /* File tree panel */
    #file-tree-container {
        height: 100%;
        border-right: solid $primary-darken-2;
    }

    #file-tree-container.hidden {
        display: none;
    }

    /* Right panel (contains editor and/or terminal) */
    #right-panel {
        width: 1fr;
        height: 100%;
    }

    /* Side-by-side mode */
    #side-container {
        width: 100%;
        height: 100%;
    }

    #editor-panel-side {
        height: 100%;
        width: 1fr;
    }

    #terminal-panel-side {
        height: 100%;
        border-left: solid $primary-darken-2;
    }

    /* Tabbed mode */
    #tabbed-container {
        width: 100%;
        height: 100%;
    }

    #tabbed-container > #layout-tabs {
        width: 100%;
        height: 100%;
    }

    #tabbed-container TabbedContent {
        width: 100%;
        height: 100%;
    }

    #tabbed-container ContentSwitcher {
        width: 100%;
        height: 1fr;
    }

    #tabbed-container TabPane {
        width: 100%;
        height: 100%;
        padding: 0;
    }

    #tab-editor {
        width: 100%;
        height: 100%;
    }

    #tab-terminal {
        width: 100%;
        height: 100%;
    }

    /* Stacked mode */
    #stacked-container {
        width: 100%;
        height: 100%;
    }

    #editor-panel-stacked {
        width: 100%;
    }

    #terminal-panel-stacked {
        width: 100%;
        border-top: solid $primary-darken-2;
    }

    /* Widget sizing */
    FileTreeWidget {
        height: 100%;
        width: 100%;
    }

    EditorPane {
        height: 100%;
        width: 100%;
    }

    TerminalWidget {
        height: 100%;
        width: 100%;
    }

    /* Hide inactive layouts */
    .layout-hidden {
        display: none;
    }
    """

    BINDINGS = [
        Binding("ctrl+b", "toggle_file_tree", "Toggle Files", show=True),
        Binding("ctrl+l", "cycle_layout", "Layout", show=True),
        Binding("ctrl+s", "save_file", "Save", show=True),
        Binding("ctrl+w", "close_file", "Close", show=False),
        Binding("ctrl+q", "quit_ide", "Quit", show=True),
        Binding("ctrl+n", "new_file", "New File", show=False),
        Binding("f5", "refresh", "Refresh", show=True),
        # Panel resize shortcuts
        Binding(
            "ctrl+alt+left",
            "shrink_file_tree",
            "Shrink Files",
            show=False,
            priority=True,
        ),
        Binding(
            "ctrl+alt+right",
            "expand_file_tree",
            "Expand Files",
            show=False,
            priority=True,
        ),
        Binding(
            "ctrl+shift+left",
            "shrink_terminal_width",
            "Shrink Term",
            show=False,
            priority=True,
        ),
        Binding(
            "ctrl+shift+right",
            "expand_terminal_width",
            "Expand Term",
            show=False,
            priority=True,
        ),
        Binding(
            "ctrl+shift+up",
            "shrink_terminal_height",
            "Term Up",
            show=False,
            priority=True,
        ),
        Binding(
            "ctrl+shift+down",
            "expand_terminal_height",
            "Term Down",
            show=False,
            priority=True,
        ),
    ]

    TITLE = "KohakuRiver IDE"

    def __init__(
        self,
        host: str,
        port: int,
        task_id: str,
        task_type: str = "vps",
    ) -> None:
        super().__init__()

        self._host = host
        self._port = port
        self._task_id = task_id
        self._task_type = task_type

        # Layout state
        self._layout_mode = LayoutMode.SIDE_BY_SIDE
        self._show_file_tree = True

        # Panel sizes (in characters/rows)
        self._file_tree_width = 25
        self._terminal_width = 50  # For side-by-side
        self._terminal_height = 15  # For stacked (percentage)
        self._editor_height = 70  # For stacked (percentage)

        # Widget references
        self._file_tree: FileTreeWidget | None = None
        self._status_bar: StatusBar | None = None

        # Multiple editors/terminals for different layouts
        self._editors: dict[str, EditorPane] = {}
        self._terminals: dict[str, TerminalWidget] = {}

    def compose(self) -> ComposeResult:
        yield Header()

        root_paths = (
            ["/shared", "/local_temp", "/"] if self._task_type == "vps" else ["/"]
        )

        with Horizontal(id="main-container"):
            # File tree panel
            with Container(id="file-tree-container"):
                self._file_tree = FileTreeWidget(
                    self._host,
                    self._port,
                    self._task_id,
                    root_paths=root_paths,
                    id="file-tree",
                )
                yield self._file_tree

            # Right panel with all 3 layout options
            with Container(id="right-panel"):
                # Layout 1: Side-by-side
                with Horizontal(id="side-container"):
                    with Container(id="editor-panel-side"):
                        editor_side = EditorPane(
                            self._host, self._port, self._task_id, id="editor-side"
                        )
                        self._editors["side"] = editor_side
                        yield editor_side
                    with Container(id="terminal-panel-side"):
                        term_side = TerminalWidget(
                            self._host, self._port, self._task_id, id="terminal-side"
                        )
                        self._terminals["side"] = term_side
                        yield term_side

                # Layout 2: Tabbed
                with Container(id="tabbed-container", classes="layout-hidden"):
                    with TabbedContent(id="layout-tabs"):
                        with TabPane("Editor", id="tab-editor"):
                            editor_tab = EditorPane(
                                self._host, self._port, self._task_id, id="editor-tab"
                            )
                            self._editors["tab"] = editor_tab
                            yield editor_tab
                        with TabPane("Terminal", id="tab-terminal"):
                            term_tab = TerminalWidget(
                                self._host, self._port, self._task_id, id="terminal-tab"
                            )
                            self._terminals["tab"] = term_tab
                            yield term_tab

                # Layout 3: Stacked
                with Vertical(id="stacked-container", classes="layout-hidden"):
                    with Container(id="editor-panel-stacked"):
                        editor_stack = EditorPane(
                            self._host, self._port, self._task_id, id="editor-stack"
                        )
                        self._editors["stack"] = editor_stack
                        yield editor_stack
                    with Container(id="terminal-panel-stacked"):
                        term_stack = TerminalWidget(
                            self._host, self._port, self._task_id, id="terminal-stack"
                        )
                        self._terminals["stack"] = term_stack
                        yield term_stack

        self._status_bar = StatusBar()
        yield self._status_bar

        yield Footer()

    def on_mount(self) -> None:
        """Apply initial layout sizes."""
        self._apply_sizes()
        if self._status_bar:
            self._status_bar.update_layout(self._layout_mode)

    def _apply_sizes(self) -> None:
        """Apply current panel sizes."""
        # File tree width
        try:
            ft_container = self.query_one("#file-tree-container", Container)
            ft_container.styles.width = self._file_tree_width
        except Exception:
            pass

        # Side-by-side terminal width
        try:
            term_side = self.query_one("#terminal-panel-side", Container)
            term_side.styles.width = self._terminal_width
        except Exception:
            pass

        # Stacked heights
        try:
            editor_stack = self.query_one("#editor-panel-stacked", Container)
            term_stack = self.query_one("#terminal-panel-stacked", Container)
            editor_stack.styles.height = f"{self._editor_height}%"
            term_stack.styles.height = f"{100 - self._editor_height}%"
        except Exception:
            pass

    def _get_active_editor(self) -> EditorPane | None:
        """Get the editor for the current layout mode."""
        mode_key = {
            LayoutMode.SIDE_BY_SIDE: "side",
            LayoutMode.TABBED: "tab",
            LayoutMode.STACKED: "stack",
        }
        return self._editors.get(mode_key[self._layout_mode])

    def _get_active_terminal(self) -> TerminalWidget | None:
        """Get the terminal for the current layout mode."""
        mode_key = {
            LayoutMode.SIDE_BY_SIDE: "side",
            LayoutMode.TABBED: "tab",
            LayoutMode.STACKED: "stack",
        }
        return self._terminals.get(mode_key[self._layout_mode])

    # -------------------------------------------------------------------------
    # Layout Actions
    # -------------------------------------------------------------------------

    def action_cycle_layout(self) -> None:
        """Cycle through layout modes."""
        modes = list(LayoutMode)
        current_idx = modes.index(self._layout_mode)
        next_idx = (current_idx + 1) % len(modes)
        self._layout_mode = modes[next_idx]

        # Update visibility
        side = self.query_one("#side-container")
        tabbed = self.query_one("#tabbed-container")
        stacked = self.query_one("#stacked-container")

        side.set_class(self._layout_mode != LayoutMode.SIDE_BY_SIDE, "layout-hidden")
        tabbed.set_class(self._layout_mode != LayoutMode.TABBED, "layout-hidden")
        stacked.set_class(self._layout_mode != LayoutMode.STACKED, "layout-hidden")

        if self._status_bar:
            self._status_bar.update_layout(self._layout_mode)

        self.notify(f"Layout: {self._layout_mode.value}")

    def action_toggle_file_tree(self) -> None:
        """Toggle file tree visibility."""
        self._show_file_tree = not self._show_file_tree
        container = self.query_one("#file-tree-container", Container)
        container.set_class(not self._show_file_tree, "hidden")

    # -------------------------------------------------------------------------
    # Panel Resize Actions
    # -------------------------------------------------------------------------

    def action_shrink_file_tree(self) -> None:
        """Shrink file tree width."""
        self._file_tree_width = max(15, self._file_tree_width - 3)
        self._apply_sizes()

    def action_expand_file_tree(self) -> None:
        """Expand file tree width."""
        self._file_tree_width = min(50, self._file_tree_width + 3)
        self._apply_sizes()

    def action_shrink_terminal_width(self) -> None:
        """Shrink terminal width (side-by-side mode)."""
        if self._layout_mode == LayoutMode.SIDE_BY_SIDE:
            self._terminal_width = max(20, self._terminal_width - 5)
            self._apply_sizes()

    def action_expand_terminal_width(self) -> None:
        """Expand terminal width (side-by-side mode)."""
        if self._layout_mode == LayoutMode.SIDE_BY_SIDE:
            self._terminal_width = min(100, self._terminal_width + 5)
            self._apply_sizes()

    def action_shrink_terminal_height(self) -> None:
        """Shrink terminal height / expand editor (stacked mode)."""
        if self._layout_mode == LayoutMode.STACKED:
            self._editor_height = min(85, self._editor_height + 5)
            self._apply_sizes()

    def action_expand_terminal_height(self) -> None:
        """Expand terminal height / shrink editor (stacked mode)."""
        if self._layout_mode == LayoutMode.STACKED:
            self._editor_height = max(30, self._editor_height - 5)
            self._apply_sizes()

    # -------------------------------------------------------------------------
    # File Tree Events
    # -------------------------------------------------------------------------

    @on(FileTreeWidget.FileSelected)
    async def on_file_selected(self, event: FileTreeWidget.FileSelected) -> None:
        """Handle file selection from tree."""
        event.stop()
        editor = self._get_active_editor()
        if editor:
            await editor.open_file(event.path, event.name)

    @on(FileTreeWidget.NewFileRequested)
    async def on_new_file_requested(
        self, event: FileTreeWidget.NewFileRequested
    ) -> None:
        event.stop()
        await self._create_new_item("file", event.parent_path)

    @on(FileTreeWidget.NewFolderRequested)
    async def on_new_folder_requested(
        self, event: FileTreeWidget.NewFolderRequested
    ) -> None:
        event.stop()
        await self._create_new_item("folder", event.parent_path)

    @on(FileTreeWidget.DeleteRequested)
    async def on_delete_requested(self, event: FileTreeWidget.DeleteRequested) -> None:
        event.stop()
        await self._delete_item(event.path, event.is_dir)

    # -------------------------------------------------------------------------
    # Editor Events
    # -------------------------------------------------------------------------

    @on(EditorPane.ActiveFileChanged)
    def on_active_file_changed(self, event: EditorPane.ActiveFileChanged) -> None:
        event.stop()
        if self._status_bar:
            editor = self._get_active_editor()
            file = editor.get_active_file() if editor else None
            self._status_bar.update_file(
                event.name,
                is_dirty=file.is_dirty if file else False,
            )

    @on(EditorPane.FileCloseRequested)
    async def on_file_close_requested(
        self, event: EditorPane.FileCloseRequested
    ) -> None:
        event.stop()
        if event.is_dirty:
            result = await self.push_screen_wait(
                ConfirmDialog(
                    "Unsaved Changes", "File has unsaved changes. Close anyway?"
                )
            )
            if result:
                editor = self._get_active_editor()
                if editor:
                    await editor.close_file(event.path, force=True)
        else:
            editor = self._get_active_editor()
            if editor:
                await editor.close_file(event.path)

    # -------------------------------------------------------------------------
    # Terminal Events
    # -------------------------------------------------------------------------

    @on(TerminalWidget.ConnectionStatusChanged)
    def on_terminal_connection_changed(
        self, event: TerminalWidget.ConnectionStatusChanged
    ) -> None:
        event.stop()
        if self._status_bar:
            self._status_bar.update_connection(event.connected)

    # -------------------------------------------------------------------------
    # File Actions
    # -------------------------------------------------------------------------

    async def action_save_file(self) -> None:
        """Save current file."""
        editor = self._get_active_editor()
        if editor:
            await editor.save_file()

    async def action_close_file(self) -> None:
        """Close current file."""
        editor = self._get_active_editor()
        if editor:
            file = editor.get_active_file()
            if file and file.is_dirty:
                result = await self.push_screen_wait(
                    ConfirmDialog("Unsaved Changes", f"Save changes to {file.name}?")
                )
                if result:
                    await editor.save_file()
            await editor.close_file()

    async def action_quit_ide(self) -> None:
        """Quit the IDE."""
        # Check all editors for unsaved changes
        all_dirty = []
        for editor in self._editors.values():
            all_dirty.extend(editor.get_dirty_files())

        if all_dirty:
            names = ", ".join(f.name for f in all_dirty[:3])
            if len(all_dirty) > 3:
                names += f" and {len(all_dirty) - 3} more"

            result = await self.push_screen_wait(
                ConfirmDialog(
                    "Unsaved Changes",
                    f"You have unsaved changes in: {names}\n\nQuit anyway?",
                )
            )
            if not result:
                return

        self.exit()

    async def action_new_file(self) -> None:
        """Create new file."""
        if self._file_tree and self._file_tree.cursor_node:
            node = self._file_tree.cursor_node
            if node.data:
                if node.data.is_dir:
                    parent_path = node.data.path
                else:
                    parent_path = str(__import__("pathlib").Path(node.data.path).parent)
                await self._create_new_item("file", parent_path)

    async def action_refresh(self) -> None:
        """Refresh file tree."""
        if self._file_tree:
            self._file_tree.clear_cache()
            self._file_tree.root.expand()

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    async def _create_new_item(self, item_type: str, parent_path: str) -> None:
        """Create a new file or folder."""
        title = f"New {'Folder' if item_type == 'folder' else 'File'}"
        placeholder = "folder-name" if item_type == "folder" else "filename.txt"

        name = await self.push_screen_wait(InputDialog(title, placeholder))

        if not name:
            return

        full_path = f"{parent_path}/{name}" if parent_path != "/" else f"/{name}"

        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                if item_type == "folder":
                    response = await client.post(
                        f"http://{self._host}:{self._port}/api/fs/{self._task_id}/mkdir",
                        json={"path": full_path, "parents": True},
                    )
                else:
                    response = await client.post(
                        f"http://{self._host}:{self._port}/api/fs/{self._task_id}/write",
                        json={"path": full_path, "content": "", "encoding": "utf-8"},
                    )

                response.raise_for_status()
                self.notify(f"Created {name}", severity="information")

                if self._file_tree:
                    await self._file_tree.refresh_path(parent_path)

            except Exception as e:
                self.notify(f"Failed to create: {e}", severity="error")

    async def _delete_item(self, path: str, is_dir: bool) -> None:
        """Delete a file or folder."""
        name = path.split("/")[-1]
        item_type = "folder" if is_dir else "file"

        result = await self.push_screen_wait(
            ConfirmDialog(
                "Delete Confirmation",
                f"Are you sure you want to delete {item_type} '{name}'?",
            )
        )

        if not result:
            return

        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.delete(
                    f"http://{self._host}:{self._port}/api/fs/{self._task_id}/delete",
                    params={"path": path, "recursive": "true" if is_dir else "false"},
                )
                response.raise_for_status()
                self.notify(f"Deleted {name}", severity="information")

                parent_path = str(__import__("pathlib").Path(path).parent)
                if self._file_tree:
                    await self._file_tree.refresh_path(parent_path)

            except Exception as e:
                self.notify(f"Failed to delete: {e}", severity="error")


# =============================================================================
# Run Function
# =============================================================================


def run_ide(host: str, port: int, task_id: str, task_type: str = "vps") -> None:
    """Run the TUI IDE application."""
    app = IdeApp(host, port, task_id, task_type)
    app.run()
