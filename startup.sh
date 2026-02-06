#!/bin/bash
gunicorn website:app --bind=0.0.0.0:8000