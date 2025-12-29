# Production Deployment Checklist

## Logging Configuration ✅

### Log Files Location
- All logs are stored in `/app/logs/` inside the container
- Mapped to `./logs/` on the host machine via Docker volume
- Log files are automatically rotated when they reach 10MB

### Log Files Created
- `django.log` - Django framework logs
- `application.log` - Application-level logs
- `errors.log` - Error-level logs only
- `security.log` - Security-related warnings
- `email.log` - Email sorting operations
- `gunicorn.log` - Gunicorn server logs
- `gunicorn_access.log` - Gunicorn access logs
- `gunicorn_error.log` - Gunicorn error logs

### Log Levels
- **Development (DEBUG=True)**: DEBUG level logging enabled
- **Production (DEBUG=False)**: INFO level logging (more secure, less verbose)

## Security Settings ⚠️

### Required Environment Variables
Before deploying to production, ensure these environment variables are set:

```bash
# Required for production
SECRET_KEY=your-secret-key-here  # Generate a new secure key!
DEBUG=False
ALLOWED_HOSTS=wip.anp.softwarised.com,localhost  # Comma-separated list

# Database (already using environment variables)
DB_NAME=your_db_name
DB_USER=your_db_user
DB_USER_PASS=your_db_password
DB_HOST=your_db_host
DB_PORT=5432
```

### Security Improvements Made
1. ✅ `SECRET_KEY` now uses environment variable (with insecure fallback for development)
2. ✅ `DEBUG` setting fixed (was a tuple, now a proper boolean)
3. ✅ `ALLOWED_HOSTS` now configurable via environment variable
4. ✅ Log file permissions set to 644 (readable by owner/group, writable by owner)
5. ✅ Log directory permissions set to 755

## Docker Configuration ✅

### Volume Mounts
- `./media:/app/media` - User uploaded files
- `./logs:/app/logs` - Application logs (persists outside container)

### Gunicorn Configuration
- Uses `gunicorn_config.py` for logging configuration
- 3 workers configured
- Logs to both console and files

## Before Production Deployment

1. **Set Environment Variables**:
   ```bash
   export SECRET_KEY="$(python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')"
   export DEBUG=False
   export ALLOWED_HOSTS="wip.anp.softwarised.com"
   ```

2. **Verify Log Directory Permissions**:
   ```bash
   chmod 755 logs/
   ```

3. **Test Logging**:
   - Start the application
   - Perform some actions (login, access files, etc.)
   - Verify logs are being written to `./logs/` directory
   - Check log rotation works (logs rotate at 10MB)

4. **Monitor Logs**:
   ```bash
   # Watch error logs
   tail -f logs/errors.log
   
   # Watch application logs
   tail -f logs/application.log
   
   # Watch security logs
   tail -f logs/security.log
   ```

## Log Rotation

Logs automatically rotate when they reach 10MB:
- Application logs: Keep 5 backup files
- Error logs: Keep 10 backup files (more important)
- Security logs: Keep 10 backup files (more important)

## Troubleshooting

### Logs not appearing?
1. Check Docker volume mount: `docker-compose ps`
2. Check directory permissions: `ls -la logs/`
3. Check container logs: `docker-compose logs web`

### Permission errors?
```bash
# Fix log directory permissions
chmod 755 logs/
chmod 644 logs/*.log
```

### Too many logs?
- Adjust log levels in `settings.py` LOGGING configuration
- Reduce `backupCount` for less log retention
- Increase `maxBytes` for larger files before rotation

