# Use Python 3.10 slim image for ARM64/AMD64 compatibility
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/app/playwright-browsers

# Install system dependencies
# ffmpeg needed for Whisper audio processing
# wget and curl needed for Piper TTS download
# Playwright dependencies for headless browser scraping
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    g++ \
    wget \
    curl \
    # Playwright/Chromium dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (for better layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers to shared location (PLAYWRIGHT_BROWSERS_PATH)
# Directory will be chowned to semantika user later
RUN mkdir -p /app/playwright-browsers && \
    playwright install chromium

# NOTE: ML models (FastEmbed, Whisper) are downloaded at runtime
# and stored in /app/.cache volume (shared between containers)
# This keeps image size small (~2-3 GB instead of 12 GB)

# Download and install Piper TTS
RUN mkdir -p /app/models && \
    cd /app && \
    wget -q https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_amd64.tar.gz && \
    tar -xzf piper_amd64.tar.gz && \
    rm piper_amd64.tar.gz && \
    chmod +x /app/piper/piper && \
    cd /app/models && \
    wget -q https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/carlfm/x_low/es_ES-carlfm-x_low.onnx && \
    wget -q https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/carlfm/x_low/es_ES-carlfm-x_low.onnx.json

# Create non-root user BEFORE copying code (avoids duplicating layers)
# Also chown playwright-browsers so the user can access chromium
RUN useradd -m -u 1000 semantika && \
    chown -R semantika:semantika /app /app/playwright-browsers

# Copy application code with correct ownership (after ML models to preserve cache)
COPY --chown=semantika:semantika . .

USER semantika

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=5)" || exit 1

# Default command (will be overridden by docker-compose)
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
