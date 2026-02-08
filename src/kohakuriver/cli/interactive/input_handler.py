"""Non-blocking terminal input reader with escape sequence handling."""

import select
import sys


class InputReader:
    """Non-blocking input reader with proper escape sequence handling."""

    def __init__(self):
        self.buffer = []

    def read_key(self, timeout: float = 0.1) -> str | None:
        """Read a key with proper escape sequence handling."""
        # Check if input available
        if not select.select([sys.stdin], [], [], timeout)[0]:
            return None

        # Read first character
        ch = sys.stdin.read(1)

        # Handle escape sequences
        if ch == "\x1b":
            # Wait a bit longer for the rest of escape sequence
            # SSH may have latency, so use longer timeout
            if select.select([sys.stdin], [], [], 0.1)[0]:
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    return self._parse_csi_sequence()
                elif ch2 == "O":
                    return self._parse_ss3_sequence()
                else:
                    # Alt+key combination
                    return f"alt+{ch2}"
            else:
                # Just escape key pressed
                return "escape"

        return ch

    def _parse_csi_sequence(self) -> str:
        """Parse a CSI (Control Sequence Introducer) escape sequence."""
        seq = ""
        while True:
            if select.select([sys.stdin], [], [], 0.05)[0]:
                ch3 = sys.stdin.read(1)
                seq += ch3
                # CSI sequences end with a letter or ~
                if ch3.isalpha() or ch3 == "~":
                    break
            else:
                break

        # Parse common sequences
        if seq == "A":
            return "up"
        elif seq == "B":
            return "down"
        elif seq == "C":
            return "right"
        elif seq == "D":
            return "left"
        elif seq == "H":
            return "home"
        elif seq == "F":
            return "end"
        elif seq.endswith("~"):
            # Handle sequences like 1~, 4~, 5~, 6~
            num = seq[:-1]
            if num == "1":
                return "home"
            elif num == "4":
                return "end"
            elif num == "5":
                return "pageup"
            elif num == "6":
                return "pagedown"
            elif num == "3":
                return "delete"
        return f"esc[{seq}"  # Unknown sequence

    def _parse_ss3_sequence(self) -> str:
        """Parse an SS3 escape sequence (some terminals use for arrow keys)."""
        if select.select([sys.stdin], [], [], 0.05)[0]:
            ch3 = sys.stdin.read(1)
            if ch3 == "A":
                return "up"
            elif ch3 == "B":
                return "down"
            elif ch3 == "C":
                return "right"
            elif ch3 == "D":
                return "left"
        return "escape"
