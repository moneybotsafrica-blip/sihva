import asyncio
import sys
from pathlib import Path

# Add the backend directory to the path
backend_dir = Path(__file__).parent / "shiva_backend"
sys.path.insert(0, str(backend_dir))

from app.api_keys.service import APIKeyService
from app.db.session import init_db

async def create_frontend_api_key():
    """Create an API key for the frontend application."""
    try:
        # Initialize database first
        print("Initializing database...")
        await init_db()
        print("Database initialized successfully!")
        
        result = await APIKeyService.create_api_key(
            name="Frontend Application",
            scope="frontend",
            expires_in_days=365,
            created_by="admin"
        )
        
        print("API Key Created Successfully!")
        print("=" * 50)
        print(f"API Key: {result['api_key']}")
        print(f"Key ID: {result['id']}")
        print(f"Name: {result['name']}")
        print(f"Scope: {result['scope']}")
        print(f"Expires: {result['expires_at']}")
        print("=" * 50)
        print("SAVE THIS API KEY SECURELY - IT WILL NOT BE SHOWN AGAIN!")
        print()
        print("Usage in frontend:")
        print("Authorization: Bearer " + result['api_key'])
        
        return result
        
    except Exception as e:
        print(f"Error creating API key: {e}")
        return None

if __name__ == "__main__":
    asyncio.run(create_frontend_api_key())