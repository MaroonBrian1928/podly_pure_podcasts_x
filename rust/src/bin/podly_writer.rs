use anyhow::Result;
use clap::Parser;
use podly_tools::writer::config::{WriterArgs, WriterConfig};

#[tokio::main]
async fn main() -> Result<()> {
    let config = WriterConfig::from_args(WriterArgs::parse())?;
    podly_tools::writer::transport::run(config).await
}
