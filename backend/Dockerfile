FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Step 1: Install CPU-only PyTorch FIRST (avoids pip downloading 2GB CUDA torch)
RUN pip install --no-cache-dir \
    torch==2.2.0+cpu \
    --index-url https://download.pytorch.org/whl/cpu

# Step 2: Install all other dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Step 3: Copy application code
COPY . .

# Render assigns a dynamic PORT env var
EXPOSE 5000

# Use gunicorn for production (more stable than Flask dev server)
CMD gunicorn --bind 0.0.0.0:${PORT:-5000} --timeout 120 --workers 1 app:app
