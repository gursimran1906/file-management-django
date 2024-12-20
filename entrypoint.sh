#!/bin/sh

# Install required packages for cron
apt-get update && apt-get install -y --no-install-recommends \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Run migrations
echo 'Running migrations...'
python manage.py migrate

# Add crontab
echo 'Adding crontab...'
python manage.py crontab add

# Start cron service in the background
echo 'Starting crond...'
cron -f &

# Execute the command passed to the container (e.g., gunicorn, server, etc.)
exec "$@"
