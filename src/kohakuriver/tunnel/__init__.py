"""
Tunnel system for dynamic port forwarding to containers.

This module provides the infrastructure for forwarding TCP/UDP connections
to services running inside Docker containers without port mapping.
"""

from kohakuriver.tunnel.protocol import (
    HEADER_SIZE,
    MSG_CLOSE,
    MSG_CONNECT,
    MSG_CONNECTED,
    MSG_DATA,
    MSG_ERROR,
    MSG_PING,
    MSG_PONG,
    PROTO_TCP,
    PROTO_UDP,
    build_message,
    parse_header,
)

__all__ = [
    "HEADER_SIZE",
    "MSG_CONNECT",
    "MSG_CONNECTED",
    "MSG_DATA",
    "MSG_CLOSE",
    "MSG_ERROR",
    "MSG_PING",
    "MSG_PONG",
    "PROTO_TCP",
    "PROTO_UDP",
    "build_message",
    "parse_header",
]
