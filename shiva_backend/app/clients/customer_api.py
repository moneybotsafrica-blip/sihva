from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


class CustomerAccount:
    """Customer account data model."""

    def __init__(
        self,
        customer_id: str,
        email: str,
        name: str,
        plan: str,
        created_at: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.customer_id = customer_id
        self.email = email
        self.name = name
        self.plan = plan
        self.created_at = created_at
        self.metadata = metadata or {}


class CustomerApiClientInterface(ABC):
    """Abstract interface for Customer API client."""

    @abstractmethod
    async def get_account(self, customer_id: str) -> Optional[CustomerAccount]:
        """Fetch customer account information by ID."""
        pass

    @abstractmethod
    async def validate_customer(self, customer_id: str) -> bool:
        """Validate that a customer exists and is active."""
        pass


class CustomerApiClient(CustomerApiClientInterface):
    """Real implementation of Customer API client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or settings.customer_api_key
        self.base_url = base_url or settings.customer_api_base_url
        self.client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30.0,
        )

    async def get_account(self, customer_id: str) -> Optional[CustomerAccount]:
        """Fetch customer account information from external API."""
        try:
            response = await self.client.get(f"{self.base_url}/customers/{customer_id}")
            response.raise_for_status()
            data = response.json()

            return CustomerAccount(
                customer_id=data["id"],
                email=data["email"],
                name=data["name"],
                plan=data["plan"],
                created_at=data["created_at"],
                metadata=data.get("metadata"),
            )
        except httpx.HTTPStatusError as e:
            logger.error(
                "Failed to fetch customer account",
                customer_id=customer_id,
                status_code=e.response.status_code,
            )
            return None
        except Exception as e:
            logger.error(
                "Error fetching customer account",
                customer_id=customer_id,
                error=str(e),
            )
            return None

    async def validate_customer(self, customer_id: str) -> bool:
        """Validate that a customer exists and is active."""
        account = await self.get_account(customer_id)
        return account is not None

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
