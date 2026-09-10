"""
Script to start the Shiva backend server with Swagger documentation.
"""

import subprocess
import sys
import os

def start_server():
    """Start the FastAPI server with Swagger UI enabled."""
    print("Starting Shiva AI Support Platform Backend...")
    print("=" * 60)
    print("Swagger UI will be available at: http://localhost:8000/docs")
    print("ReDoc documentation: http://localhost:8000/redoc")
    print("OpenAPI Schema: http://localhost:8000/openapi.json")
    print("=" * 60)
    print()
    
    # Change to the backend directory
    backend_dir = os.path.join(os.path.dirname(__file__), "shiva_backend")
    os.chdir(backend_dir)
    
    # Start the server
    try:
        subprocess.run([
            sys.executable, "-m", "uvicorn", 
            "app.main:app",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--reload"
        ])
    except KeyboardInterrupt:
        print("\nServer stopped.")
    except Exception as e:
        print(f"Error starting server: {e}")

if __name__ == "__main__":
    start_server()