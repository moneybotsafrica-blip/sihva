from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import Base

# Database engine configuration
# Handle both PostgreSQL and SQLite
if "postgresql" in settings.database_url:
    # PostgreSQL-specific configuration
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,  # Verify connections before using
        pool_size=settings.db_pool_size,  # Number of connections to maintain
        max_overflow=settings.db_max_overflow,  # Additional connections when pool is full
        pool_recycle=settings.db_pool_recycle,  # Recycle connections after configured time
        connect_args={
            "server_settings": {
                "application_name": "shiva_backend",
                "jit": "off",  # Disable JIT for better performance in some cases
            }
        }
    )
else:
    # SQLite configuration (for testing/development)
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        connect_args={"check_same_thread": False}  # Allow multi-threaded access
    )

async_session_maker = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def init_db() -> None:
    """Initialize database connection and create tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get async database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for database sessions."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
