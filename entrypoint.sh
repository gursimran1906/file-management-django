#!/bin/sh

# Create logs directory if it doesn't exist
mkdir -p /app/logs
chmod 755 /app/logs

# Set proper permissions for log files (if they exist)
chmod 644 /app/logs/*.log 2>/dev/null || true

# Run migrations
echo 'Running migrations...'
python manage.py migrate

# Hand the container's environment to cron. Debian's cron builds each job's
# environment through PAM (/etc/pam.d/cron -> pam_env.so), which reads
# /etc/environment; without this a cron job starts with almost no environment
# and dies in settings.py on the first require_env() ('SECRET_KEY' is not set).
#
# There is no fallback: secrets reach this container through docker-compose
# env_file, and .env is gitignored so it is never baked into the image. An
# earlier revision dropped this dump assuming load_dotenv would cover cron --
# it does not, and that silently killed every cron job (email sync, Granola,
# the sign-off digest, correspondence exports).
#
# Created 600 BEFORE it is written, so the secrets are never world-readable.
#
# pam_env's parser is crude: it truncates a value at the first '#' (quoting it
# does not help) and cannot carry a newline. A variable like that is skipped
# rather than written through, so the job fails loudly on a missing variable
# instead of running with a silently truncated secret.
install -m 600 /dev/null /etc/environment
python - <<'ENVDUMP'
import os

LOSSY = sorted(k for k, v in os.environ.items() if '#' in v or '\n' in v)
with open('/etc/environment', 'w') as fh:
    for key, value in sorted(os.environ.items()):
        if key not in LOSSY:
            fh.write(f'{key}={value}\n')
if LOSSY:
    print('WARNING: cron cannot carry these variables (the value contains "#" '
          'or a newline, which pam_env mangles) and they have been left out of '
          '/etc/environment: ' + ', '.join(LOSSY))
    print('WARNING: any cron job that needs one will fail with a clear '
          '"not set" error. Re-issue the secret without those characters.')
ENVDUMP

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