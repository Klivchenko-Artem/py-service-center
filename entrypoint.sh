#!/bin/sh
# Миграции и статика, до старта сервера
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput --clear >/dev/null

# Суперпользователь заводится, только если его попросили переменными
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
  python manage.py createsuperuser --noinput || true
fi

exec "$@"
