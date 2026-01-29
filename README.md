# yt-meme-bot

Telegram bot that accepts short MP4 memes from a trusted admin account, enriches the metadata, and uploads them to every configured YouTube channel. When the daily upload quota is reached, videos are automatically queued and posted in evenly spaced slots the next day.

## Features

- **Robust Architecture**: Docker-ready "1 file run" (runs as non-root user).
- **Quota Management**: Automatically schedules uploads for the next day if daily limit is reached.
- **Auto-Retry**: Resilient against ephemeral API errors.
- **Smart Metadata**: Randomly selects descriptions and relevant tags for memes.
- **Duplicate Detection**: Prevents accidental re-uploads using SHA256 hashing.
- **Auto-Thumbnails**: Extracts the "best" frame from the middle of the video using FFmpeg.
- **Daily Reports**: Morning summary of upload stats.

## Prerequisities

- Docker & Docker Compose (Recommended)
- OR Python 3.10+ & FFmpeg
- Telegram Bot Token & Admin ID
- Google YouTube Data API Credentials

## 🚀 Quick Start (Docker)

1. **Configure**:
    cp config.yaml.example config.yaml

    # Edit config.yaml with your tokens

2. **Add Credentials**:

    # Place your YouTube "client_secret" or oauth token JSONs in channels/

    # (See channels/README.md)

3. **Run**:

    ```bash
    ./deploy.sh
    ```

That's it! The bot will start, create necessary database files in `data/`, and log to `logs/`.

### Configuration via Environment Variables

You can override config values using environment variables (great for Portainer/Coolify):

- `TELEGRAM_TOKEN`
- `ADMIN_ID`
- `DAILY_LIMIT`
- `UPLOAD_START_HOUR`
- `UPLOAD_INTERVAL_MINUTES`

## Development (Local Python)

1. **Install**:

    ```bash
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    # Ensure ffmpeg is installed on your system
    ```

2. **Run**:

    ```bash
    # Run as a module
    python -m app.bot
    ```

## Project Structure

- `app/`: Source code.
- `channels/`: Mount point for YouTube credentials.
- `data/`: Mount point for SQLite database.
- `logs/`: Application logs.
- `deploy.sh`: One-click deployment script.
