from typing import Optional, List
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog
import uuid

from app.db.models import APIKey, API_KEY_SCOPES
from app.db.session import async_session_maker

logger = structlog.get_logger(__name__)


class APIKeyService:
    """Service for managing API keys."""

    @staticmethod
    async def create_api_key(
        name: str,
        scope: str = "frontend",
        expires_in_days: Optional[int] = None,
        created_by: Optional[str] = None,
    ) -> dict:
        """
        Create a new API key.
        
        Args:
            name: Human-readable name for the key
            scope: Access scope (frontend, internal, admin)
            expires_in_days: Optional expiration in days
            created_by: User or system that created the key
            
        Returns:
            Dict with the generated key and key details
        """
        if scope not in API_KEY_SCOPES:
            raise ValueError(f"Invalid scope. Must be one of: {API_KEY_SCOPES}")

        # Generate the actual API key (this is the only time it's shown)
        api_key = APIKey.generate_key()
        key_hash = APIKey.hash_key(api_key)
        
        # Calculate expiration if provided
        expires_at = None
        if expires_in_days:
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

        async with async_session_maker() as session:
            api_key_record = APIKey(
                id=str(uuid.uuid4()),
                key_hash=key_hash,
                name=name,
                scope=scope,
                is_active=True,
                created_at=datetime.now(timezone.utc),
                expires_at=expires_at,
                created_by=created_by,
            )
            
            session.add(api_key_record)
            await session.commit()
            await session.refresh(api_key_record)
            
            logger.info(
                "API key created",
                key_id=api_key_record.id,
                name=name,
                scope=scope,
                created_by=created_by,
            )
            
            return {
                "id": api_key_record.id,
                "api_key": api_key,  # Only shown once at creation
                "name": name,
                "scope": scope,
                "is_active": True,
                "created_at": api_key_record.created_at.isoformat(),
                "expires_at": api_key_record.expires_at.isoformat() if api_key_record.expires_at else None,
                "created_by": created_by,
            }

    @staticmethod
    async def validate_api_key(api_key: str, required_scope: Optional[str] = None) -> Optional[dict]:
        """
        Validate an API key and return its details if valid.
        
        Args:
            api_key: The API key to validate
            required_scope: Optional required scope for the operation
            
        Returns:
            Dict with key details if valid, None otherwise
        """
        key_hash = APIKey.hash_key(api_key)
        
        async with async_session_maker() as session:
            result = await session.execute(
                select(APIKey).where(APIKey.key_hash == key_hash)
            )
            api_key_record = result.scalar_one_or_none()
            
            if not api_key_record:
                logger.warning("API key not found", key_hash=key_hash[:8] + "...")
                return None
            
            # Check if key is active
            if not api_key_record.is_active:
                logger.warning("API key is inactive", key_id=api_key_record.id)
                return None
            
            # Check if key has expired
            if api_key_record.expires_at and api_key_record.expires_at < datetime.now(timezone.utc):
                logger.warning("API key has expired", key_id=api_key_record.id)
                return None
            
            # Check scope if required
            if required_scope and api_key_record.scope != required_scope:
                # For now, allow admin keys to access everything
                if api_key_record.scope != "admin":
                    logger.warning(
                        "API key scope mismatch",
                        key_id=api_key_record.id,
                        required_scope=required_scope,
                        actual_scope=api_key_record.scope,
                    )
                    return None
            
            # Update last used timestamp
            api_key_record.last_used_at = datetime.now(timezone.utc)
            await session.commit()
            
            logger.info(
                "API key validated successfully",
                key_id=api_key_record.id,
                scope=api_key_record.scope,
            )
            
            return {
                "id": api_key_record.id,
                "name": api_key_record.name,
                "scope": api_key_record.scope,
                "is_active": api_key_record.is_active,
                "created_at": api_key_record.created_at.isoformat(),
                "expires_at": api_key_record.expires_at.isoformat() if api_key_record.expires_at else None,
                "last_used_at": api_key_record.last_used_at.isoformat() if api_key_record.last_used_at else None,
            }

    @staticmethod
    async def list_api_keys() -> List[dict]:
        """List all API keys (without the actual keys)."""
        async with async_session_maker() as session:
            result = await session.execute(select(APIKey))
            api_keys = result.scalars().all()
            
            return [
                {
                    "id": key.id,
                    "name": key.name,
                    "scope": key.scope,
                    "is_active": key.is_active,
                    "created_at": key.created_at.isoformat(),
                    "expires_at": key.expires_at.isoformat() if key.expires_at else None,
                    "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
                    "created_by": key.created_by,
                }
                for key in api_keys
            ]

    @staticmethod
    async def deactivate_api_key(key_id: str) -> bool:
        """Deactivate an API key."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(APIKey).where(APIKey.id == key_id)
            )
            api_key = result.scalar_one_or_none()
            
            if not api_key:
                return False
            
            api_key.is_active = False
            await session.commit()
            
            logger.info("API key deactivated", key_id=key_id)
            return True

    @staticmethod
    async def delete_api_key(key_id: str) -> bool:
        """Delete an API key permanently."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(APIKey).where(APIKey.id == key_id)
            )
            api_key = result.scalar_one_or_none()
            
            if not api_key:
                return False
            
            await session.delete(api_key)
            await session.commit()
            
            logger.info("API key deleted", key_id=key_id)
            return True