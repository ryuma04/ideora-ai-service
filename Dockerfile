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

# Step 1: Upgrade core build tools
# We pin setuptools to 69.5.1 because versions >= 70 removed pkg_resources, 
# which some legacy packages (like whisper) still need during build.
RUN pip install --no-cache-dir --upgrade pip "setuptools<70" wheel

# Step 2: Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Step 3: Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
