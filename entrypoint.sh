#!/bin/sh

# Run migrations
echo 'Running migrations...'
python manage.py migrate

printenv > /etc/environment


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