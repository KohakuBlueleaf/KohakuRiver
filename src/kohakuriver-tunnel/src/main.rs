//! KohakuRiver Tunnel Client
//!
//! A lightweight tunnel client that runs inside Docker containers to enable
//! port forwarding without Docker port mapping.
//!
//! This binary connects to the runner's WebSocket endpoint and forwards
//! TCP/UDP connections to local services inside the container.
//!
//! Usage:
//!     tunnel-client --runner-url ws://192.168.1.100:8001 --container-id my-container
//!
//! Or using environment variables:
//!     RUNNER_URL=ws://192.168.1.100:8001 CONTAINER_ID=my-container tunnel-client

mod connection;
mod protocol;
mod tunnel;

use std::time::Duration;

use anyhow::Result;
use clap::Parser;
use tracing::info;
use tracing_subscriber::EnvFilter;

use tunnel::{TunnelClient, TunnelConfig};

/// KohakuRiver Tunnel Client - Port forwarding for containers
#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    /// Runner WebSocket URL (e.g., ws://192.168.1.100:8001)
    #[arg(short, long, env = "RUNNER_URL")]
    runner_url: String,

    /// Container ID or name (used to identify this tunnel)
    #[arg(short, long, env = "CONTAINER_ID")]
    container_id: String,

    /// Reconnect delay in seconds
    #[arg(long, default_value = "5", env = "RECONNECT_DELAY")]
    reconnect_delay: u64,

    /// Maximum reconnect attempts (0 = infinite)
    #[arg(long, default_value = "0", env = "MAX_RECONNECT")]
    max_reconnect: u32,

    /// Log level (trace, debug, info, warn, error)
    #[arg(long, default_value = "info", env = "LOG_LEVEL")]
    log_level: String,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();

    // Initialize logging
    init_logging(&args.log_level);

    info!(
        runner_url = %args.runner_url,
        container_id = %args.container_id,
        "Starting KohakuRiver Tunnel Client"
    );

    // Build configuration
    let config = TunnelConfig {
        runner_url: args.runner_url,
        container_id: args.container_id,
        reconnect_delay: Duration::from_secs(args.reconnect_delay),
        max_reconnect_attempts: args.max_reconnect,
    };

    // Create and run tunnel client
    let client = TunnelClient::new(config);
    client.run().await?;

    Ok(())
}

fn init_logging(level: &str) {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new(level));

    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_target(false)
        .with_thread_ids(false)
        .compact()
        .init();
}
