#!/bin/bash
# Fix for remote server logs permission issue

echo "🔧 Fixing logs permissions on remote server..."

# Stop and remove containers + volumes
docker-compose down -v

# Remove the logs directory if it exists
rm -rf logs

# Rebuild and start
docker-compose up -d --build

echo "✅ Fix applied! Bot should be running now."
echo "📜 Check logs with: docker-compose logs -f"
