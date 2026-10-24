"""WSGI entry point for production servers such as Gunicorn."""
import os

if os.environ.get('ARTECT_ENV', '').strip().lower() not in ('production', 'prod'):
    raise RuntimeError('Set ARTECT_ENV=production before starting the WSGI application.')

from app import app

__all__ = ['app']
