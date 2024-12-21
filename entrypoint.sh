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

# Remove any existing crontab
echo "Removing existing crontab..."
python manage.py crontab remove

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

# Follow the logs (this helps in debugging)
tail -f /app/email_sorting/email_job.log /app/email_sorting/remove_log.log &

# Execute the command passed to the container
exec "$@"