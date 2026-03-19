# Use a stable Python version
FROM python:3.11-slim

# Install system dependencies for WeasyPrint, Whisper, and building wheels
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    python3-cffi \
    python3-brotli \
    libpango-1.0-0 \
    libharfbuzz0b \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libffi-dev \
    shared-mime-info \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Upgrade core build tools globally first.
# Pinning setuptools < 70 keeps pkg_resources available for Whisper's build script.
# We also pre-install numpy to satisfy Whisper's build-time requirements.
RUN pip install --no-cache-dir --upgrade pip "setuptools<70" wheel "numpy==1.26.4"

# Install remaining requirements WITHOUT build isolation.
# This ensures pip uses our global setuptools/numpy to build Whisper.
COPY requirements.txt .
RUN pip install --no-cache-dir --no-build-isolation -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
