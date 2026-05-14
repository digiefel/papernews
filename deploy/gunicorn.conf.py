"""Gunicorn config for the production service. Referenced by papernews.service."""

bind = "127.0.0.1:8000"
workers = 3
timeout = 30

accesslog = "-"
errorlog = "-"
loglevel = "info"
