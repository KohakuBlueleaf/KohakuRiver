//! Tunnel protocol definitions and utilities.
//!
//! Wire format (binary, big-endian):
//! ```text
//! ┌──────────┬──────────┬──────────┬──────────┬─────────────────────┐
//! │ Type (1B)│ Proto(1B)│ClientID  │ Port (2B)│  Payload (var)      │
//! │          │          │  (4B)    │          │                     │
//! └──────────┴──────────┴──────────┴──────────┴─────────────────────┘
//! ```
//! Total header: 8 bytes

use bytes::{BufMut, Bytes, BytesMut};
use thiserror::Error;

/// Header size in bytes
pub const HEADER_SIZE: usize = 8;

// =============================================================================
// Message Types
// =============================================================================

/// Message type constants
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum MsgType {
    /// Server → Client: open connection to port
    Connect = 0x01,
    /// Client → Server: connection established
    Connected = 0x02,
    /// Bidirectional: relay data
    Data = 0x03,
    /// Bidirectional: close connection
    Close = 0x04,
    /// Client → Server: connection failed
    Error = 0x05,
    /// Keepalive ping
    Ping = 0x06,
    /// Keepalive pong
    Pong = 0x07,
}

impl TryFrom<u8> for MsgType {
    type Error = ProtocolError;

    fn try_from(value: u8) -> Result<Self, <Self as TryFrom<u8>>::Error> {
        match value {
            0x01 => Ok(MsgType::Connect),
            0x02 => Ok(MsgType::Connected),
            0x03 => Ok(MsgType::Data),
            0x04 => Ok(MsgType::Close),
            0x05 => Ok(MsgType::Error),
            0x06 => Ok(MsgType::Ping),
            0x07 => Ok(MsgType::Pong),
            _ => Err(ProtocolError::InvalidMsgType(value)),
        }
    }
}

// =============================================================================
// Protocol Types
// =============================================================================

/// Protocol type (TCP or UDP)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum Proto {
    Tcp = 0x00,
    Udp = 0x01,
}

impl TryFrom<u8> for Proto {
    type Error = ProtocolError;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0x00 => Ok(Proto::Tcp),
            0x01 => Ok(Proto::Udp),
            _ => Err(ProtocolError::InvalidProto(value)),
        }
    }
}

impl std::fmt::Display for Proto {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Proto::Tcp => write!(f, "TCP"),
            Proto::Udp => write!(f, "UDP"),
        }
    }
}

// =============================================================================
// Protocol Errors
// =============================================================================

#[derive(Error, Debug)]
pub enum ProtocolError {
    #[error("Invalid message type: {0}")]
    InvalidMsgType(u8),

    #[error("Invalid protocol type: {0}")]
    InvalidProto(u8),

    #[error("Message too short: got {0} bytes, need at least {HEADER_SIZE}")]
    MessageTooShort(usize),
}

// =============================================================================
// Message Header
// =============================================================================

/// Parsed tunnel message header
#[derive(Debug, Clone)]
pub struct Header {
    pub msg_type: MsgType,
    pub proto: Proto,
    pub client_id: u32,
    pub port: u16,
}

impl Header {
    /// Parse header from bytes
    pub fn parse(data: &[u8]) -> Result<Self, ProtocolError> {
        if data.len() < HEADER_SIZE {
            return Err(ProtocolError::MessageTooShort(data.len()));
        }

        let msg_type = MsgType::try_from(data[0])?;
        let proto = Proto::try_from(data[1])?;
        let client_id = u32::from_be_bytes([data[2], data[3], data[4], data[5]]);
        let port = u16::from_be_bytes([data[6], data[7]]);

        Ok(Header {
            msg_type,
            proto,
            client_id,
            port,
        })
    }

    /// Write header to buffer
    pub fn write_to(&self, buf: &mut BytesMut) {
        buf.put_u8(self.msg_type as u8);
        buf.put_u8(self.proto as u8);
        buf.put_u32(self.client_id);
        buf.put_u16(self.port);
    }
}

// =============================================================================
// Message Building
// =============================================================================

/// Build a complete tunnel message
pub fn build_message(
    msg_type: MsgType,
    proto: Proto,
    client_id: u32,
    port: u16,
    payload: &[u8],
) -> Bytes {
    let mut buf = BytesMut::with_capacity(HEADER_SIZE + payload.len());

    let header = Header {
        msg_type,
        proto,
        client_id,
        port,
    };
    header.write_to(&mut buf);
    buf.put_slice(payload);

    buf.freeze()
}

/// Build a CONNECTED message
pub fn build_connected(proto: Proto, client_id: u32) -> Bytes {
    build_message(MsgType::Connected, proto, client_id, 0, &[])
}

/// Build a DATA message
pub fn build_data(proto: Proto, client_id: u32, data: &[u8]) -> Bytes {
    build_message(MsgType::Data, proto, client_id, 0, data)
}

/// Build a CLOSE message
pub fn build_close(proto: Proto, client_id: u32) -> Bytes {
    build_message(MsgType::Close, proto, client_id, 0, &[])
}

/// Build an ERROR message
pub fn build_error(proto: Proto, client_id: u32, error_msg: &str) -> Bytes {
    build_message(MsgType::Error, proto, client_id, 0, error_msg.as_bytes())
}

/// Build a PONG message (response to PING)
pub fn build_pong(client_id: u32) -> Bytes {
    build_message(MsgType::Pong, Proto::Tcp, client_id, 0, &[])
}

/// Extract payload from a message (everything after header)
pub fn get_payload(data: &[u8]) -> &[u8] {
    if data.len() > HEADER_SIZE {
        &data[HEADER_SIZE..]
    } else {
        &[]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_header_roundtrip() {
        let original = Header {
            msg_type: MsgType::Connect,
            proto: Proto::Tcp,
            client_id: 12345,
            port: 8080,
        };

        let mut buf = BytesMut::new();
        original.write_to(&mut buf);

        let parsed = Header::parse(&buf).unwrap();
        assert_eq!(parsed.msg_type, original.msg_type);
        assert_eq!(parsed.proto, original.proto);
        assert_eq!(parsed.client_id, original.client_id);
        assert_eq!(parsed.port, original.port);
    }

    #[test]
    fn test_build_message() {
        let msg = build_data(Proto::Tcp, 42, b"hello");
        assert_eq!(msg.len(), HEADER_SIZE + 5);

        let header = Header::parse(&msg).unwrap();
        assert_eq!(header.msg_type, MsgType::Data);
        assert_eq!(header.client_id, 42);

        let payload = get_payload(&msg);
        assert_eq!(payload, b"hello");
    }
}
