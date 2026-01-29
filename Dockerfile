FROM python:3.10-slim

WORKDIR /app

# Install dependencies and ffmpeg
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Copy source code
COPY app/ ./app/

# Create directories for data and config
RUN mkdir -p channels data logs

# Security: Create non-root user
RUN useradd -m appuser && \
    chown -R appuser:appuser /app
USER appuser

# Set env vars to point to these
ENV CHANNELS_PATH=/app/channels
ENV DB_PATH=/app/data/uploads.db

# Run the bot
# We use -m to run the package
CMD ["python", "-m", "app.bot"]
