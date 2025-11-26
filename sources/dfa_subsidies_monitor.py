"""DFA Subsidies Monitor - Automated monitoring of forestry subsidies.

Monitors https://egoitza.araba.eus/es/-/tr-solicitar-ayudas-forestales
Uses SimHash for intelligent change detection (immune to trivial changes).
"""

import aiohttp
from typing import Dict, Optional
from datetime import datetime

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.content_hasher import compare_content
from workflows.subsidy_extraction_workflow import SubsidyExtractionWorkflow
from core.source_content import SourceContent

logger = get_logger("dfa_subsidies_monitor")

# Change detection threshold
SIMHASH_THRESHOLD = 0.90  # Trigger if similarity < 0.90


class DFASubsidiesMonitor:
    """Monitor DFA forestry subsidies page for changes."""
    
    def __init__(self):
        """Initialize DFA subsidies monitor."""
        self.supabase = get_supabase_client()
        logger.info("dfa_subsidies_monitor_initialized")
    
    async def fetch_page(self, url: str) -> Optional[str]:
        """
        Fetch HTML content from URL.
        
        Args:
            url: Page URL
            
        Returns:
            HTML content or None if failed
        """
        try:
            logger.info("fetching_page", url=url)
            
            timeout = aiohttp.ClientTimeout(total=30)
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; semantika/1.0; +https://ekimen.ai)'
            }
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        logger.error("fetch_failed",
                            url=url,
                            status=response.status
                        )
                        return None
                    
                    html = await response.text()
                    
                    logger.info("page_fetched",
                        url=url,
                        size_kb=len(html) / 1024
                    )
                    
                    return html
        
        except Exception as e:
            logger.error("fetch_error", url=url, error=str(e))
            return None
    
    async def check_for_updates(
        self,
        source: Dict,
        company: Dict
    ) -> bool:
        """
        Check if page has updates using SimHash detection.
        
        Args:
            source: Source configuration from database
            company: Company data
            
        Returns:
            True if changes detected and processed, False otherwise
        """
        try:
            target_url = source["config"]["target_url"]
            source_id = source["source_id"]
            company_id = company["id"]
            
            logger.info("dfa_update_check_start",
                source_id=source_id,
                url=target_url
            )
            
            # Step 1: Fetch current page
            html = await self.fetch_page(target_url)
            if not html:
                logger.error("update_check_failed_fetch", source_id=source_id)
                return False
            
            # Step 2: Get previous snapshot
            old_snapshot = source.get("source_metadata", {}).get("last_snapshot")
            
            # Step 3: Compare using SimHash
            comparison = compare_content(
                old_content=old_snapshot,
                new_html=html,
                simhash_threshold=source["config"].get("change_detection", {}).get("simhash_threshold", SIMHASH_THRESHOLD)
            )
            
            change_type = comparison["change_type"]
            similarity = comparison.get("similarity_score")
            
            logger.info("change_detection_result",
                source_id=source_id,
                change_type=change_type,
                similarity=similarity,
                detection_tier=comparison["detection_tier"]
            )
            
            # Step 4: Decide whether to process
            should_process = change_type in ["new", "minor_update", "major_update"]
            
            if not should_process:
                logger.info("no_significant_changes",
                    source_id=source_id,
                    change_type=change_type,
                    similarity=similarity
                )
                return False
            
            # Step 5: Process changes
            logger.info("processing_subsidy_updates",
                source_id=source_id,
                change_type=change_type
            )
            
            await self._process_subsidy_page(
                html=html,
                source=source,
                company=company,
                change_info=comparison
            )
            
            # Step 6: Save new snapshot
            await self._save_snapshot(
                source_id=source_id,
                comparison=comparison
            )
            
            logger.info("dfa_update_check_complete",
                source_id=source_id,
                change_type=change_type,
                processed=True
            )
            
            return True
        
        except Exception as e:
            logger.error("update_check_error",
                source_id=source.get("id"),
                error=str(e)
            )
            return False
    
    async def _process_subsidy_page(
        self,
        html: str,
        source: Dict,
        company: Dict,
        change_info: Dict
    ):
        """
        Process subsidy page using SubsidyExtractionWorkflow.
        
        Args:
            html: HTML content
            source: Source configuration
            company: Company data
            change_info: Change detection info
        """
        try:
            # Create SourceContent
            source_content = SourceContent(
                source_type="dfa_subsidies",
                source_id=source["source_id"],
                organization_slug=company["slug"],
                text_content=html,
                title="Subvenciones Forestales DFA",
                metadata={
                    "url": source["config"]["target_url"],
                    "company_id": company["id"],
                    "source_name": source["source_name"],
                    "change_type": change_info["change_type"],
                    "similarity": change_info.get("similarity_score"),
                    "detection_tier": change_info["detection_tier"],
                    "fetched_at": datetime.utcnow().isoformat()
                }
            )
            
            # Process with workflow
            workflow = SubsidyExtractionWorkflow(
                company_code=company["slug"],
                company_settings=company.get("settings", {})
            )
            
            result = await workflow.process_content(source_content)
            
            context_unit = result.get("context_unit", {})
            
            if not context_unit:
                logger.error("workflow_no_context_unit", source_id=source["id"])
                return
            
            # Save to web_context_units (using adapted ingester)
            from utils.unified_context_ingester import ingest_web_context_unit
            
            ingest_result = await ingest_web_context_unit(
                raw_text=context_unit.get("raw_text", ""),
                title=context_unit.get("title"),
                summary=context_unit.get("summary"),
                tags=context_unit.get("tags", []),
                category=context_unit.get("category", "subvenciones"),
                atomic_statements=context_unit.get("atomic_statements", []),
                
                company_id=company["id"],
                source_type="dfa_subsidies",
                source_id=source["source_id"],
                source_metadata=context_unit.get("source_metadata", {}),
                
                generate_embedding_flag=True,
                check_duplicates=True,
                replace_previous=True  # Replace old version
            )
            
            if ingest_result["success"]:
                logger.info("subsidy_context_unit_saved",
                    source_id=source["source_id"],
                    context_unit_id=ingest_result["context_unit_id"]
                )
            else:
                logger.error("subsidy_ingest_failed",
                    source_id=source["source_id"],
                    error=ingest_result.get("error")
                )
        
        except Exception as e:
            logger.error("subsidy_processing_error",
                source_id=source["source_id"],
                error=str(e)
            )
            raise
    
    async def _save_snapshot(
        self,
        source_id: str,
        comparison: Dict
    ):
        """
        Save content snapshot to source metadata.
        
        Args:
            source_id: Source UUID
            comparison: Comparison result with hashes
        """
        try:
            snapshot = {
                "content_hash": comparison["new_hash"],
                "simhash": comparison["new_simhash"],
                "checked_at": datetime.utcnow().isoformat(),
                "change_type": comparison["change_type"],
                "similarity": comparison.get("similarity_score")
            }
            
            # Update source metadata
            self.supabase.client.table("sources")\
                .update({
                    "source_metadata": {
                        "last_snapshot": snapshot
                    },
                    "updated_at": datetime.utcnow().isoformat()
                })\
                .eq("source_id", source_id)\
                .execute()
            
            logger.info("snapshot_saved",
                source_id=source_id,
                hash_prefix=comparison["new_hash"][:16]
            )
        
        except Exception as e:
            logger.error("snapshot_save_error",
                source_id=source_id,
                error=str(e)
            )


# Singleton instance
_monitor_instance = None

def get_dfa_subsidies_monitor() -> DFASubsidiesMonitor:
    """Get or create DFA subsidies monitor singleton."""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = DFASubsidiesMonitor()
    return _monitor_instance
