from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class SearchResult:
    """Result from vector similarity search."""

    id: str
    score: float
    payload: Dict[str, Any]
    content: str


@dataclass
class Document:
    """Document for indexing in Qdrant."""

    id: str
    vector: List[float]
    payload: Dict[str, Any]


class QdrantClientInterface(ABC):
    """Abstract interface for Qdrant vector database client."""

    @abstractmethod
    async def search(
        self,
        query_vector: List[float],
        limit: int = 5,
        score_threshold: Optional[float] = None,
    ) -> List[SearchResult]:
        """Search for similar vectors in the knowledge base."""
        pass

    @abstractmethod
    async def embed_text(self, text: str) -> List[float]:
        """Convert text to embedding vector."""
        pass

    @abstractmethod
    async def upsert(self, documents: List[Document]) -> bool:
        """Upsert documents into the collection."""
        pass


class QdrantClient(QdrantClientInterface):
    """Real implementation of Qdrant client."""

    def __init__(
        self,
        url: Optional[str] = None,
        collection_name: Optional[str] = None,
        similarity_threshold: Optional[float] = None,
    ):
        self.url = url or settings.qdrant_url
        self.collection_name = collection_name or settings.qdrant_collection_name
        self.similarity_threshold = similarity_threshold or settings.qdrant_similarity_threshold

        # Initialize Qdrant client (placeholder - would use qdrant-client library)
        self._client = None

    async def _get_client(self):
        """Lazy initialization of Qdrant client."""
        if self._client is None:
            try:
                from qdrant_client import QdrantClient as Qdrant
                from qdrant_client.models import Distance, VectorParams, PointStruct

                self._client = Qdrant(url=self.url)
                
                # Ensure collection exists
                collections = self._client.get_collections().collections
                collection_names = [c.name for c in collections]
                
                if self.collection_name not in collection_names:
                    logger.info(
                        "Creating Qdrant collection",
                        collection_name=self.collection_name,
                    )
                    self._client.create_collection(
                        collection_name=self.collection_name,
                        vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
                    )
            except Exception as e:
                logger.error(
                    "Failed to initialize Qdrant client",
                    error=str(e)
                )
                raise

        return self._client

    async def search(
        self,
        query_vector: List[float],
        limit: int = 5,
        score_threshold: Optional[float] = None,
    ) -> List[SearchResult]:
        """Search for similar vectors in the knowledge base."""
        client = await self._get_client()
        threshold = score_threshold or self.similarity_threshold

        try:
            results = client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit,
                score_threshold=threshold,
            )

            return [
                SearchResult(
                    id=str(result.id),
                    score=result.score,
                    payload=result.payload or {},
                    content=result.payload.get("content", ""),
                )
                for result in results
            ]
        except Exception as e:
            logger.error(
                "Qdrant search failed",
                error=str(e),
            )
            return []

    async def embed_text(self, text: str) -> List[float]:
        """Convert text to embedding vector."""
        # This would typically use an embedding model
        # For now, return a placeholder
        # In production, integrate with OpenAI embeddings or similar
        logger.warning(
            "Using placeholder embedding - integrate with real embedding model",
            text_length=len(text),
        )
        return [0.0] * 1536  # Placeholder 1536-dimensional vector

    async def upsert(self, documents: List[Document]) -> bool:
        """Upsert documents into the collection."""
        client = await self._get_client()
        
        try:
            from qdrant_client.models import PointStruct
            
            points = [
                PointStruct(
                    id=doc.id,
                    vector=doc.vector,
                    payload=doc.payload
                )
                for doc in documents
            ]
            
            client.upsert(
                collection_name=self.collection_name,
                points=points
            )
            
            logger.info(
                "Upserted documents to Qdrant",
                count=len(documents),
                collection_name=self.collection_name
            )
            
            return True
            
        except Exception as e:
            logger.error(
                "Failed to upsert documents to Qdrant",
                error=str(e),
                count=len(documents)
            )
            return False


