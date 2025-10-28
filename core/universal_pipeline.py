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

            # 1.5. Get company for workflow selection
            company = await self._get_company(org["company_id"])
            if not company:
                raise ValueError(f"Company not found for organization: {org['slug']}")

            # 2. Generate context unit ID first (needed for usage tracking)
            cu_id = str(uuid.uuid4())

            # 3. PHASE 3: Use company-specific workflow
            logger.info("using_company_workflow", 
                org=org["slug"], 
                company_code=company["company_code"]
            )
            
            from workflows.workflow_factory import get_workflow
            workflow = get_workflow(company["company_code"], company.get("settings", {}))
            
            # Process content through company workflow
            workflow_result = await workflow.process_content(source_content)
            context_unit = workflow_result["context_unit"]

            # 4. Store in database (include company_id)
            await self._store_context_unit(
                cu_id=cu_id,
                organization_id=org["id"],
                company_id=company["id"],
                source_type=source_content.source_type,
                source_id=source_content.source_id,
                source_metadata=source_content.metadata,
                context_unit=context_unit,
                workflow_result=workflow_result
            )

            logger.info("context_unit_stored", cu_id=cu_id, org=org["slug"], company_code=company["company_code"])

            # 5. Optional: Store in Qdrant (use workflow setting)
            qdrant_point_id = None
            if workflow.should_store_in_qdrant():
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
                "workflow_result": workflow_result,
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

    async def _get_company(self, company_id: str) -> Dict[str, Any]:
        """Get company by ID."""
        try:
            result = self.supabase.client.table("companies") \
                .select("*") \
                .eq("id", company_id) \
                .eq("is_active", True) \
                .single() \
                .execute()

            return result.data

        except Exception as e:
            logger.error("get_company_error", company_id=company_id, error=str(e))
            return None

    async def _store_context_unit(
        self,
        cu_id: str,
        organization_id: str,
        company_id: str,
        source_type: str,
        source_id: str,
        source_metadata: Dict,
        context_unit: Dict[str, Any],
        workflow_result: Dict[str, Any]
    ) -> None:
        """
        Store context unit in database.

        Args:
            cu_id: Pre-generated context unit UUID
            organization_id: Organization UUID
            company_id: Company UUID
            source_type: Source type (email, api, etc.)
            source_id: Source identifier
            source_metadata: Source metadata
            context_unit: Generated context unit
            workflow_result: Full workflow processing result
        """
        try:
            data = {
                "id": cu_id,
                "organization_id": organization_id,
                "company_id": company_id,
                "source_type": source_type,
                "source_id": source_id,
                "source_metadata": source_metadata,
                "title": context_unit.get("title", ""),
                "summary": context_unit.get("summary", ""),
                "tags": context_unit.get("tags", []),
                "atomic_statements": context_unit.get("atomic_statements", []),
                "raw_text": context_unit.get("raw_text", ""),
                "status": "completed",
                "processed_at": datetime.utcnow().isoformat(),
                # Store additional workflow data
                "workflow_data": {
                    "company_code": workflow_result.get("company_code"),
                    "analysis": workflow_result.get("analysis", {}),
                    "custom_data": workflow_result.get("custom_data", {})
                }
            }

            result = self.supabase.client.table("press_context_units") \
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
            self.supabase.client.table("press_context_units") \
                .update({"qdrant_point_id": point_id}) \
                .eq("id", cu_id) \
                .execute()

            return point_id

        except Exception as e:
            logger.error("store_qdrant_error", cu_id=cu_id, error=str(e))
            # Don't raise - Qdrant storage is optional
            return None

