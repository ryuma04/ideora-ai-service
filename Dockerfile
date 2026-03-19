# Use a stable Python version
FROM python:3.11-slim

# Install system dependencies for WeasyPrint and Whisper
RUN apt-get update && apt-get install -y \
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

# Copy requirements and install
# Note: Pinned versions in requirements.txt prevent version loops
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Command to run the application
# Use workers to handle multiple concurrent tasks if needed
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
