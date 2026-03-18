#!/bin/bash
gunicorn website:app \
  --bind=0.0.0.0:8000 \
  --worker-class gthread \
  --workers 1 \
  --threads 100 \
  --timeout 0
