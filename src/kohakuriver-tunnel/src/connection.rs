//! Connection handling for TCP and UDP forwarding.
//!
//! Manages individual connections from the tunnel to local services.

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;

use anyhow::{Context, Result};
use bytes::Bytes;
use futures_util::stream::SplitSink;
use futures_util::SinkExt;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpStream, UdpSocket};
use tokio::sync::{mpsc, Mutex};
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::WebSocketStream;
use tracing::{debug, error, info, warn};

use crate::protocol::{self, Proto};

/// Type alias for the WebSocket sender
pub type WsSender = Arc<Mutex<SplitSink<WebSocketStream<tokio_tungstenite::MaybeTlsStream<TcpStream>>, Message>>>;

/// Represents an active connection with a channel for sending data
struct ActiveConnection {
    /// Channel to send data to the TCP/UDP writer
    data_tx: mpsc::Sender<Bytes>,
    /// Task handle for cleanup
    _handle: tokio::task::JoinHandle<()>,
}

/// Manages all active connections for this tunnel client
pub struct ConnectionManager {
    /// Map of client_id -> active connection
    connections: HashMap<u32, ActiveConnection>,
    /// WebSocket sender for sending messages back to runner
    ws_sender: WsSender,
}

impl ConnectionManager {
    pub fn new(ws_sender: WsSender) -> Self {
        Self {
            connections: HashMap::new(),
            ws_sender,
        }
    }

    /// Handle a CONNECT message - open connection to local service
    pub async fn handle_connect(&mut self, client_id: u32, proto: Proto, port: u16) {
        info!(
            client_id,
            port,
            proto = %proto,
            "Opening connection"
        );

        // Check if connection already exists
        if self.connections.contains_key(&client_id) {
            warn!(client_id, "Connection already exists, ignoring duplicate CONNECT");
            return;
        }

        // Create channel for forwarding data to the connection
        let (data_tx, data_rx) = mpsc::channel::<Bytes>(256);
        let ws_sender = self.ws_sender.clone();

        // Spawn connection handler based on protocol
        let handle = match proto {
            Proto::Tcp => {
                tokio::spawn(async move {
                    if let Err(e) = handle_tcp_connection(client_id, port, ws_sender, data_rx).await {
                        error!(client_id, error = %e, "TCP connection failed");
                    }
                })
            }
            Proto::Udp => {
                tokio::spawn(async move {
                    if let Err(e) = handle_udp_connection(client_id, port, ws_sender, data_rx).await {
                        error!(client_id, error = %e, "UDP connection failed");
                    }
                })
            }
        };

        self.connections.insert(client_id, ActiveConnection {
            data_tx,
            _handle: handle,
        });
    }

    /// Handle a DATA message - forward to the appropriate connection
    pub async fn handle_data(&self, client_id: u32, proto: Proto, data: &[u8]) {
        debug!(
            client_id,
            proto = %proto,
            len = data.len(),
            "Forwarding data to connection"
        );

        if let Some(conn) = self.connections.get(&client_id) {
            let data_bytes = Bytes::copy_from_slice(data);
            if let Err(e) = conn.data_tx.send(data_bytes).await {
                warn!(client_id, error = %e, "Failed to send data to connection");
            }
        } else {
            warn!(client_id, "DATA for unknown connection");
        }
    }

    /// Handle a CLOSE message - close the connection
    pub async fn handle_close(&mut self, client_id: u32) {
        info!(client_id, "Closing connection");

        if let Some(conn) = self.connections.remove(&client_id) {
            // Dropping the connection will:
            // 1. Close the data channel (signals writer to stop)
            // 2. Abort the task handle
            drop(conn);
        }
    }

    /// Handle a PING message - respond with PONG
    pub async fn handle_ping(&self, client_id: u32) {
        debug!(client_id, "Received PING, sending PONG");

        let pong = protocol::build_pong(client_id);
        if let Err(e) = self.send_message(pong).await {
            error!(error = %e, "Failed to send PONG");
        }
    }

    /// Send a message through the WebSocket
    async fn send_message(&self, data: Bytes) -> Result<()> {
        let mut sender = self.ws_sender.lock().await;
        sender
            .send(Message::Binary(data.to_vec().into()))
            .await
            .context("Failed to send WebSocket message")?;
        Ok(())
    }

    /// Shutdown all connections
    pub async fn shutdown(&mut self) {
        info!("Shutting down all connections");
        for (client_id, conn) in self.connections.drain() {
            debug!(client_id, "Closing connection");
            drop(conn);
        }
    }
}

// =============================================================================
// TCP Connection Handler
// =============================================================================

