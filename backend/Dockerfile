# =============================================================================
# BACKEND DOCKERFILE - DIGITAL EKUB PLATFORM
# =============================================================================
# Build: docker build -t ekub-backend .
# This image runs the Django API server with Gunicorn in production.
# =============================================================================

# Use Python 3.11 slim image for smaller size
FROM python:3.11-slim-bullseye

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  TZ=Africa/Addis_Ababa

# Set work directory
WORKDIR /app

# Install system dependencies
# - netcat: used by entrypoint to wait for database
# - gcc, libpq-dev: build tools for psycopg2
# - libffi-dev: needed for cryptography
# - curl: for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
  netcat \
  gcc \
  libpq-dev \
  libffi-dev \
  curl \
  gettext \
  && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project
COPY . .

# Copy entrypoint script and make it executable
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create directories for static and media files
RUN mkdir -p /app/static /app/media/profiles /app/media/groups

# Expose port 8000
EXPOSE 8000

# Set the entrypoint
ENTRYPOINT ["/entrypoint.sh"]

# Default command (overridden in docker-compose)
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--threads", "2", "--timeout", "120"]