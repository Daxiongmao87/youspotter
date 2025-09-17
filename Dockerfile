# Use Python 3.12 slim image
FROM python:3.12-slim

# Install system dependencies needed for yt-dlp, audio processing, and gosu for entrypoint
RUN apt-get update && apt-get install -y \
    ffmpeg \
    gosu \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for security
RUN useradd --create-home --shell /bin/bash youspotter

# Set working directory
WORKDIR /app

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy entrypoint script first
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Copy application code
COPY . .

# Create data directory for database persistence
RUN mkdir -p /app/data /app/downloads && chown youspotter:youspotter /app/data /app/downloads

# Change ownership of app directory to non-root user
RUN chown -R youspotter:youspotter /app

# Set environment variables
ENV YOUSPOTTER_DB=/app/data/youspotter.db
ENV PORT=5000

# Expose the port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# Set entrypoint and command
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "app.py"]