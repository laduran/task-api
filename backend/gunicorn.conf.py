"""Gunicorn settings, auto-loaded from the working directory.

Everything is environment-driven so the same image runs unchanged in local
compose and on a platform that injects its own PORT.
"""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# Worker count is safe to raise now that state lives in Postgres rather than
# in a module-level list.
workers = int(os.environ.get("WEB_CONCURRENCY", "4"))

accesslog = "-"
errorlog = "-"

# Requests arrive from the platform's proxy, so trust its forwarding headers.
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "*")

# Long enough for a slow query, short enough to shed a wedged worker.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "30"))
graceful_timeout = 30

# The control socket defaults to $HOME/.gunicorn/gunicorn.ctl, which a
# homeless container user cannot create — it logs a permission error on every
# boot. Nothing here uses the control interface, so turn it off.
control_socket_disable = True
