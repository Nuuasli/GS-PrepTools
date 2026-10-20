FROM python:3.10-slim

# Install system dependencies required for OpenCV, FFmpeg, and Image Processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Create user with UID 1000 (Required by Hugging Face Spaces security policy)
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# Install Python dependencies
COPY --chown=user requirements.txt $HOME/app/requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Copy application source code
COPY --chown=user . $HOME/app

# Ensure storage directories exist with write permissions
RUN mkdir -p $HOME/app/storage/uploads $HOME/app/storage/jobs

# Hugging Face Spaces exposes port 7860
EXPOSE 7860

# Set environment variables for production on Hugging Face
ENV PORT=7860 \
    HOST=0.0.0.0 \
    APP_ENV=production

# Start Uvicorn server on port 7860
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
