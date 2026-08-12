#!/bin/bash
# =============================================================================
# ENTRYPOINT SCRIPT FOR DJANGO BACKEND
# =============================================================================
# This script runs before the Django server starts inside the container.
# It performs migrations, creates a superuser, collects static files,
# and waits for the database to be ready.
# =============================================================================

set -e

echo "========================================"
echo "DIGITAL EKUB PLATFORM - BACKEND STARTUP"
echo "========================================"

# ----------------------------------------------------------------------------
# 1. WAIT FOR DATABASE
# ----------------------------------------------------------------------------
echo "⏳ Waiting for database to be ready..."

# Try to connect to PostgreSQL until it responds
while ! nc -z ${DB_HOST:-db} ${DB_PORT:-5432} 2>/dev/null; do
    sleep 1
done

echo "✅ Database is ready!"

# ----------------------------------------------------------------------------
# 2. RUN MIGRATIONS
# ----------------------------------------------------------------------------
echo "🔄 Running database migrations..."
python manage.py migrate --noinput

# ----------------------------------------------------------------------------
# 3. CREATE SUPERUSER (if it doesn't exist)
# ----------------------------------------------------------------------------
echo "👤 Creating superuser (if not exists)..."

python manage.py shell <<EOF
import os
from django.contrib.auth import get_user_model

User = get_user_model()
email = os.environ.get('ADMIN_EMAIL', 'admin@ekub-platform.com')
password = os.environ.get('ADMIN_PASSWORD', 'admin123')

if not User.objects.filter(email=email).exists():
    User.objects.create_superuser(
        email=email,
        password=password,
        first_name='Admin',
        last_name='User'
    )
    print(f"✅ Superuser created: {email}")
else:
    print(f"ℹ️ Superuser already exists: {email}")
EOF

# ----------------------------------------------------------------------------
# 4. COLLECT STATIC FILES
# ----------------------------------------------------------------------------
echo "📦 Collecting static files..."
python manage.py collectstatic --noinput

# ----------------------------------------------------------------------------
# 5. CREATE MEDIA DIRECTORY (if missing)
# ----------------------------------------------------------------------------
echo "📁 Ensuring media directories exist..."
mkdir -p /app/media/profiles
mkdir -p /app/media/groups
chmod -R 755 /app/media

# ----------------------------------------------------------------------------
# 6. START THE APPLICATION
# ----------------------------------------------------------------------------
echo "🚀 Starting application..."
exec "$@"