from typing import Optional, Any
from dataclasses import dataclass
from fastapi import Request, HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext
import structlog

from app.config import settings
from app.api_keys.service import APIKeyService

logger = structlog.get_logger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@dataclass
class User:
    """User context for authentication."""
    id: str
    email: str
    role: str  # "customer", "staff", or "developer"


@dataclass
class GraphQLContext:
    """GraphQL context with authentication and database session."""
    request: Request
    current_user: Optional[User]
    session: Any


class AuthContext:
    """Authentication context builder for GraphQL."""

    @staticmethod
    def decode_token(token: str) -> Optional[User]:
        """
        Decode JWT token and return user context.
        In production, this would validate against your auth provider.
        """
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
            )
            
            user_id = payload.get("sub")
            email = payload.get("email")
            role = payload.get("role", "customer")
            
            if not user_id:
                return None
            
            return User(id=user_id, email=email, role=role)
            
        except JWTError as e:
            logger.warning("JWT decode failed", error=str(e))
            return None

    @staticmethod
    def create_token(user: User) -> str:
        """Create a JWT token for a user."""
        payload = {
            "sub": user.id,
            "email": user.email,
            "role": user.role,
        }
        
        token = jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        
        return token

    @staticmethod
    async def get_context(request: Request) -> dict:
        """
        Build GraphQL context with authentication and session.
        This is called by Strawberry for each GraphQL request.
        """
        # Extract token from Authorization header
        auth_header = request.headers.get("Authorization")
        current_user = None
        api_key_info = None
        
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]  # Remove "Bearer " prefix
            
            # Try JWT token first
            current_user = AuthContext.decode_token(token)
            
            # If JWT fails, try API key
            if not current_user:
                api_key_info = await APIKeyService.validate_api_key(token)
                if api_key_info:
                    # Create a user context from API key
                    current_user = User(
                        id=f"api_key_{api_key_info['id']}",
                        email=f"api_key_{api_key_info['name']}@system",
                        role=api_key_info['scope']  # Use scope as role
                    )
                    logger.info(
                        "Request authenticated via API key",
                        key_name=api_key_info['name'],
                        scope=api_key_info['scope']
                    )
        
        if not current_user:
            # For development, create a mock user if authentication fails
            logger.warning("Unauthenticated request, using mock customer")
            current_user = User(
                id="cust_001",
                email="customer@example.com",
                role="customer"
            )
        
        # For development, allow all mock users
        # In production, you'd validate properly
        logger.info(f"Request authenticated as: {current_user.role if current_user else 'none'}")
        
        # Get database session from request state (set by middleware)
        from app.db.session import async_session_maker
        session = async_session_maker()
        
        # Make context cleanup happen after request
        request.state.db_session = session
        
        return {
            "request": request,
            "current_user": current_user,
            "session": session,
            "api_key_info": api_key_info,
        }


class AuthMiddleware:
    """Authentication middleware for protecting endpoints."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        """ASGI middleware for authentication."""
        if scope["type"] == "http":
            # For HTTP requests, we'll handle auth in the route handlers
            # This middleware just ensures the request can proceed
            await self.app(scope, receive, send)
        else:
            await self.app(scope, receive, send)
