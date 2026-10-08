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

# Client onboarding invite emails are OFF unless this is set (tests always suppress them)
ONBOARDING_SEND_INVITE_EMAILS=true
DB_HOST=your_db_host
DB_PORT=5432
```

### Security Improvements Made
1. ✅ `SECRET_KEY` is required from the environment — **no fallback**. The app
   fails to start if `SECRET_KEY` is unset (was previously a committed insecure
   fallback). The same applies to `DB_USER_PASS`.
2. ✅ `DEBUG` now defaults to **False** (fails safe if the env var is missing).
3. ✅ `ALLOWED_HOSTS` configurable via environment variable.
4. ✅ HTTPS/cookie hardening: `SECURE_PROXY_SSL_HEADER`, `SESSION/CSRF_COOKIE_SECURE`,
   `SECURE_SSL_REDIRECT`, HSTS, `SECURE_CONTENT_TYPE_NOSNIFF`, `X_FRAME_OPTIONS`
   (all active when `DEBUG=False`).
5. ✅ Brute-force protection via **django-axes** (username-keyed lockout — safe
   for the shared office IP). Run `python manage.py migrate` on deploy.
6. ✅ All views require login by default (`LoginRequiredMiddleware`).
7. ✅ Per-file upload size/type validation on bundle and undertaking uploads.
8. ✅ Removed `printenv > /etc/environment` secret leak from `entrypoint.sh`.
9. ✅ Log file/dir permissions (644 / 755).

> ⚠️ **BREAKING ON DEPLOY:** because `SECRET_KEY` and `DB_USER_PASS` no longer
> have fallbacks, the app/containers **will not boot** unless both are present
> in the environment (or the baked-in/ mounted `.env`). Confirm before deploying.

### Secret Rotation (do this as part of this hardening pass)
The old `SECRET_KEY` and DB password were committed to git history, so rotate both:

1. **SECRET_KEY** — generate a fresh one and set it in the prod environment/.env:
   ```bash
   python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
   ```
   (Rotating invalidates existing sessions — users simply re-login.)
2. **Database password** — rotate the DigitalOcean Postgres password and update
   `DB_USER_PASS` in the prod environment/.env.
3. Rotate the Postgres password hardcoded in `scripts/add_prev_data_to_psql_db.py`
   (gitignored/local, but live-looking).
4. *(Optional follow-up)* scrub the old secrets from git history (e.g. `git filter-repo`).

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