/// Handle a single TCP connection to a local service
async fn handle_tcp_connection(
    client_id: u32,
    port: u16,
    ws_sender: WsSender,
    mut data_rx: mpsc::Receiver<Bytes>,
) -> Result<()> {
    let addr: SocketAddr = format!("127.0.0.1:{}", port).parse()?;

    // Connect to local service
    let stream = match TcpStream::connect(addr).await {
        Ok(s) => {
            info!(client_id, port, "TCP connection established");
            s
        }
        Err(e) => {
            error!(client_id, port, error = %e, "Failed to connect to local service");

            // Send ERROR message back
            let error_msg = protocol::build_error(Proto::Tcp, client_id, &e.to_string());
            let mut sender = ws_sender.lock().await;
            let _ = sender.send(Message::Binary(error_msg.to_vec().into())).await;

            return Err(e.into());
        }
    };

    // Send CONNECTED message
    let connected = protocol::build_connected(Proto::Tcp, client_id);
    {
        let mut sender = ws_sender.lock().await;
        sender
            .send(Message::Binary(connected.to_vec().into()))
            .await
            .context("Failed to send CONNECTED")?;
    }

    let (mut reader, mut writer) = stream.into_split();

    // Task to read from TCP and send to WebSocket
    let ws_sender_clone = ws_sender.clone();
    let read_task = tokio::spawn(async move {
        let mut buf = vec![0u8; 65536];
        loop {
            match reader.read(&mut buf).await {
                Ok(0) => {
                    debug!(client_id, "TCP connection closed by remote");
                    break;
                }
                Ok(n) => {
                    debug!(client_id, bytes = n, "Read from TCP, sending to WebSocket");
                    let data = protocol::build_data(Proto::Tcp, client_id, &buf[..n]);
                    let mut sender = ws_sender_clone.lock().await;
                    if sender.send(Message::Binary(data.to_vec().into())).await.is_err() {
                        break;
                    }
                }
                Err(e) => {
                    error!(client_id, error = %e, "TCP read error");
                    break;
                }
            }
        }

        // Send CLOSE message
        let close = protocol::build_close(Proto::Tcp, client_id);
        let mut sender = ws_sender_clone.lock().await;
        let _ = sender.send(Message::Binary(close.to_vec().into())).await;
    });

    // Task to receive data from channel and write to TCP
    let write_task = tokio::spawn(async move {
        while let Some(data) = data_rx.recv().await {
            debug!(client_id, bytes = data.len(), "Writing to TCP");
            if let Err(e) = writer.write_all(&data).await {
                error!(client_id, error = %e, "TCP write error");
                break;
            }
            if let Err(e) = writer.flush().await {
                error!(client_id, error = %e, "TCP flush error");
                break;
            }
        }
        debug!(client_id, "Write task ending (channel closed)");
    });

    // Wait for either task to complete
    tokio::select! {
        _ = read_task => {
            debug!(client_id, "Read task completed");
        }
        _ = write_task => {
            debug!(client_id, "Write task completed");
        }
    }

    Ok(())
}

// =============================================================================
// UDP Connection Handler
// =============================================================================

/// Handle a single UDP "connection" to a local service
async fn handle_udp_connection(
    client_id: u32,
    port: u16,
    ws_sender: WsSender,
    mut data_rx: mpsc::Receiver<Bytes>,
) -> Result<()> {
    // Bind to a random local port
    let socket = UdpSocket::bind("127.0.0.1:0").await?;
    let target: SocketAddr = format!("127.0.0.1:{}", port).parse()?;

    // Connect the UDP socket to the target (allows send/recv instead of send_to/recv_from)
    socket.connect(target).await?;

    info!(client_id, port, "UDP socket ready");

    // Send CONNECTED message
    let connected = protocol::build_connected(Proto::Udp, client_id);
    {
        let mut sender = ws_sender.lock().await;
        sender
            .send(Message::Binary(connected.to_vec().into()))
            .await
            .context("Failed to send CONNECTED")?;
    }

    // Split socket for concurrent read/write
    let socket = Arc::new(socket);
    let socket_read = socket.clone();
    let socket_write = socket.clone();

    // Task to read from UDP and send to WebSocket
    let ws_sender_clone = ws_sender.clone();
    let read_task = tokio::spawn(async move {
        let mut buf = vec![0u8; 65536];
        loop {
            match socket_read.recv(&mut buf).await {
                Ok(n) => {
                    debug!(client_id, bytes = n, "Read from UDP, sending to WebSocket");
                    let data = protocol::build_data(Proto::Udp, client_id, &buf[..n]);
                    let mut sender = ws_sender_clone.lock().await;
                    if sender.send(Message::Binary(data.to_vec().into())).await.is_err() {
                        break;
                    }
                }
                Err(e) => {
                    error!(client_id, error = %e, "UDP recv error");
                    break;
                }
            }
        }

        // Send CLOSE message
        let close = protocol::build_close(Proto::Udp, client_id);
        let mut sender = ws_sender_clone.lock().await;
        let _ = sender.send(Message::Binary(close.to_vec().into())).await;
    });

    // Task to receive data from channel and write to UDP
    let write_task = tokio::spawn(async move {
        while let Some(data) = data_rx.recv().await {
            debug!(client_id, bytes = data.len(), "Writing to UDP");
            if let Err(e) = socket_write.send(&data).await {
                error!(client_id, error = %e, "UDP send error");
                break;
            }
        }
        debug!(client_id, "UDP write task ending (channel closed)");
    });

    // Wait for either task to complete
    tokio::select! {
        _ = read_task => {
            debug!(client_id, "UDP read task completed");
        }
        _ = write_task => {
            debug!(client_id, "UDP write task completed");
        }
    }

    Ok(())
}
