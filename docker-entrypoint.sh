#!/bin/sh
# Apply pending migrations, then hand off to the CMD.
set -e

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "==> alembic upgrade head"
  alembic upgrade head
fi

# exec so the server becomes PID 1 and receives SIGTERM directly, which lets
# gunicorn shut down gracefully instead of being killed after the grace period.
exec "$@"
