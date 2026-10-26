"""
api/index.py – Vercel Serverless Entrypoint for Innov8 REST API
===============================================================
Wraps the Flask application from backend/app.py for Vercel's
@vercel/python runtime.
"""

import os
import sys

# Ensure backend folder is in Python's search path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(CURRENT_DIR, "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app import app
from db import init_db

# Initialize database schema & demo seed on serverless cold boot
try:
    init_db()
except Exception as exc:
    print(f"[vercel] DB init notice: {exc}")

# Vercel serverless WSGI handler
