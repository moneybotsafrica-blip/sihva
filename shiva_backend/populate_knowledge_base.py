"""
Script to populate Qdrant knowledge base with real Shiva Softwares documentation.
Run this after starting Qdrant to ingest the actual knowledge-base markdown files.
"""

import asyncio
import sys
from pathlib import Path
import re

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent))

from app.clients.qdrant_client import QdrantClient, Document
from app.config import settings
import structlog

logger = structlog.get_logger(__name__)


def extract_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter from markdown content."""
    frontmatter = {}
    if content.startswith('---'):
        end = content.find('---', 3)
        if end != -1:
            yaml_content = content[3:end].strip()
            # Simple YAML parsing for key: value pairs
            for line in yaml_content.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    frontmatter[key.strip()] = value.strip().strip('"\'')
    return frontmatter


def remove_frontmatter(content: str) -> str:
    """Remove YAML frontmatter from markdown content."""
    if content.startswith('---'):
        end = content.find('---', 3)
        if end != -1:
            return content[end+3:].strip()
    return content


def load_markdown_documents(kb_path: Path) -> list:
    """Load all markdown files from the knowledge base directory."""
    documents = []
    
    # Find all markdown files in the knowledge base
    md_files = list(kb_path.glob("**/*.md"))
    
    for md_file in md_files:
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract frontmatter
            frontmatter = extract_frontmatter(content)
            
            # Remove frontmatter from content for embedding
            clean_content = remove_frontmatter(content)
            
            # Use file path as ID if not in frontmatter
            doc_id = frontmatter.get('id', md_file.stem)
            title = frontmatter.get('title', md_file.stem)
            category = frontmatter.get('category', 'general')
            
            documents.append({
                "id": doc_id,
                "content": clean_content,
                "metadata": {
                    "title": title,
                    "category": category,
                    "file": str(md_file.relative_to(kb_path)),
                    **{k: v for k, v in frontmatter.items() if k not in ['id', 'title', 'category']}
                }
            })
            
            logger.info(
                "Loaded markdown document",
                doc_id=doc_id,
                title=title,
                file=str(md_file.relative_to(kb_path))
            )
            
        except Exception as e:
            logger.error(
                "Failed to load markdown file",
                file=str(md_file),
                error=str(e)
            )
    
    return documents


async def populate_knowledge_base():
    """Populate Qdrant with real Shiva Softwares documentation."""
    
    logger.info("Starting knowledge base population...")
    
    # Initialize Qdrant client
    qdrant_client = QdrantClient()
    
    # Path to knowledge base (parent directory of shiva_backend)
    kb_path = Path(__file__).parent.parent / "knowledge-base"
    
    if not kb_path.exists():
        logger.error("Knowledge base directory not found", path=str(kb_path))
        print(f"❌ Knowledge base directory not found: {kb_path}")
        return
    
    # Load markdown documents
    documents_data = load_markdown_documents(kb_path)
    
    if not documents_data:
        logger.warning("No markdown documents found in knowledge base")
        print("⚠️ No markdown documents found in knowledge base")
        return
    
    # Generate documents with embeddings
    documents_to_upsert = []
    
    for doc_data in documents_data:
        try:
            # Generate embedding for the document content
            embedding = await qdrant_client.embed_text(doc_data["content"])
            
            # Create document
            document = Document(
                id=doc_data["id"],
                vector=embedding,
                payload={
                    "content": doc_data["content"],
                    **doc_data["metadata"]
                }
            )
            
            documents_to_upsert.append(document)
            logger.info(
                "Generated embedding for document",
                doc_id=doc_data["id"],
                title=doc_data["metadata"]["title"]
            )
            
        except Exception as e:
            logger.error(
                "Failed to generate embedding for document",
                doc_id=doc_data["id"],
                error=str(e)
            )
    
    # Upsert documents to Qdrant
    if documents_to_upsert:
        try:
            success = await qdrant_client.upsert(documents_to_upsert)
            
            if success:
                logger.info(
                    "Successfully populated knowledge base",
                    document_count=len(documents_to_upsert)
                )
                print(f"\n✅ Successfully added {len(documents_to_upsert)} documents to knowledge base")
            else:
                logger.error("Failed to upsert documents to Qdrant")
                print("❌ Failed to add documents to knowledge base")
                
        except Exception as e:
            logger.error("Error upserting documents", error=str(e))
            print(f"❌ Error: {str(e)}")
    else:
        logger.warning("No documents to upsert")
        print("⚠️ No documents were prepared for upsert")


async def test_search():
    """Test vector search with sample queries relevant to Shiva Softwares."""
    
    logger.info("Testing vector search...")
    
    qdrant_client = QdrantClient()
    
    test_queries = [
        "How do I browse products?",
        "I can't login to my account",
        "Payment failed at checkout",
        "Track my order delivery",
        "Return policy for products"
    ]
    
    print("\n🔍 Testing vector search queries:")
    print("=" * 50)
    
    for query in test_queries:
        try:
            # Generate embedding for the query
            query_vector = await qdrant_client.embed_text(query)
            
            # Search for similar documents
            results = await qdrant_client.search(
                query_vector=query_vector,
                limit=3,
                score_threshold=0.5
            )
            
            print(f"\n📝 Query: '{query}'")
            if results:
                for i, result in enumerate(results, 1):
                    print(f"  {i}. [Score: {result.score:.3f}] {result.payload.get('title', 'No title')}")
                    print(f"     {result.payload.get('content', 'No content')[:100]}...")
            else:
                print("  No results found")
                
        except Exception as e:
            logger.error("Search failed", query=query, error=str(e))
            print(f"  ❌ Error: {str(e)}")


async def main():
    """Main function to populate and test knowledge base."""
    
    print("🚀 Shiva Softwares Knowledge Base Setup")
    print("=" * 50)
    
    # Populate knowledge base
    await populate_knowledge_base()
    
    # Test search functionality
    print("\n" + "=" * 50)
    await test_search()
    
    print("\n" + "=" * 50)
    print("✅ Knowledge base setup complete!")


if __name__ == "__main__":
    asyncio.run(main())
