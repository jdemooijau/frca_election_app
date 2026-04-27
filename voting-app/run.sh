#!/bin/bash
cd "$(dirname "$0")"
echo "================================================"
echo "  FRCA Election App"
echo "  http://localhost:5000"
echo "  Admin: http://localhost:5000/admin"
echo "================================================"
gunicorn -w 4 -b 0.0.0.0:5000 app:app
