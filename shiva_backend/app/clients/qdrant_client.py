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
        collection_name: Optional[str] = None,
        filter: Optional[Dict[str, Any]] = None,
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
        api_key: Optional[str] = None,
    ):
        self.url = url or settings.qdrant_url
        self.collection_name = collection_name or settings.qdrant_collection_name
        self.similarity_threshold = similarity_threshold or settings.qdrant_similarity_threshold
        self.api_key = api_key or getattr(settings, 'qdrant_api_key', None)

        # Initialize Qdrant client (placeholder - would use qdrant-client library)
        self._client = None

    async def _get_client(self):
        """Lazy initialization of Qdrant client."""
        if self._client is None:
            try:
                from qdrant_client import QdrantClient as Qdrant
                from qdrant_client.models import Distance, VectorParams, PointStruct

                # Connect with API key if provided (for Qdrant Cloud)
                if self.api_key:
                    self._client = Qdrant(url=self.url, api_key=self.api_key)
                else:
                    self._client = Qdrant(url=self.url)

                # Ensure collection exists
                collections = self._client.get_collections().collections
                collection_names = [c.name for c in collections]

                if self.collection_name not in collection_names:
                    logger.info(
                        "Creating Qdrant collection",
                        collection_name=self.collection_name,
                    )
                    # Use 384 dimensions for sentence-transformers all-MiniLM-L6-v2
                    self._client.create_collection(
                        collection_name=self.collection_name,
                        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
                    )
            except Exception as e:
                logger.error(
                    "Failed to initialize Qdrant client - will operate without knowledge base",
                    error=str(e)
                )
                # Don't raise - allow system to operate without Qdrant
                self._client = None
                return None

        return self._client

        return self._client

    async def search(
        self,
        query_vector: List[float],
        limit: int = 5,
        score_threshold: Optional[float] = None,
        collection_name: Optional[str] = None,
        filter: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Search for similar vectors in the knowledge base."""
        client = await self._get_client()
        
        # If Qdrant is not available, return empty results
        if client is None:
            logger.warning(
                "Qdrant client not available - returning empty search results",
                collection_name=collection_name or self.collection_name,
            )
            return []
        
        threshold = score_threshold or self.similarity_threshold
        target_collection = collection_name or self.collection_name

        try:
            if hasattr(client, "search"):
                results = client.search(
                    collection_name=target_collection,
                    query_vector=query_vector,
                    limit=limit,
                    score_threshold=threshold,
                    query_filter=filter,
                )
            else:
                query_response = client.query_points(
                    collection_name=target_collection,
                    query=query_vector,
                    limit=limit,
                    score_threshold=threshold,
                    query_filter=filter,
                )
                results = query_response.points

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
                collection_name=target_collection,
            )
            return []

    async def embed_text(self, text: str) -> List[float]:
        """Convert text to embedding vector using sentence-transformers."""
        try:
            from sentence_transformers import SentenceTransformer

            # Load a lightweight embedding model (cached after first load)
            if not hasattr(self, '_embedding_model'):
                logger.info("Loading sentence-transformers embedding model...")
                self._embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
                logger.info("Embedding model loaded successfully")

            # Generate embedding
            embedding = self._embedding_model.encode(text, convert_to_numpy=True)

            # Convert to list (384 dimensions for all-MiniLM-L6-v2)
            embedding_list = embedding.tolist()

            logger.debug(
                "Generated embedding",
                text_length=len(text),
                embedding_dim=len(embedding_list),
            )

            return embedding_list

        except ImportError:
            logger.warning(
                "sentence-transformers not installed - using placeholder embedding",
                text_length=len(text),
            )
            logger.info("Install sentence-transformers: pip install sentence-transformers")
            return [0.0] * 384  # Fallback to placeholder (384 dimensions for all-MiniLM-L6-v2)
        except Exception as e:
            logger.error(
                "Failed to generate embedding",
                error=str(e),
                text_length=len(text),
            )
            return [0.0] * 384  # Fallback to placeholder on error (384 dimensions for all-MiniLM-L6-v2)

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
