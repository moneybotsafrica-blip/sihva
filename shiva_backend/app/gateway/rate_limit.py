from typing import Dict
from datetime import datetime, timedelta, timezone
from fastapi import Request, HTTPException, status
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

# Create rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{settings.rate_limit_per_ip}/{settings.rate_limit_window_seconds}seconds"],
)


class RateLimitMiddleware:
    """Custom rate limiting middleware for customer-specific limits."""

    def __init__(self, app):
        self.app = app
        # In-memory rate limit storage (use Redis in production)
        self.customer_limits: Dict[str, Dict[str, int]] = {}
        self.ip_limits: Dict[str, Dict[str, int]] = {}

    async def __call__(self, scope, receive, send):
        """ASGI middleware for rate limiting."""
        if scope["type"] == "http":
            # Extract client info
            client_ip = self._get_client_ip(scope)
            customer_id = self._get_customer_id(scope)
            
            # Check IP-based rate limit
            if not self._check_ip_limit(client_ip):
                logger.warning("IP rate limit exceeded", ip=client_ip)
                # You could return a 429 response here
                # For now, we'll let the request proceed and let slowapi handle it
            
            # Check customer-specific rate limit
            if customer_id and not self._check_customer_limit(customer_id):
                logger.warning("Customer rate limit exceeded", customer_id=customer_id)
                # Return 429 response
                response = self._rate_limit_response()
                await send({
                    "type": "http.response.start",
                    "status": response["status"],
                    "headers": response["headers"],
                })
                await send({
                    "type": "http.response.body",
                    "body": response["body"],
                })
                return
        
        await self.app(scope, receive, send)

    def _get_client_ip(self, scope) -> str:
        """Extract client IP from ASGI scope."""
        headers = dict(scope.get("headers", []))
        
        # Check for forwarded headers (proxy/load balancer)
        x_forwarded_for = headers.get(b"x-forwarded-for")
        if x_forwarded_for:
            return x_forwarded_for.decode().split(",")[0].strip()
        
        x_real_ip = headers.get(b"x-real-ip")
        if x_real_ip:
            return x_real_ip.decode()
        
        # Fall back to direct client address
        client = scope.get("client")
        if client:
            return client[0]
        
        return "unknown"

    def _get_customer_id(self, scope) -> str:
        """Extract customer ID from request headers if available."""
        headers = dict(scope.get("headers", []))
        x_customer_id = headers.get(b"x-customer-id")
        if x_customer_id:
            return x_customer_id.decode()
        return None

    def _check_ip_limit(self, ip: str) -> bool:
        """Check if IP has exceeded rate limit."""
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=settings.rate_limit_window_seconds)
        
        if ip not in self.ip_limits:
            self.ip_limits[ip] = {"count": 0, "window_start": now}
        
        limit_data = self.ip_limits[ip]
        
        # Reset window if expired
        if limit_data["window_start"] < window_start:
            limit_data["count"] = 0
            limit_data["window_start"] = now
        
        # Check limit
        if limit_data["count"] >= settings.rate_limit_per_ip:
            return False
        
        limit_data["count"] += 1
        return True

    def _check_customer_limit(self, customer_id: str) -> bool:
        """Check if customer has exceeded rate limit."""
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=settings.rate_limit_window_seconds)
        
        if customer_id not in self.customer_limits:
            self.customer_limits[customer_id] = {"count": 0, "window_start": now}
        
        limit_data = self.customer_limits[customer_id]
        
        # Reset window if expired
        if limit_data["window_start"] < window_start:
            limit_data["count"] = 0
            limit_data["window_start"] = now
        
        # Check limit
        if limit_data["count"] >= settings.rate_limit_per_customer:
            return False
        
        limit_data["count"] += 1
        return True

    def _rate_limit_response(self) -> dict:
        """Generate a 429 Too Many Requests response."""
        return {
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"retry-after", str(settings.rate_limit_window_seconds).encode()),
            ],
            "body": b'{"error": "Rate limit exceeded", "message": "Too many requests"}',
        }

    def cleanup_old_entries(self):
        """Clean up old rate limit entries to prevent memory leaks."""
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=settings.rate_limit_window_seconds * 2)
        
        # Clean IP limits
        self.ip_limits = {
            ip: data
            for ip, data in self.ip_limits.items()
            if data["window_start"] > window_start
        }
        
        # Clean customer limits
        self.customer_limits = {
            customer_id: data
            for customer_id, data in self.customer_limits.items()
            if data["window_start"] > window_start
        }


# Rate limit exception handler
async def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded):
    """Handle rate limit exceptions."""
    logger.warning("Rate limit exceeded", path=request.url.path)
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Rate limit exceeded",
    )
