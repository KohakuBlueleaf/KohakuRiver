"""
File tree widget for TUI IDE.

Provides a navigable file tree with:
- Expandable directories
- File icons based on type
- Keyboard navigation
- File selection events
"""

from dataclasses import dataclass
from pathlib import Path

import httpx
from rich.text import Text
from textual import on
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Tree
from textual.widgets.tree import TreeNode


# =============================================================================
# File Icons
# =============================================================================

# File type to icon mapping (using unicode/emoji for cross-platform)
FILE_ICONS = {
    # Directories
    "directory": "📁",
    "directory_open": "📂",
    # Programming languages
    ".py": "🐍",
    ".js": "📜",
    ".ts": "📘",
    ".jsx": "⚛️",
    ".tsx": "⚛️",
    ".vue": "💚",
    ".go": "🔵",
    ".rs": "🦀",
    ".java": "☕",
    ".c": "🔷",
    ".cpp": "🔷",
    ".h": "🔷",
    ".cs": "🟣",
    ".rb": "💎",
    ".php": "🐘",
    ".swift": "🔶",
    ".kt": "🟠",
    ".r": "📊",
    ".lua": "🌙",
    ".pl": "🐪",
    ".sh": "🐚",
    ".bash": "🐚",
    ".zsh": "🐚",
    ".fish": "🐟",
    # Config files
    ".json": "📋",
    ".yaml": "📋",
    ".yml": "📋",
    ".toml": "📋",
    ".xml": "📋",
    ".ini": "⚙️",
    ".conf": "⚙️",
    ".config": "⚙️",
    ".env": "🔐",
    # Documents
    ".md": "📝",
    ".txt": "📄",
    ".rst": "📝",
    ".pdf": "📕",
    ".doc": "📘",
    ".docx": "📘",
    # Web
    ".html": "🌐",
    ".htm": "🌐",
    ".css": "🎨",
    ".scss": "🎨",
    ".sass": "🎨",
    ".less": "🎨",
    # Data
    ".csv": "📊",
    ".sql": "🗃️",
    ".sqlite": "🗃️",
    ".db": "🗃️",
    # Images
    ".png": "🖼️",
    ".jpg": "🖼️",
    ".jpeg": "🖼️",
    ".gif": "🖼️",
    ".svg": "🖼️",
    ".ico": "🖼️",
    ".webp": "🖼️",
    # Archives
    ".zip": "📦",
    ".tar": "📦",
    ".gz": "📦",
    ".7z": "📦",
    ".rar": "📦",
    # Executables
    ".exe": "⚡",
    ".bin": "⚡",
    ".so": "⚡",
    ".dll": "⚡",
    # Docker/DevOps
    "dockerfile": "🐳",
    "docker-compose": "🐳",
    ".dockerfile": "🐳",
    "makefile": "🔨",
    ".mk": "🔨",
    # Git
    ".gitignore": "🙈",
    ".gitattributes": "🙈",
    ".gitmodules": "🙈",
    # Default
    "default": "📄",
}


def get_file_icon(name: str, is_dir: bool, is_expanded: bool = False) -> str:
    """
    Get icon for a file or directory.

    Args:
        name: Filename
        is_dir: Whether it's a directory
        is_expanded: Whether directory is expanded (for open folder icon)

    Returns:
        Icon string
    """
    if is_dir:
        return FILE_ICONS["directory_open"] if is_expanded else FILE_ICONS["directory"]

    # Check special filenames first (case insensitive)
    name_lower = name.lower()
    if name_lower in ("dockerfile", "makefile"):
        return FILE_ICONS.get(name_lower, FILE_ICONS["default"])

    # Check by extension
    ext = Path(name).suffix.lower()
    return FILE_ICONS.get(ext, FILE_ICONS["default"])


# =============================================================================
# File Entry Data
# =============================================================================


@dataclass
class FileEntry:
    """
    Represents a file or directory entry.

    Attributes:
        name: Filename
        path: Absolute path
        type: 'file', 'directory', 'symlink', or 'other'
        size: File size in bytes
    """

    name: str
    path: str
    type: str
    size: int = 0

    @property
    def is_dir(self) -> bool:
        """Check if entry is a directory."""
        return self.type == "directory"


# =============================================================================
# File Tree Widget
# =============================================================================


