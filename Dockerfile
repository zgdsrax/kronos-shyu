FROM python:3.11-slim

WORKDIR /app

# Install system deps for potential native modules
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Verify config loads at build time (fail-fast on bad config)
RUN python -c "from config.loader import load_config; load_config()" || \
    (echo "Config validation failed" && exit 1)

# Create log directory
RUN mkdir -p /app/logs

# Run as non-root
RUN adduser --disabled-password --gecos '' botuser
USER botuser

# Default to live mode; override with command line args
CMD ["python", "src/bot.py"]