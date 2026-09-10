"""
Initialize default routing rules and destinations.

This script populates the database with default routing rules that mirror
the static patterns from the legacy classifier, enabling dynamic routing
while maintaining the same behavior.

Run this script after running database migrations to set up the routing system.
"""
import asyncio
import sys
from pathlib import Path

# Add the parent directory to the path to import app modules
sys.path.insert(0, str(Path(__file__).parent))

from app.db.session import get_db_context
from app.ai_router.classifier import initialize_default_routing_rules
import structlog

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger(__name__)


async def main():
    """Main function to initialize routing rules."""
    logger.info("Starting routing rules initialization...")
    
    try:
        async with get_db_context() as session:
            await initialize_default_routing_rules(session)
            await session.commit()
            
        logger.info("Routing rules initialization completed successfully")
        print("✓ Default routing rules and destinations initialized successfully")
        print("\nYou can now:")
        print("  - Use the /routing API endpoints to manage rules")
        print("  - Enable dynamic routing in AIRouter by setting use_dynamic_routing=True")
        print("  - Customize rules based on your specific needs")
        
    except Exception as e:
        logger.error("Failed to initialize routing rules", error=str(e))
        print(f"✗ Failed to initialize routing rules: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
