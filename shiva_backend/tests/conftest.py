import pytest
import asyncio
from typing import AsyncGenerator, Optional
import os

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.config import settings


# Override database URL for testing
# Use in-memory SQLite for fast tests, or use PostgreSQL if TEST_USE_POSTGRES is set
TEST_USE_POSTGRES = os.getenv("TEST_USE_POSTGRES", "false").lower() == "true"

if TEST_USE_POSTGRES:
    # Use a separate test database in PostgreSQL
    TEST_DATABASE_URL = settings.database_url.replace(
        "/shiva_support", "/shiva_support_test"
    )
else:
    # Use in-memory SQLite for fast testing
    TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def engine():
    """Create a test database engine."""
    if TEST_USE_POSTGRES:
        # For PostgreSQL, use NullPool to avoid connection pooling issues in tests
        from sqlalchemy.pool import NullPool
        engine = create_async_engine(
            TEST_DATABASE_URL,
            poolclass=NullPool,
        )
    else:
        # For SQLite, use StaticPool with in-memory database
        engine = create_async_engine(
            TEST_DATABASE_URL,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="function")
async def async_session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session."""
    async_session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with async_session_maker() as session:
        yield session


@pytest.fixture
def mock_user():
    """Create a mock user for testing."""
    from app.gateway.auth import User

    return User(
        id="test_user_123",
        email="test@example.com",
        role="customer",
    )


@pytest.fixture
def mock_staff_user():
    """Create a mock staff user for testing."""
    from app.gateway.auth import User

    return User(
        id="staff_123",
        email="staff@example.com",
        role="staff",
    )


@pytest.fixture
def mock_developer_user():
    """Create a mock developer user for testing."""
    from app.gateway.auth import User

    return User(
        id="dev_123",
        email="dev@example.com",
        role="developer",
    )



