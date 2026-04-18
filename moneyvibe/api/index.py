"""Vercel serverless entry point — wraps the Flask app."""
import sys
import os

# Add parent directory to path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import app

# Vercel expects a WSGI-compatible app
