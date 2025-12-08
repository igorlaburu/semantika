"""Pool client for Qdrant - manages shared news pool.

Wrapper around Qdrant client specifically for Pool collection with:
- Fixed company_id="pool"
- 768-dimensional embeddings (FastEmbed multilingual)
- Quality scoring and filtering
- Adoption tracking
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

from qdrant_client import QdrantClient as QClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue, MatchAny, Range,
    PayloadSchemaType
)

from .config import settings
from .logger import get_logger
from .embedding_generator import generate_embedding

logger = get_logger("pool_client")

POOL_COMPANY_ID = "pool"
QUALITY_THRESHOLD = 0.4


class PoolClient:
    """Client for Pool collection in Qdrant."""
    
    def __init__(self):
        """Initialize Pool client."""
        try:
            # Initialize Qdrant client
            if settings.qdrant_api_key:
                self.client = QClient(
                    url=settings.qdrant_url,
                    api_key=settings.qdrant_api_key
                )
                logger.info("pool_qdrant_connected", url=settings.qdrant_url)
            else:
                raise ValueError("Qdrant API key required for Pool")
            
            self.collection_name = settings.pool_collection_name
            
            # Ensure collection exists with 768d
            self._ensure_collection()
        
        except Exception as e:
            logger.error("pool_client_init_error", error=str(e))
            raise
    
    def _ensure_collection(self):
        """Ensure Pool collection exists with correct config."""
        try:
            collections = self.client.get_collections()
            collection_names = [c.name for c in collections.collections]
            
            if self.collection_name not in collection_names:
                logger.info("creating_pool_collection", name=self.collection_name)
                
                # Create with 768d for FastEmbed multilingual
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=768,  # FastEmbed multilingual
                        distance=Distance.COSINE
                    )
                )
                
                logger.info("pool_collection_created", name=self.collection_name)
                
                # Create indexes
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="company_id",
                    field_schema=PayloadSchemaType.KEYWORD
                )
                
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="source_id",
                    field_schema=PayloadSchemaType.KEYWORD
                )
                
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="category",
                    field_schema=PayloadSchemaType.KEYWORD
                )
                
                logger.info("pool_indexes_created")
            else:
                logger.info("pool_collection_exists", name=self.collection_name)
        
        except Exception as e:
            logger.error("ensure_pool_collection_error", error=str(e))
            raise
    
    async def ingest_to_pool(
        self,
        title: str,
        content: str,
        url: str,
        source_id: str,
        quality_score: float,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        published_at: Optional[str] = None,
        atomic_statements: Optional[List[Dict]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Ingest content to Pool.
        
        Args:
            title: Title
            content: Full text
            url: Source URL
            source_id: Source UUID
            quality_score: Quality score (0.0-1.0)
            category: Category
            tags: Tags list
            published_at: Publication date
            atomic_statements: Atomic facts
            metadata: Additional metadata
        
        Returns:
            Dict with success, point_id, etc.
        """
        # Validate quality
        if quality_score < QUALITY_THRESHOLD:
            logger.warn("pool_ingest_rejected_quality",
                title=title[:50],
                quality_score=quality_score
            )
            return {
                "success": False,
                "reason": "quality_too_low",
                "quality_score": quality_score
            }
        
        logger.info("pool_ingest_start", title=title[:50], source_id=source_id)
        
        try:
            # Generate embedding (768d)
            embedding = await generate_embedding(
                title=title,
                summary=content[:500],
                company_id=POOL_COMPANY_ID
            )
            
            # Check duplicates
            similar = await self._check_duplicate(embedding)
            
            if similar:
                logger.warn("pool_duplicate_found",
                    title=title[:50],
                    duplicate_id=similar["id"],
                    similarity=similar["score"]
                )
                return {
                    "success": False,
                    "reason": "duplicate",
                    "duplicate_id": similar["id"],
                    "similarity": similar["score"]
                }
            
            # Create point ID from URL
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, url))
            
            # Build payload
            payload = {
                "company_id": POOL_COMPANY_ID,
                "source_id": source_id,
                "title": title,
                "summary": content[:500],
                "content": content[:2000],
                "url": url,
                "category": category or "general",
                "tags": tags or [],
                "quality_score": quality_score,
                "published_at": published_at or datetime.utcnow().isoformat(),
                "ingested_at": datetime.utcnow().isoformat(),
                "atomic_statements": atomic_statements or [],
                "adoption_count": 0,
                **(metadata or {})
            }
            
            # Insert
            point = PointStruct(
                id=point_id,
                vector=embedding,
                payload=payload
            )
            
            self.client.upsert(
                collection_name=self.collection_name,
                points=[point]
            )
            
            logger.info("pool_point_inserted",
                point_id=point_id,
                title=title[:50],
                quality_score=quality_score
            )
            
            return {
                "success": True,
                "point_id": point_id,
                "quality_score": quality_score,
                "duplicate": False
            }
        
        except Exception as e:
            logger.error("pool_ingest_error", title=title[:50], error=str(e))
            return {
                "success": False,
                "reason": "error",
                "error": str(e)
            }
    
    async def _check_duplicate(self, embedding: List[float]) -> Optional[Dict]:
        """Check for duplicates by embedding similarity."""
        try:
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=embedding,
                limit=1,
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="company_id",
                            match=MatchValue(value=POOL_COMPANY_ID)
                        )
                    ]
                )
            )
            
            if results and len(results) > 0:
                top = results[0]
                if top.score >= 0.98:
                    return {
                        "id": str(top.id),
                        "score": top.score
                    }
            
            return None
        
        except Exception as e:
            logger.error("duplicate_check_error", error=str(e))
            return None
    
    async def search(
        self,
        query_text: str,
        limit: int = 10,
        categories: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        min_quality: Optional[float] = None,
        tags: Optional[List[str]] = None,
        score_threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """
        Search in Pool with filters.
        
        Args:
            query_text: Search query
            limit: Max results
            categories: Category filter
            date_from: Date range start
            date_to: Date range end
            min_quality: Min quality score
            tags: Tag filter
            score_threshold: Min similarity
        
        Returns:
            List of results with payload and score
        """
        try:
            # Generate query embedding
            embedding = await generate_embedding(
                title=query_text,
                summary="",
                company_id=POOL_COMPANY_ID
            )
            
            # Build filters
            conditions = [
                FieldCondition(
                    key="company_id",
                    match=MatchValue(value=POOL_COMPANY_ID)
                )
            ]
            
            if categories:
                conditions.append(
                    FieldCondition(
                        key="category",
                        match=MatchAny(any=categories)
                    )
                )
            
            if date_from or date_to:
                range_dict = {}
                if date_from:
                    range_dict["gte"] = date_from
                if date_to:
                    range_dict["lte"] = date_to
                conditions.append(
                    FieldCondition(
                        key="published_at",
                        range=Range(**range_dict)
                    )
                )
            
            if min_quality:
                conditions.append(
                    FieldCondition(
                        key="quality_score",
                        range=Range(gte=min_quality)
                    )
                )
            
            if tags:
                conditions.append(
                    FieldCondition(
                        key="tags",
                        match=MatchAny(any=tags)
                    )
                )
            
            query_filter = Filter(must=conditions) if conditions else None
            
            # Search
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=embedding,
                limit=limit,
                query_filter=query_filter,
                score_threshold=score_threshold
            )
            
            # Format results
            formatted = []
            for r in results:
                formatted.append({
                    "id": str(r.id),
                    "score": r.score,
                    **r.payload
                })
            
            logger.debug("pool_search_completed",
                query=query_text[:50],
                results=len(formatted)
            )
            
            return formatted
        
        except Exception as e:
            logger.error("pool_search_error", error=str(e))
            return []
    
    def get_by_id(self, point_id: str) -> Optional[Dict[str, Any]]:
        """Get context unit by ID."""
        try:
            points = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[point_id],
                with_payload=True,
                with_vectors=False
            )
            
            if points and len(points) > 0:
                return {
                    "id": str(points[0].id),
                    **points[0].payload
                }
            
            return None
        
        except Exception as e:
            logger.error("pool_get_by_id_error", point_id=point_id, error=str(e))
            return None
    
    def register_adoption(self, point_id: str, adopted_by_company: str):
        """Register adoption of Pool item."""
        try:
            # Get current point
            point = self.get_by_id(point_id)
            
            if not point:
                logger.warn("adoption_point_not_found", point_id=point_id)
                return
            
            # Increment adoption count
            current_count = point.get("adoption_count", 0)
            
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={
                    "adoption_count": current_count + 1,
                    "last_adopted_at": datetime.utcnow().isoformat()
                },
                points=[point_id]
            )
            
            logger.info("adoption_registered",
                point_id=point_id,
                new_count=current_count + 1
            )
        
        except Exception as e:
            logger.error("register_adoption_error", error=str(e))
    
    def get_stats(self) -> Dict[str, Any]:
        """Get Pool statistics."""
        try:
            # Count total points
            count_result = self.client.count(
                collection_name=self.collection_name,
                count_filter=Filter(
                    must=[
                        FieldCondition(
                            key="company_id",
                            match=MatchValue(value=POOL_COMPANY_ID)
                        )
                    ]
                ),
                exact=True
            )
            
            return {
                "total_context_units": count_result.count,
                "collection_name": self.collection_name
            }
        
        except Exception as e:
            logger.error("get_pool_stats_error", error=str(e))
            return {"total_context_units": 0}


# Singleton
_pool_client: Optional[PoolClient] = None

def get_pool_client() -> PoolClient:
    """Get Pool client singleton."""
    global _pool_client
    if _pool_client is None:
        _pool_client = PoolClient()
    return _pool_client