class FileTreeWidget(Tree[FileEntry]):
    """
    File tree browser widget.

    Displays a hierarchical file tree with:
    - Lazy loading of directories
    - File icons
    - Keyboard navigation
    - Selection events

    Bindings:
        enter: Open selected file
        r: Refresh current directory
        n: Create new file (emits event)
        d: Delete selected (emits event)
    """

    BINDINGS = [
        Binding("enter", "select_node", "Open", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("n", "new_file", "New File", show=False),
        Binding("shift+n", "new_folder", "New Folder", show=False),
        Binding("d", "delete", "Delete", show=False),
    ]

    # -------------------------------------------------------------------------
    # Messages
    # -------------------------------------------------------------------------

    class FileSelected(Message):
        """Posted when a file is selected for opening."""

        def __init__(self, path: str, name: str) -> None:
            self.path = path
            self.name = name
            super().__init__()

    class NewFileRequested(Message):
        """Posted when new file creation is requested."""

        def __init__(self, parent_path: str) -> None:
            self.parent_path = parent_path
            super().__init__()

    class NewFolderRequested(Message):
        """Posted when new folder creation is requested."""

        def __init__(self, parent_path: str) -> None:
            self.parent_path = parent_path
            super().__init__()

    class DeleteRequested(Message):
        """Posted when deletion is requested."""

        def __init__(self, path: str, is_dir: bool) -> None:
            self.path = path
            self.is_dir = is_dir
            super().__init__()

    class RefreshRequested(Message):
        """Posted when refresh is requested."""

        def __init__(self, path: str) -> None:
            self.path = path
            super().__init__()

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------

    def __init__(
        self,
        host: str,
        port: int,
        task_id: str,
        root_paths: list[str] | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """
        Initialize file tree widget.

        Args:
            host: API host address
            port: API port
            task_id: Task ID for filesystem API
            root_paths: Root paths to show (default: ['/shared', '/local_temp', '/'])
            name: Widget name
            id: Widget ID
            classes: CSS classes
        """
        super().__init__(
            "Files",
            data=FileEntry(name="root", path="/", type="directory"),
            name=name,
            id=id,
            classes=classes,
        )

        self._host = host
        self._port = port
        self._task_id = task_id
        self._root_paths = root_paths or ["/shared", "/local_temp", "/"]
        self._http_client: httpx.AsyncClient | None = None

        # Cache for loaded directories
        self._dir_cache: dict[str, list[FileEntry]] = {}

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def compose(self):
        """Compose the widget (nothing extra needed for Tree)."""
        yield from super().compose()

    async def on_mount(self) -> None:
        """Initialize tree when mounted."""
        self._http_client = httpx.AsyncClient(timeout=30.0)
        await self._load_root_sections()

    async def on_unmount(self) -> None:
        """Cleanup when unmounted."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    # -------------------------------------------------------------------------
    # API Client
    # -------------------------------------------------------------------------

    def _get_api_url(self, endpoint: str) -> str:
        """Build API URL for filesystem endpoint."""
        return f"http://{self._host}:{self._port}/api/fs/{self._task_id}/{endpoint}"

    async def _list_directory(self, path: str) -> list[FileEntry]:
        """
        List directory contents via API.

        Args:
            path: Directory path to list

        Returns:
            List of file entries
        """
        if not self._http_client:
            return []

        try:
            response = await self._http_client.get(
                self._get_api_url("list"),
                params={"path": path, "show_hidden": "true"},
            )
            response.raise_for_status()
            data = response.json()

            entries = []
            for item in data.get("entries", []):
                entries.append(
                    FileEntry(
                        name=item["name"],
                        path=item["path"],
                        type=item["type"],
                        size=item.get("size", 0),
                    )
                )

            # Sort: directories first, then alphabetically
            entries.sort(key=lambda e: (0 if e.is_dir else 1, e.name.lower()))
            return entries

        except Exception as e:
            self.log.error(f"Failed to list directory {path}: {e}")
            return []

    # -------------------------------------------------------------------------
    # Tree Building
    # -------------------------------------------------------------------------

    async def _load_root_sections(self) -> None:
        """Load root sections (e.g., /shared, /local_temp, /)."""
        self.root.expand()

        for path in self._root_paths:
            # Create section node
            name = Path(path).name or "Root"
            if path == "/shared":
                name = "Shared"
            elif path == "/local_temp":
                name = "Local Temp"
            elif path == "/":
                name = "Root"

            entry = FileEntry(name=name, path=path, type="directory")
            label = self._create_label(entry, is_expanded=False)
            node = self.root.add(label, data=entry, expand=False, allow_expand=True)

            # Mark as not loaded yet
            node.set_label(label)

    def _create_label(self, entry: FileEntry, is_expanded: bool = False) -> Text:
        """
        Create rich text label for tree node.

        Args:
            entry: File entry
            is_expanded: Whether node is expanded

        Returns:
            Rich Text label
        """
        icon = get_file_icon(entry.name, entry.is_dir, is_expanded)
        text = Text()
        text.append(f"{icon} ")
        text.append(entry.name)
        return text

    async def _load_directory(self, node: TreeNode[FileEntry]) -> None:
        """
        Load directory contents into tree node.

        Args:
            node: Tree node to populate
        """
        if not node.data:
            return

        path = node.data.path

        # Check cache
        if path in self._dir_cache:
            entries = self._dir_cache[path]
        else:
            entries = await self._list_directory(path)
            self._dir_cache[path] = entries

        # Clear existing children
        node.remove_children()

        # Add entries
        for entry in entries:
            label = self._create_label(entry, is_expanded=False)
            child = node.add(
                label,
                data=entry,
                expand=False,
                allow_expand=entry.is_dir,
            )

    # -------------------------------------------------------------------------
    # Event Handlers
    # -------------------------------------------------------------------------

    @on(Tree.NodeExpanded)
    async def on_node_expanded(self, event: Tree.NodeExpanded[FileEntry]) -> None:
        """Handle node expansion - load directory contents."""
        event.stop()
        node = event.node

        if node.data and node.data.is_dir:
            # Update icon to open folder
            node.set_label(self._create_label(node.data, is_expanded=True))

            # Load children if not already loaded
            if not node.children:
                await self._load_directory(node)

    @on(Tree.NodeCollapsed)
    def on_node_collapsed(self, event: Tree.NodeCollapsed[FileEntry]) -> None:
        """Handle node collapse - update icon."""
        event.stop()
        node = event.node

        if node.data and node.data.is_dir:
            node.set_label(self._create_label(node.data, is_expanded=False))

    @on(Tree.NodeSelected)
    def on_node_selected(self, event: Tree.NodeSelected[FileEntry]) -> None:
        """Handle node selection - emit file selected if it's a file."""
        event.stop()
        node = event.node

        if node.data and not node.data.is_dir:
            self.post_message(self.FileSelected(node.data.path, node.data.name))

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    def action_select_node(self) -> None:
        """Action: select/open current node."""
        if self.cursor_node:
            if self.cursor_node.data:
                if self.cursor_node.data.is_dir:
                    self.cursor_node.toggle()
                else:
                    self.post_message(
                        self.FileSelected(
                            self.cursor_node.data.path, self.cursor_node.data.name
                        )
                    )

    async def action_refresh(self) -> None:
        """Action: refresh current directory."""
        if self.cursor_node and self.cursor_node.data:
            path = self.cursor_node.data.path
            if self.cursor_node.data.is_dir:
                # Refresh this directory
                self._dir_cache.pop(path, None)
                if self.cursor_node.is_expanded:
                    await self._load_directory(self.cursor_node)
            else:
                # Refresh parent directory
                parent_path = str(Path(path).parent)
                self._dir_cache.pop(parent_path, None)
                if self.cursor_node.parent and self.cursor_node.parent.is_expanded:
                    await self._load_directory(self.cursor_node.parent)

            self.post_message(self.RefreshRequested(path))

    def action_new_file(self) -> None:
        """Action: request new file creation."""
        if self.cursor_node and self.cursor_node.data:
            if self.cursor_node.data.is_dir:
                parent_path = self.cursor_node.data.path
            else:
                parent_path = str(Path(self.cursor_node.data.path).parent)
            self.post_message(self.NewFileRequested(parent_path))

    def action_new_folder(self) -> None:
        """Action: request new folder creation."""
        if self.cursor_node and self.cursor_node.data:
            if self.cursor_node.data.is_dir:
                parent_path = self.cursor_node.data.path
            else:
                parent_path = str(Path(self.cursor_node.data.path).parent)
            self.post_message(self.NewFolderRequested(parent_path))

    def action_delete(self) -> None:
        """Action: request deletion."""
        if self.cursor_node and self.cursor_node.data:
            entry = self.cursor_node.data
            # Don't allow deleting root sections
            if entry.path not in self._root_paths:
                self.post_message(self.DeleteRequested(entry.path, entry.is_dir))

    # -------------------------------------------------------------------------
    # Public Methods
    # -------------------------------------------------------------------------

    def clear_cache(self, path: str | None = None) -> None:
        """
        Clear directory cache.

        Args:
            path: Specific path to clear, or None for all
        """
        if path:
            self._dir_cache.pop(path, None)
        else:
            self._dir_cache.clear()

    async def refresh_path(self, path: str) -> None:
        """
        Refresh a specific path in the tree.

        Args:
            path: Path to refresh
        """
        self.clear_cache(path)

        # Find and refresh the node
        def find_node(
            node: TreeNode[FileEntry], target: str
        ) -> TreeNode[FileEntry] | None:
            if node.data and node.data.path == target:
                return node
            for child in node.children:
                result = find_node(child, target)
                if result:
                    return result
            return None

        node = find_node(self.root, path)
        if node and node.data and node.data.is_dir and node.is_expanded:
            await self._load_directory(node)
