# Use Python 3.10 slim image for ARM64/AMD64 compatibility
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
# ffmpeg needed for Whisper audio processing
# wget and curl needed for Piper TTS download
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    g++ \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (for better layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download ML models BEFORE copying code (better layer caching)
# 1. FastEmbed model for embeddings (768d multilingual)
# 2. Whisper base model for audio transcription
# 3. Piper TTS models
RUN python3 -c "from fastembed import TextEmbedding; TextEmbedding(model_name='sentence-transformers/paraphrase-multilingual-mpnet-base-v2', cache_dir='/app/.cache/fastembed')" && \
    python3 -c "import whisper; whisper.load_model('base', download_root='/app/.cache/whisper')"

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

# Copy application code (after ML models to preserve cache)
COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 semantika && \
    chown -R semantika:semantika /app

USER semantika

# Set cache directories (use pre-downloaded models)
ENV FASTEMBED_CACHE_PATH=/app/.cache/fastembed \
    WHISPER_CACHE_DIR=/app/.cache/whisper

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=5)" || exit 1

# Default command (will be overridden by docker-compose)
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
