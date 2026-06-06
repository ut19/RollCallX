import os
import sys

# Resolve the absolute path to the backend directory
backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend')

# Change working directory to backend so all relative paths in back.py resolve correctly
os.chdir(backend_dir)

# Add backend directory to sys.path so we can import back
sys.path.insert(0, backend_dir)

from back import app, init_db

# Initialize database during startup (ensures it runs in production/gunicorn)
init_db()

if __name__ == "__main__":
    app.run(debug=True)
