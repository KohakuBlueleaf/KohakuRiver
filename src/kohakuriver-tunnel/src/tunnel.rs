//! Main tunnel client implementation.
//!
//! Connects to the runner's WebSocket endpoint and handles incoming messages.

use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use futures_util::{SinkExt, StreamExt};
use tokio::sync::Mutex;
use tokio::time::sleep;
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::Message;
use tracing::{debug, error, info, warn};
use url::Url;

use crate::connection::{ConnectionManager, WsSender};
use crate::protocol::{self, Header, MsgType, HEADER_SIZE};

/// Tunnel client configuration
#[derive(Debug, Clone)]
pub struct TunnelConfig {
    /// Runner WebSocket URL (e.g., ws://192.168.1.100:8001/ws/tunnel/container-id)
    pub runner_url: String,
    /// Container ID (used in the URL path)
    pub container_id: String,
    /// Reconnect delay on connection failure
    pub reconnect_delay: Duration,
    /// Maximum reconnect attempts (0 = infinite)
    pub max_reconnect_attempts: u32,
}

impl Default for TunnelConfig {
    fn default() -> Self {
        Self {
            runner_url: String::new(),
            container_id: String::new(),
            reconnect_delay: Duration::from_secs(5),
            max_reconnect_attempts: 0, // Infinite
        }
    }
}

/// Main tunnel client
pub struct TunnelClient {
    config: TunnelConfig,
}

impl TunnelClient {
    pub fn new(config: TunnelConfig) -> Self {
        Self { config }
    }

    /// Build the full WebSocket URL
    fn build_ws_url(&self) -> Result<Url> {
        let url_str = format!(
            "{}/ws/tunnel/{}",
            self.config.runner_url.trim_end_matches('/'),
            self.config.container_id
        );
        Url::parse(&url_str).context("Failed to parse WebSocket URL")
    }

    /// Run the tunnel client with automatic reconnection
    pub async fn run(&self) -> Result<()> {
        let mut attempt = 0u32;

        loop {
            attempt += 1;

            if self.config.max_reconnect_attempts > 0
                && attempt > self.config.max_reconnect_attempts
            {
                error!("Max reconnection attempts reached, giving up");
                return Err(anyhow::anyhow!("Max reconnection attempts exceeded"));
            }

            info!(attempt, "Connecting to runner...");

            match self.connect_and_run().await {
                Ok(()) => {
                    info!("Connection closed normally");
                    attempt = 0; // Reset on successful connection
                }
                Err(e) => {
                    error!(error = %e, "Connection error");
                }
            }

            // Wait before reconnecting
            info!(
                delay_secs = self.config.reconnect_delay.as_secs(),
                "Reconnecting..."
            );
            sleep(self.config.reconnect_delay).await;
        }
    }

    /// Connect to the runner and handle messages
    async fn connect_and_run(&self) -> Result<()> {
        let url = self.build_ws_url()?;
        info!(url = %url, "Connecting to WebSocket");

        // Connect to WebSocket
        let (ws_stream, response) = connect_async(url.as_str())
            .await
            .context("Failed to connect to WebSocket")?;

        info!(
            status = %response.status(),
            "WebSocket connected"
        );

        let (ws_sender, mut ws_receiver) = ws_stream.split();
        let ws_sender: WsSender = Arc::new(Mutex::new(ws_sender));

        // Create connection manager
        let mut conn_manager = ConnectionManager::new(ws_sender.clone());

        // Main message loop
        while let Some(msg_result) = ws_receiver.next().await {
            match msg_result {
                Ok(Message::Binary(data)) => {
                    if let Err(e) = self.handle_message(&mut conn_manager, &data).await {
                        warn!(error = %e, "Error handling message");
                    }
                }
                Ok(Message::Text(text)) => {
                    debug!(text, "Received text message (unexpected)");
                }
                Ok(Message::Ping(data)) => {
                    debug!("Received WebSocket ping");
                    let mut sender = ws_sender.lock().await;
                    let _ = sender.send(Message::Pong(data)).await;
                }
                Ok(Message::Pong(_)) => {
                    debug!("Received WebSocket pong");
                }
                Ok(Message::Close(frame)) => {
                    info!(?frame, "WebSocket closed by server");
                    break;
                }
                Ok(Message::Frame(_)) => {
                    // Raw frame, usually not received
                }
                Err(e) => {
                    error!(error = %e, "WebSocket error");
                    break;
                }
            }
        }

        // Cleanup
        conn_manager.shutdown().await;

        Ok(())
    }

    /// Handle an incoming tunnel protocol message
    async fn handle_message(
        &self,
        conn_manager: &mut ConnectionManager,
        data: &[u8],
    ) -> Result<()> {
        if data.len() < HEADER_SIZE {
            warn!(len = data.len(), "Message too short, ignoring");
            return Ok(());
        }

        let header = Header::parse(data)?;
        let payload = protocol::get_payload(data);

        debug!(
            msg_type = ?header.msg_type,
            proto = %header.proto,
            client_id = header.client_id,
            port = header.port,
            payload_len = payload.len(),
            "Received message"
        );

        match header.msg_type {
            MsgType::Connect => {
                // Server wants us to open a connection
                conn_manager
                    .handle_connect(header.client_id, header.proto, header.port)
                    .await;
            }
            MsgType::Data => {
                // Data to forward to local service
                // Note: In the current implementation, we need a channel-based approach
                // to forward data to specific connections. For now, this is handled
                // differently - see connection.rs TODO.
                conn_manager
                    .handle_data(header.client_id, header.proto, payload)
                    .await;
            }
            MsgType::Close => {
                // Server wants us to close a connection
                conn_manager.handle_close(header.client_id).await;
            }
            MsgType::Ping => {
                // Keepalive from server
                conn_manager.handle_ping(header.client_id).await;
            }
            MsgType::Connected | MsgType::Error | MsgType::Pong => {
                // These are client → server messages, shouldn't receive them
                warn!(msg_type = ?header.msg_type, "Unexpected message type from server");
            }
        }

        Ok(())
    }
}
