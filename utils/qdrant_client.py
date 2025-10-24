"""Qdrant client for semantika vector storage.

Handles all vector storage operations including collection management,
document insertion, and semantic search.
"""

from typing import Optional, List, Dict, Any
from qdrant_client import QdrantClient as QClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from qdrant_client.models import Filter, FieldCondition, MatchValue, PayloadSchemaType

from .config import settings
from .logger import get_logger

logger = get_logger("qdrant_client")


class QdrantClient:
    """Qdrant client wrapper for semantika."""

    def __init__(self):
        """Initialize Qdrant client and ensure collection exists."""
        try:
            # Initialize Qdrant client (Cloud or local)
            if settings.qdrant_api_key:
                # Qdrant Cloud
                self.client = QClient(
                    url=settings.qdrant_url,
                    api_key=settings.qdrant_api_key
                )
                logger.info("qdrant_cloud_connected", url=settings.qdrant_url)
            else:
                # Local Qdrant
                self.client = QClient(url=settings.qdrant_url)
                logger.info("qdrant_local_connected", url=settings.qdrant_url)

            self.collection_name = settings.qdrant_collection_name

            # Ensure collection exists
            self._ensure_collection()

        except Exception as e:
            logger.error("qdrant_connection_failed", error=str(e))
            raise

    def _ensure_collection(self):
        """Ensure the collection exists, create if it doesn't."""
        try:
            collections = self.client.get_collections()
            collection_names = [c.name for c in collections.collections]

            if self.collection_name not in collection_names:
                logger.info("creating_collection", name=self.collection_name)

                # Create collection with fastembed default dimensions
                # fastembed/BAAI/bge-small-en-v1.5 uses 384 dimensions
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=384,  # fastembed default
                        distance=Distance.COSINE
                    )
                )

                logger.info("collection_created", name=self.collection_name)

                # Create payload index for client_id filtering
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="client_id",
                    field_schema=PayloadSchemaType.KEYWORD
                )

                logger.info("index_created", field="client_id")
            else:
                logger.info("collection_exists", name=self.collection_name)

        except Exception as e:
            logger.error("ensure_collection_error", error=str(e))
            raise

    def get_collection_info(self) -> Dict[str, Any]:
        """Get collection information."""
        try:
            info = self.client.get_collection(self.collection_name)
            return {
                "name": self.collection_name,
                "vectors_count": info.vectors_count if hasattr(info, 'vectors_count') else 0,
                "points_count": info.points_count if hasattr(info, 'points_count') else 0,
                "status": info.status if hasattr(info, 'status') else 'unknown'
            }
        except Exception as e:
            logger.error("get_collection_info_error", error=str(e))
            return {}

    async def add_points(
        self,
        points: List[PointStruct]
    ) -> List[str]:
        """
        Add points to the collection.

        Args:
            points: List of PointStruct objects

        Returns:
            List of point IDs added
        """
        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=points
            )

            point_ids = [str(p.id) for p in points]

            logger.info(
                "points_added",
                count=len(points),
                collection=self.collection_name
            )

            return point_ids

        except Exception as e:
            logger.error("add_points_error", error=str(e))
            raise

    async def search(
        self,
        query_vector: List[float],
        limit: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar vectors.

        Args:
            query_vector: Query embedding vector
            limit: Maximum number of results
            filter_dict: Filter conditions (e.g., {"client_id": "uuid"})

        Returns:
            List of search results with payload and score
        """
        try:
            # Build filter
            qdrant_filter = None
            if filter_dict:
                conditions = []
                for key, value in filter_dict.items():
                    conditions.append(
                        FieldCondition(
                            key=key,
                            match=MatchValue(value=value)
                        )
                    )

                if conditions:
                    qdrant_filter = Filter(must=conditions)

            # Search
            search_result = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit,
                query_filter=qdrant_filter
            )

            results = []
            for scored_point in search_result:
                results.append({
                    "id": str(scored_point.id),
                    "score": scored_point.score,
                    "payload": scored_point.payload
                })

            logger.debug(
                "search_completed",
                results_count=len(results),
                limit=limit
            )

            return results

        except Exception as e:
            logger.error("search_error", error=str(e))
            return []

    async def delete_points(self, point_ids: List[str]) -> bool:
        """Delete points by IDs."""
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=point_ids
            )

            logger.info("points_deleted", count=len(point_ids))
            return True

        except Exception as e:
            logger.error("delete_points_error", error=str(e))
            return False

    async def delete_by_filter(self, filter_dict: Dict[str, Any]) -> bool:
        """Delete points matching filter."""
        try:
            conditions = []
            for key, value in filter_dict.items():
                conditions.append(
                    FieldCondition(
                        key=key,
                        match=MatchValue(value=value)
                    )
                )

            qdrant_filter = Filter(must=conditions)

            self.client.delete(
                collection_name=self.collection_name,
                points_selector=qdrant_filter
            )

            logger.info("points_deleted_by_filter", filter=filter_dict)
            return True

        except Exception as e:
            logger.error("delete_by_filter_error", error=str(e))
            return False

    def delete_old_points(self, cutoff_timestamp: int, exclude_special: bool = True) -> int:
        """
        Delete old points based on TTL.

        Args:
            cutoff_timestamp: Unix timestamp - delete points older than this
            exclude_special: If True, don't delete points with special=true

        Returns:
            Number of points deleted
        """
        try:
            from qdrant_client.models import Range, FieldCondition, Filter

            # Build filter for old points
            must_conditions = [
                # Points with timestamp < cutoff_timestamp
                FieldCondition(
                    key="timestamp",
                    range=Range(lt=cutoff_timestamp)
                )
            ]

            must_not_conditions = []
            if exclude_special:
                # Exclude points with special=true
                must_not_conditions.append(
                    FieldCondition(
                        key="special",
                        match=MatchValue(value=True)
                    )
                )

            qdrant_filter = Filter(
                must=must_conditions,
                must_not=must_not_conditions if must_not_conditions else None
            )

            # Count points before deletion (for logging)
            count_result = self.client.count(
                collection_name=self.collection_name,
                count_filter=qdrant_filter,
                exact=True
            )
            count_to_delete = count_result.count

            if count_to_delete > 0:
                # Delete old points
                self.client.delete(
                    collection_name=self.collection_name,
                    points_selector=qdrant_filter
                )

                logger.info(
                    "old_points_deleted",
                    count=count_to_delete,
                    cutoff_timestamp=cutoff_timestamp
                )

            return count_to_delete

        except Exception as e:
            logger.error("delete_old_points_error", error=str(e))
            return 0


# Global Qdrant client instance
_qdrant_client: Optional[QdrantClient] = None


def get_qdrant_client() -> QdrantClient:
    """Get or create Qdrant client singleton."""
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient()
    return _qdrant_client
