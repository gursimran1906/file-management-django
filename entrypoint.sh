#!/bin/sh

echo 'Running migrations...'
python manage.py migrate

echo 'Adding crontab...'
python manage.py crontab add

echo 'Starting crond...'
crond -b

exec "$@"