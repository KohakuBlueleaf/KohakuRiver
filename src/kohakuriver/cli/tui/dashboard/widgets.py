"""
Reusable widgets for the TUI Dashboard.
"""

from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from kohakuriver.cli.tui.dashboard.styles import get_status_style


class HeaderBar(Widget):
    """Application header bar with title and datetime."""

    DEFAULT_CSS = """
    HeaderBar {
        dock: top;
        height: 3;
        background: #1a1a2e;
        padding: 0 1;
        layout: horizontal;
    }

    HeaderBar > .title {
        width: 1fr;
        text-style: bold;
        color: #00d4ff;
        content-align: left middle;
    }

    HeaderBar > .datetime {
        width: auto;
        color: #888;
        content-align: right middle;
    }
    """

    def __init__(self, title: str = "KohakuRiver Cluster Manager") -> None:
        super().__init__()
        self._title = title

    def compose(self) -> ComposeResult:
        yield Static(self._title, classes="title")
        yield Static(
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            classes="datetime",
            id="header-time",
        )

    def update_time(self) -> None:
        """Update the time display."""
        try:
            time_widget = self.query_one("#header-time", Static)
            time_widget.update(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            pass


class FooterBar(Widget):
    """Application footer with keybindings help."""

    DEFAULT_CSS = """
    FooterBar {
        dock: bottom;
        height: 1;
        background: #1a1a2e;
        padding: 0 1;
        layout: horizontal;
    }
    """

    def __init__(self, keys: list[tuple[str, str]] | None = None) -> None:
        super().__init__()
        self._keys = keys or []

    def compose(self) -> ComposeResult:
        text = Text()
        for i, (key, action) in enumerate(self._keys):
            if i > 0:
                text.append("  ", style="dim")
            text.append(key, style="bold")
            text.append(f"-{action}", style="dim")
        yield Static(text, id="footer-text")

    def update_keys(self, keys: list[tuple[str, str]]) -> None:
        """Update the displayed keybindings."""
        self._keys = keys
        text = Text()
        for i, (key, action) in enumerate(keys):
            if i > 0:
                text.append("  ", style="dim")
            text.append(key, style="bold")
            text.append(f"-{action}", style="dim")

        try:
            static = self.query_one("#footer-text", Static)
            static.update(text)
        except Exception:
            pass


class SummaryCard(Widget):
    """A card showing a label and value."""

    DEFAULT_CSS = """
    SummaryCard {
        height: auto;
        min-height: 3;
        border: solid #333;
        padding: 0 1;
        margin: 0 1 0 0;
        width: 1fr;
        layout: vertical;
    }

    SummaryCard > .card-label {
        color: #888;
    }

    SummaryCard > .card-value {
        text-style: bold;
        color: #00d4ff;
    }
    """

    def __init__(
        self,
        label: str,
        value: str = "0",
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._label = label
        self._value = value

    def compose(self) -> ComposeResult:
        yield Static(self._label, classes="card-label")
        yield Static(self._value, classes="card-value", id="card-value")

    def update_value(self, value: str) -> None:
        """Update the card value."""
        self._value = value
        try:
            value_widget = self.query_one("#card-value", Static)
            value_widget.update(value)
        except Exception:
            pass


class StatusText(Widget):
    """A text widget that shows status with color."""

    def __init__(self, status: str) -> None:
        super().__init__()
        self._status = status

    def compose(self) -> ComposeResult:
        style = get_status_style(self._status)
        yield Static(Text(self._status, style=style), id="status-text")

    def update_status(self, status: str) -> None:
        """Update the status."""
        self._status = status
        style = get_status_style(status)
        try:
            static = self.query_one("#status-text", Static)
            static.update(Text(status, style=style))
        except Exception:
            pass


def create_status_text(status: str) -> Text:
    """Create a Rich Text object with status colored appropriately."""
    style = get_status_style(status)
    return Text(status, style=style)


def truncate_id(task_id: str, length: int = 20) -> str:
    """Truncate a task ID to specified length from the end."""
    task_id = str(task_id)
    if len(task_id) <= length:
        return task_id
    return task_id[-length:]
