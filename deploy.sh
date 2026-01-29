#!/bin/bash
set -e

echo "🚀 Deploying YT Meme Bot..."

# Check for Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker could not be found. Please install Docker first."
    exit 1
fi

# Create necessary folders if they don't exist
mkdir -p channels data logs

# Build and start
echo "🐳 Building and starting containers..."
docker compose up -d --build

echo "✅ Deployment successful!"
echo "📜 Showing logs (Ctrl+C to exit)..."
docker compose logs -f
