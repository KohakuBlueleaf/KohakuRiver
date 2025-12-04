"""
Tunnel protocol definitions and utilities.

Wire format (binary, big-endian):
┌──────────┬──────────┬──────────┬──────────┬─────────────────────┐
│ Type (1B)│ Proto(1B)│ClientID  │ Port (2B)│  Payload (var)      │
│          │          │  (4B)    │          │                     │
└──────────┴──────────┴──────────┴──────────┴─────────────────────┘

Total header: 8 bytes
"""

import struct
from dataclasses import dataclass

# =============================================================================
# Message Types
# =============================================================================

MSG_CONNECT: int = 0x01  # Server → Client: open connection to port
MSG_CONNECTED: int = 0x02  # Client → Server: connection established
MSG_DATA: int = 0x03  # Bidirectional: relay data
MSG_CLOSE: int = 0x04  # Bidirectional: close connection
MSG_ERROR: int = 0x05  # Client → Server: connection failed
MSG_PING: int = 0x06  # Keepalive ping
MSG_PONG: int = 0x07  # Keepalive pong

# =============================================================================
# Protocol Types
# =============================================================================

PROTO_TCP: int = 0x00
PROTO_UDP: int = 0x01

# =============================================================================
# Header Format
# =============================================================================

# Header: type(1) + proto(1) + client_id(4) + port(2) = 8 bytes
HEADER_FORMAT = ">BBIH"  # Big-endian: byte, byte, uint32, uint16
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 8 bytes


@dataclass
class TunnelHeader:
    """Parsed tunnel message header."""

    msg_type: int
    proto: int
    client_id: int
    port: int


def build_message(
    msg_type: int,
    proto: int,
    client_id: int,
    port: int = 0,
    payload: bytes = b"",
) -> bytes:
    """
    Build a tunnel protocol message.

    Args:
        msg_type: Message type (MSG_CONNECT, MSG_DATA, etc.)
        proto: Protocol type (PROTO_TCP or PROTO_UDP)
        client_id: Connection identifier
        port: Target port (used in CONNECT messages)
        payload: Message payload data

    Returns:
        Complete message as bytes
    """
    header = struct.pack(HEADER_FORMAT, msg_type, proto, client_id, port)
    return header + payload


def parse_header(data: bytes) -> TunnelHeader | None:
    """
    Parse the header from a tunnel message.

    Args:
        data: Raw message bytes (must be at least HEADER_SIZE bytes)

    Returns:
        Parsed TunnelHeader or None if data too short
    """
    if len(data) < HEADER_SIZE:
        return None

    msg_type, proto, client_id, port = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    return TunnelHeader(msg_type=msg_type, proto=proto, client_id=client_id, port=port)


def get_payload(data: bytes) -> bytes:
    """
    Extract payload from a tunnel message.

    Args:
        data: Raw message bytes

    Returns:
        Payload bytes (everything after header)
    """
    return data[HEADER_SIZE:] if len(data) > HEADER_SIZE else b""
