#!/bin/sh

# Create logs directory if it doesn't exist
mkdir -p /app/logs
chmod 755 /app/logs

# Set proper permissions for log files (if they exist)
chmod 644 /app/logs/*.log 2>/dev/null || true

# Run migrations
echo 'Running migrations...'
python manage.py migrate

# NOTE: previously this dumped all env vars (incl. secrets) to /etc/environment.
# Removed: it was a world-readable secret leak and is unnecessary — cron jobs run
# `python manage.py ...`, and settings.py loads the baked-in .env via load_dotenv,
# so the cron environment already has everything it needs.
# Ensure the database cache table exists (idempotent). The default cache uses
# DatabaseCache so the bundle-PDF generation lock is shared across gunicorn workers.
echo 'Ensuring cache table...'
python manage.py createcachetable


# Add crontab
echo "Adding crontab..."
python manage.py crontab add

# Make sure crontab is owned by root and has correct permissions
touch /var/spool/cron/crontabs/root
chmod 600 /var/spool/cron/crontabs/root
chown root:crontab /var/spool/cron/crontabs/root

# Start cron service in the background
echo "Starting crond..."
cron

# Verify crontab was added
echo "Verifying crontab..."
crontab -l
python manage.py crontab show

# Execute the command passed to the container
exec "$@"