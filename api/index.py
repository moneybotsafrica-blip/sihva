"""
Vercel serverless function entry point for Shiva Backend.
This file allows Vercel to properly serve the FastAPI application.
"""

import sys
import os

# Add the backend directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'shiva_backend'))

from app.main import app

# Export the ASGI app for Vercel
app_handler = app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)