class MockQdrantClient(QdrantClientInterface):
    """Mock implementation for testing."""

    def __init__(self):
        self.documents: List[SearchResult] = []
        self.stored_documents: List[Document] = []
        
        # Add default knowledge base documents for common issues
        self._seed_default_knowledge_base()
    
    def _seed_default_knowledge_base(self):
        """Seed the mock knowledge base with common support documents."""
        default_docs = [
            SearchResult(
                id="kb_login_001",
                score=0.95,
                payload={
                    "title": "Login Issues Troubleshooting",
                    "content": "For login issues: Step 1: Verify username and password are correct. Step 2: Use password reset if needed. Step 3: Check account verification status. Step 4: Clear browser cache and cookies. Step 5: Try different browser or incognito mode. Step 6: Check 2FA settings if enabled. Step 7: Verify network connection and VPN settings. Step 8: Wait 15 minutes if account locked from failed attempts. Step 9: Check browser compatibility. Step 10: Confirm you're on the correct login URL."
                },
                content="For login issues: Step 1: Verify username and password are correct. Step 2: Use password reset if needed. Step 3: Check account verification status. Step 4: Clear browser cache and cookies. Step 5: Try different browser or incognito mode. Step 6: Check 2FA settings if enabled. Step 7: Verify network connection and VPN settings. Step 8: Wait 15 minutes if account locked from failed attempts. Step 9: Check browser compatibility. Step 10: Confirm you're on the correct login URL."
            ),
            SearchResult(
                id="kb_password_001", 
                score=0.92,
                payload={
                    "title": "Password Reset Guide",
                    "content": "To reset password: Step 1: Go to login page and click 'Forgot password'. Step 2: Enter registered email address. Step 3: Check email inbox and spam folder for reset link. Step 4: Click the reset link within 24 hours. Step 5: Create new password (8+ characters, mixed types). Step 6: Confirm new password. Step 7: Login with new credentials. Step 8: Update password in password manager if used."
                },
                content="To reset password: Step 1: Go to login page and click 'Forgot password'. Step 2: Enter registered email address. Step 3: Check email inbox and spam folder for reset link. Step 4: Click the reset link within 24 hours. Step 5: Create new password (8+ characters, mixed types). Step 6: Confirm new password. Step 7: Login with new credentials. Step 8: Update password in password manager if used."
            ),
            SearchResult(
                id="kb_payment_001",
                score=0.90,
                payload={
                    "title": "Payment Issues Resolution",
                    "content": "For payment issues: Step 1: Check payment method details in Settings > Billing. Step 2: Verify card has sufficient funds and isn't expired. Step 3: Ensure billing address matches card statement. Step 4: Try different payment method (credit card, PayPal). Step 5: Clear browser cache and try incognito mode. Step 6: Disable VPN temporarily. Step 7: Check payment gateway status. Step 8: Contact bank to authorize transaction. Step 9: Wait 24-48 hours for processing. Step 10: Check email for confirmation receipt."
                },
                content="For payment issues: Step 1: Check payment method details in Settings > Billing. Step 2: Verify card has sufficient funds and isn't expired. Step 3: Ensure billing address matches card statement. Step 4: Try different payment method (credit card, PayPal). Step 5: Clear browser cache and try incognito mode. Step 6: Disable VPN temporarily. Step 7: Check payment gateway status. Step 8: Contact bank to authorize transaction. Step 9: Wait 24-48 hours for processing. Step 10: Check email for confirmation receipt."
            )
        ]
        
        self.documents.extend(default_docs)

    def add_mock_document(self, document: SearchResult):
        """Add a mock document for testing."""
        self.documents.append(document)

    def clear_mock_documents(self):
        """Clear all mock documents for testing."""
        self.documents = []
        self.stored_documents = []
        # Re-seed default knowledge base
        self._seed_default_knowledge_base()

    async def search(
        self,
        query_vector: List[float],
        limit: int = 5,
        score_threshold: Optional[float] = None,
    ) -> List[SearchResult]:
        """Return mock search results based on stored documents."""
        threshold = score_threshold or 0.75
        
        # Start with manually added mock documents
        results = [doc for doc in self.documents if doc.score >= threshold]
        
        # Convert stored documents to search results with mock scores
        for doc in self.stored_documents:
            # Generate a mock score based on some simple heuristic
            # In a real implementation, this would be cosine similarity
            content = doc.payload.get('content', '')
            title = doc.payload.get('title', '')
            
            # Simple scoring: higher score if content is longer (just for mock)
            mock_score = min(0.95, 0.6 + (len(content) / 2000))
            
            if mock_score >= threshold:
                results.append(SearchResult(
                    id=doc.id,
                    score=mock_score,
                    payload=doc.payload,
                    content=content
                ))
        
        # Sort by score and return top results
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]

    async def embed_text(self, text: str) -> List[float]:
        """Return mock embedding."""
        return [0.0] * 1536

    async def upsert(self, documents: List[Document]) -> bool:
        """Mock upsert operation."""
        self.stored_documents.extend(documents)
        logger.info(
            "Mock upsert of documents",
            count=len(documents),
            total_stored=len(self.stored_documents)
        )
        return True

    async def _get_client(self):
        """Mock client initialization."""
        # Mock client doesn't need real initialization
        return None
