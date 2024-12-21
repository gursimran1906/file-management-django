#!/bin/sh

# Run migrations
echo 'Running migrations...'
python manage.py migrate

# Create environment file for cron
env | while read -r line; do
    # Escape any single quotes in the value
    escaped_line=$(echo "$line" | sed "s/'/'\\\\''/g")
    echo "export '$escaped_line'" >> /etc/environment
done

# Ensure cron has access to environment variables
printenv | grep -v "no_proxy" > /etc/default/cron

# Create a script that sources environment for cron jobs
cat <<'EOF' > /entrypoint-cron.sh
#!/bin/sh
set -e
source /etc/environment
exec "$@"
EOF
chmod +x /entrypoint-cron.sh

# Update CRON_PATH in crontab
echo "SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
CRON_PATH=/entrypoint-cron.sh" > /etc/cron.d/crontab

# Add crontab
echo 'Adding crontab...'
python manage.py crontab add

# Give execution rights on the cron job
chmod 0644 /etc/cron.d/crontab

# Apply cron job
crontab /etc/cron.d/crontab

# Start cron service in the background
echo 'Starting crond...'
cron -f &


# Execute the command passed to the container
exec "$@"