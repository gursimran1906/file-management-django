"""Gunicorn configuration file for logging"""
import os

# Logs directory (should match Django settings LOGS_DIR)
# Default to /app/logs which matches the Docker volume mount
LOGS_DIR = os.environ.get('LOGS_DIR', '/app/logs')

# Ensure logs directory exists
try:
    os.makedirs(LOGS_DIR, exist_ok=True)
    # Set secure permissions
    os.chmod(LOGS_DIR, 0o755)
except OSError:
    # If we can't create the directory, gunicorn will handle the error
    pass

# Gunicorn logging configuration
accesslog = os.path.join(LOGS_DIR, 'gunicorn_access.log')
errorlog = os.path.join(LOGS_DIR, 'gunicorn_error.log')
loglevel = 'info'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Capture output
capture_output = True
enable_stdio_inheritance = True
