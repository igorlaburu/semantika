"""Core ingestion pipeline for semantika.

Handles document processing with guardrails, deduplication, and chunking.
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any

from fastembed import TextEmbedding
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client.models import PointStruct

from utils.logger import get_logger
from utils.config import settings
from utils.openrouter_client import get_openrouter_client
from utils.qdrant_client import get_qdrant_client

logger = get_logger("core_ingest")

# Initialize embedding model (singleton)
_embedding_model: Optional[TextEmbedding] = None


def get_embedding_model() -> TextEmbedding:
    """Get or create embedding model singleton."""
    global _embedding_model
    if _embedding_model is None:
        logger.info("initializing_embedding_model")
        _embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    return _embedding_model


class IngestPipeline:
    """Core ingestion pipeline with guardrails."""

    def __init__(self, client_id: str):
        """
        Initialize pipeline for a specific client.

        Args:
            client_id: UUID of the client
        """
        self.client_id = client_id
        self.openrouter = get_openrouter_client()
        self.qdrant = get_qdrant_client()
        self.embedder = get_embedding_model()
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""]
        )

        logger.info("pipeline_initialized", client_id=client_id)

    async def ingest_text(
        self,
        text: str,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        skip_guardrails: bool = False
    ) -> Dict[str, Any]:
        """
        Ingest text document with full pipeline.

        Args:
            text: Document text
            title: Document title (optional)
            metadata: Additional metadata
            skip_guardrails: Skip PII/Copyright checks (for testing)

        Returns:
            Ingestion result with stats
        """
        logger.info(
            "ingest_start",
            client_id=self.client_id,
            text_length=len(text),
            title=title
        )

        result = {
            "status": "ok",
            "documents_added": 0,
            "chunks_created": 0,
            "duplicates_skipped": 0,
            "pii_detected": False,
            "pii_anonymized": False,
            "copyright_rejected": False,
            "errors": []
        }

        try:
            # 1. GUARDRAIL: PII Detection
            if not skip_guardrails:
                pii_result = await self.openrouter.detect_pii(text)

                if pii_result.get("has_pii", False):
                    result["pii_detected"] = True
                    entities = pii_result.get("entities", [])

                    # Anonymize PII
                    text = await self.openrouter.anonymize_pii(text, entities)
                    result["pii_anonymized"] = True

                    logger.warn(
                        "pii_anonymized",
                        client_id=self.client_id,
                        entities_count=len(entities)
                    )

            # 2. GUARDRAIL: Copyright Detection
            if not skip_guardrails:
                copyright_result = await self.openrouter.detect_copyright(text)

                if copyright_result.get("is_copyrighted", False):
                    confidence = copyright_result.get("confidence", 0.0)
                    if confidence > 0.7:  # High confidence threshold
                        result["copyright_rejected"] = True
                        result["status"] = "rejected"
                        result["errors"].append("Copyrighted content detected")

                        logger.warn(
                            "copyright_rejected",
                            client_id=self.client_id,
                            confidence=confidence
                        )
                        return result

            # 3. Chunking
            chunks = self.text_splitter.split_text(text)
            result["chunks_created"] = len(chunks)

            logger.debug("text_chunked", chunks_count=len(chunks))

            # 4. Generate embeddings
            embeddings = list(self.embedder.embed(chunks))

            # 5. Deduplication check
            unique_chunks = []
            unique_embeddings = []
            duplicates = 0

            for chunk, embedding in zip(chunks, embeddings):
                is_duplicate = await self._check_duplicate(
                    list(embedding),
                    threshold=settings.similarity_threshold
                )

                if is_duplicate:
                    duplicates += 1
                    logger.debug("duplicate_detected", chunk_preview=chunk[:50])
                else:
                    unique_chunks.append(chunk)
                    unique_embeddings.append(embedding)

            result["duplicates_skipped"] = duplicates

            # 6. Prepare metadata
            base_metadata = {
                "client_id": self.client_id,
                "title": title or "Untitled",
                "loaded_at": datetime.utcnow().isoformat() + "Z",
                "source": metadata.get("source", "manual") if metadata else "manual",
                "pii_anonymized": result["pii_anonymized"]
            }

            # Merge with custom metadata
            if metadata:
                for key, value in metadata.items():
                    if key not in base_metadata:
                        base_metadata[key] = value

            # 7. Upload to Qdrant
            points = []
            for i, (chunk, embedding) in enumerate(zip(unique_chunks, unique_embeddings)):
                point_id = str(uuid.uuid4())
                chunk_metadata = {
                    **base_metadata,
                    "chunk_index": i,
                    "chunk_text": chunk
                }

                points.append(
                    PointStruct(
                        id=point_id,
                        vector=list(embedding),
                        payload=chunk_metadata
                    )
                )

            if points:
                await self.qdrant.add_points(points)
                result["documents_added"] = len(points)

                logger.info(
                    "ingest_completed",
                    client_id=self.client_id,
                    documents_added=len(points),
                    duplicates=duplicates
                )
            else:
                logger.info(
                    "ingest_no_new_documents",
                    client_id=self.client_id,
                    all_duplicates=True
                )

            return result

        except Exception as e:
            logger.error("ingest_error", client_id=self.client_id, error=str(e))
            result["status"] = "error"
            result["errors"].append(str(e))
            return result

    async def _check_duplicate(
        self,
        embedding: List[float],
        threshold: float = 0.98
    ) -> bool:
        """
        Check if embedding is duplicate.

        Args:
            embedding: Query embedding
            threshold: Similarity threshold (0-1)

        Returns:
            True if duplicate found
        """
        try:
            # Search for similar vectors in client's collection
            results = await self.qdrant.search(
                query_vector=embedding,
                limit=1,
                filter_dict={"client_id": self.client_id}
            )

            if results and len(results) > 0:
                top_score = results[0].get("score", 0.0)
                if top_score >= threshold:
                    return True

            return False

        except Exception as e:
            logger.error("duplicate_check_error", error=str(e))
            return False  # On error, don't skip (conservative)

    async def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Semantic search in client's documents.

        Args:
            query: Search query
            limit: Maximum results
            filters: Additional filters (e.g., {"source": "web"})

        Returns:
            List of search results
        """
        try:
            logger.info("search_start", client_id=self.client_id, query=query)

            # Generate query embedding
            query_embedding = list(self.embedder.embed([query]))[0]

            # Prepare filters (always include client_id)
            search_filters = {"client_id": self.client_id}
            if filters:
                search_filters.update(filters)

            # Search
            results = await self.qdrant.search(
                query_vector=list(query_embedding),
                limit=limit,
                filter_dict=search_filters
            )

            logger.info(
                "search_completed",
                client_id=self.client_id,
                results_count=len(results)
            )

            return results

        except Exception as e:
            logger.error("search_error", client_id=self.client_id, error=str(e))
            return []

    async def aggregate(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.7
    ) -> Dict[str, Any]:
        """
        Search and aggregate results with LLM.

        Args:
            query: Search query
            limit: Maximum documents to retrieve
            threshold: Minimum similarity score

        Returns:
            Aggregation result with summary
        """
        try:
            logger.info("aggregate_start", client_id=self.client_id, query=query)

            # Search documents
            results = await self.search(query, limit=limit)

            # Filter by threshold
            filtered_results = [
                r for r in results
                if r.get("score", 0.0) >= threshold
            ]

            if not filtered_results:
                return {
                    "summary": "No relevant documents found.",
                    "sources_count": 0,
                    "documents": []
                }

            # Extract texts
            documents = [
                r["payload"].get("chunk_text", "")
                for r in filtered_results
            ]

            # Generate summary
            summary = await self.openrouter.aggregate_documents(documents, query)

            logger.info(
                "aggregate_completed",
                client_id=self.client_id,
                sources_count=len(filtered_results)
            )

            return {
                "summary": summary,
                "sources_count": len(filtered_results),
                "documents": filtered_results
            }

        except Exception as e:
            logger.error("aggregate_error", client_id=self.client_id, error=str(e))
            return {
                "summary": "Error generating summary.",
                "sources_count": 0,
                "documents": [],
                "error": str(e)
            }
