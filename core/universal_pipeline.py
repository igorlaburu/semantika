"""Universal Pipeline for processing content from any source.

Orchestrates:
1. Content aggregation from source
2. Context unit generation (LLM)
3. Storage in database
4. Optional vector storage in Qdrant
"""

from typing import Dict, Any
import uuid
from datetime import datetime

from sources.base_source import SourceContent
from core.context_unit_generator import ContextUnitGenerator
from utils.supabase_client import get_supabase_client
from utils.qdrant_client import get_qdrant_client
from utils.logger import get_logger

logger = get_logger("universal_pipeline")


class UniversalPipeline:
    """Universal pipeline for processing content from any source."""

    def __init__(self):
        """Initialize pipeline."""
        self.generator = ContextUnitGenerator()
        self.supabase = get_supabase_client()
        logger.debug("universal_pipeline_initialized")

    async def process_source_content(
        self,
        source_content: SourceContent
    ) -> Dict[str, Any]:
        """
        Process content from any source through universal pipeline.

        Steps:
        1. Get organization configuration
        2. Generate context unit (LLM) with usage tracking
        3. Store in context_units table
        4. Optionally store in Qdrant

        Args:
            source_content: Unified content from source

        Returns:
            Dict with status, context_unit_id, context_unit
        """
        logger.info(
            "pipeline_start",
            org=source_content.organization_slug,
            source_type=source_content.source_type,
            source_id=source_content.source_id
        )

        try:
            # 1. Get organization
            org = await self._get_organization(source_content.organization_slug)
            if not org:
                raise ValueError(f"Organization not found: {source_content.organization_slug}")

            # 2. Generate context unit ID first (needed for usage tracking)
            cu_id = str(uuid.uuid4())

            # 3. Generate context unit using LLM (with usage tracking)
            logger.info("generating_context_unit", org=org["slug"])
            context_unit = await self.generator.generate(
                source_content=source_content,
                organization_id=org["id"],
                context_unit_id=None,  # Simple: just track usage without relation
                client_id=None  # Email source, no client_id
            )

            # 4. Store in database
            await self._store_context_unit(
                cu_id=cu_id,
                organization_id=org["id"],
                source_type=source_content.source_type,
                source_id=source_content.source_id,
                source_metadata=source_content.metadata,
                context_unit=context_unit
            )

            logger.info("context_unit_stored", cu_id=cu_id, org=org["slug"])

            # 4. Optional: Store in Qdrant
            qdrant_point_id = None
            if org.get("settings", {}).get("store_in_qdrant", False):
                logger.info("storing_in_qdrant", cu_id=cu_id)
                qdrant_point_id = await self._store_in_qdrant(
                    cu_id=cu_id,
                    context_unit=context_unit,
                    organization_id=org["id"]
                )
                logger.info("qdrant_stored", point_id=qdrant_point_id)

            return {
                "status": "ok",
                "context_unit_id": cu_id,
                "context_unit": context_unit,
                "qdrant_point_id": qdrant_point_id
            }

        except Exception as e:
            logger.error(
                "pipeline_error",
                org=source_content.organization_slug,
                source_type=source_content.source_type,
                error=str(e)
            )
            raise

    async def _get_organization(self, slug: str) -> Dict[str, Any]:
        """Get organization by slug."""
        try:
            result = self.supabase.client.table("organizations") \
                .select("*") \
                .eq("slug", slug) \
                .eq("is_active", True) \
                .single() \
                .execute()

            return result.data

        except Exception as e:
            logger.error("get_organization_error", slug=slug, error=str(e))
            return None

    async def _store_context_unit(
        self,
        cu_id: str,
        organization_id: str,
        source_type: str,
        source_id: str,
        source_metadata: Dict,
        context_unit: Dict[str, Any]
    ) -> None:
        """
        Store context unit in database.

        Args:
            cu_id: Pre-generated context unit UUID
            organization_id: Organization UUID
            source_type: Source type (email, api, etc.)
            source_id: Source identifier
            source_metadata: Source metadata
            context_unit: Generated context unit
        """
        try:
            data = {
                "id": cu_id,
                "organization_id": organization_id,
                "source_type": source_type,
                "source_id": source_id,
                "source_metadata": source_metadata,
                "title": context_unit.get("title", ""),
                "summary": context_unit.get("summary", ""),
                "tags": context_unit.get("tags", []),
                "atomic_statements": context_unit.get("atomic_statements", []),
                "raw_text": context_unit.get("raw_text", ""),
                "status": "completed",
                "processed_at": datetime.utcnow().isoformat()
            }

            result = self.supabase.client.table("context_units") \
                .insert(data) \
                .execute()

            logger.info("context_unit_inserted", cu_id=cu_id)

        except Exception as e:
            logger.error("store_context_unit_error", error=str(e))
            raise

    async def _store_in_qdrant(
        self,
        cu_id: str,
        context_unit: Dict[str, Any],
        organization_id: str
    ) -> str:
        """
        Store context unit in Qdrant vector database.

        Creates embedding from title + summary + atomic statements text.

        Args:
            cu_id: Context unit UUID
            context_unit: Context unit data
            organization_id: Organization UUID

        Returns:
            Qdrant point UUID
        """
        try:
            qdrant = get_qdrant_client()

            # Build text for embedding
            text_parts = [
                context_unit.get("title", ""),
                context_unit.get("summary", "")
            ]

            # Add atomic statements text
            for stmt in context_unit.get("atomic_statements", []):
                text_parts.append(stmt.get("text", ""))

            text = " ".join(text_parts)

            # Create point ID
            point_id = str(uuid.uuid4())

            # Store in Qdrant (using existing ingest logic)
            from core import IngestPipeline
            pipeline = IngestPipeline()

            # Use existing _ingest_to_qdrant method
            await pipeline._ingest_to_qdrant(
                client_id=organization_id,
                text=text,
                metadata={
                    "context_unit_id": cu_id,
                    "title": context_unit.get("title", ""),
                    "tags": context_unit.get("tags", []),
                    "source_type": "context_unit"
                }
            )

            # Update context_unit with qdrant_point_id
            self.supabase.client.table("context_units") \
                .update({"qdrant_point_id": point_id}) \
                .eq("id", cu_id) \
                .execute()

            return point_id

        except Exception as e:
            logger.error("store_qdrant_error", cu_id=cu_id, error=str(e))
            # Don't raise - Qdrant storage is optional
            return None

