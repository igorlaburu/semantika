"""Multi-tier change detection for monitored URLs.

Combines hash-based, SimHash, and embedding-based detection:
- Tier 1: SHA256 hash (exact match)
- Tier 2: SimHash (fuzzy match for minor changes)
- Tier 3: Embeddings (semantic similarity for major changes)

Integrates with content_hasher.py and embedding_generator.py.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime

from .content_hasher import (
    compute_content_hashes,
    detect_change_tier,
    compare_content
)
from .embedding_generator import (
    generate_embedding,
    cosine_similarity
)
from .logger import get_logger

logger = get_logger("change_detector")


class ChangeDetector:
    """Multi-tier change detection system."""
    
    def __init__(
        self,
        simhash_threshold: float = 0.95,
        embedding_threshold: float = 0.90,
        use_embeddings: bool = True
    ):
        """Initialize change detector.
        
        Args:
            simhash_threshold: Threshold for SimHash similarity (0.0-1.0)
            embedding_threshold: Threshold for embedding similarity (0.0-1.0)
            use_embeddings: Enable Tier 3 embedding checks (costly)
        """
        self.simhash_threshold = simhash_threshold
        self.embedding_threshold = embedding_threshold
        self.use_embeddings = use_embeddings
        
        logger.info("change_detector_initialized",
            simhash_threshold=simhash_threshold,
            embedding_threshold=embedding_threshold,
            use_embeddings=use_embeddings
        )
    
    async def detect_change(
        self,
        old_content: Optional[Dict[str, Any]],
        new_html: Optional[str] = None,
        new_text: Optional[str] = None,
        new_title: Optional[str] = None,
        new_summary: Optional[str] = None,
        company_id: Optional[str] = None,
        url: Optional[str] = None
    ) -> Dict[str, Any]:
        """Detect change type using multi-tier strategy.
        
        Args:
            old_content: Previous content with 'content_hash', 'simhash', 'embedding'
            new_html: New HTML content
            new_text: New plain text content
            new_title: New content title (for embedding)
            new_summary: New content summary (for embedding)
            company_id: Company UUID for logging
            url: URL being checked
            
        Returns:
            Dict with:
            - change_type: new/identical/trivial/minor_update/major_update
            - detection_tier: 1/2/3
            - similarity_score: float or None
            - new_hash: SHA256 hash
            - new_simhash: SimHash value
            - new_embedding: Embedding vector (if Tier 3 used)
            - requires_processing: bool (should this change be ingested?)
        """
        logger.debug("detect_change_start",
            company_id=company_id,
            url=url,
            has_old_content=bool(old_content)
        )
        
        # Step 1 & 2: Hash-based detection (Tier 1 & 2)
        hash_result = compare_content(
            old_content=old_content,
            new_html=new_html,
            new_text=new_text,
            simhash_threshold=self.simhash_threshold
        )
        
        change_type = hash_result["change_type"]
        detection_tier = hash_result["detection_tier"]
        similarity_score = hash_result.get("similarity_score")
        
        # Prepare result
        result = {
            "change_type": change_type,
            "detection_tier": detection_tier,
            "similarity_score": similarity_score,
            "new_hash": hash_result["new_hash"],
            "new_simhash": hash_result["new_simhash"],
            "new_embedding": None,
            "requires_processing": False
        }
        
        # Determine if processing required based on Tier 1 & 2
        if change_type == "new":
            result["requires_processing"] = True
            logger.info("change_detected_new_content", url=url)
            return result
        
        elif change_type == "identical":
            result["requires_processing"] = False
            logger.debug("change_detected_identical", url=url)
            return result
        
        elif change_type == "trivial":
            result["requires_processing"] = False
            logger.debug("change_detected_trivial", url=url, similarity=similarity_score)
            return result
        
        elif change_type == "minor_update":
            # Minor updates might not need reprocessing
            result["requires_processing"] = False
            logger.info("change_detected_minor", url=url, similarity=similarity_score)
            return result
        
        # Step 3: Embedding check for major_update (Tier 3)
        elif change_type == "major_update":
            if not self.use_embeddings:
                # No embedding check - assume it's a major change
                result["requires_processing"] = True
                logger.info("change_detected_major_no_embedding_check", url=url)
                return result
            
            # Generate new embedding
            if not new_title:
                # No title available, can't generate embedding
                logger.warn("major_update_no_title_for_embedding", url=url)
                result["requires_processing"] = True
                return result
            
            try:
                new_embedding = await generate_embedding(
                    title=new_title,
                    summary=new_summary,
                    company_id=company_id
                )
                
                result["new_embedding"] = new_embedding
                
                # Compare with old embedding if available
                old_embedding = old_content.get("embedding") if old_content else None
                
                if old_embedding:
                    embedding_similarity = cosine_similarity(old_embedding, new_embedding)
                    
                    logger.info("embedding_similarity_computed",
                        url=url,
                        similarity=round(embedding_similarity, 4)
                    )
                    
                    if embedding_similarity >= self.embedding_threshold:
                        # Semantically similar - not a real major update
                        result["change_type"] = "minor_update"
                        result["detection_tier"] = 3
                        result["similarity_score"] = embedding_similarity
                        result["requires_processing"] = False
                        
                        logger.info("major_update_downgraded_to_minor",
                            url=url,
                            embedding_similarity=embedding_similarity
                        )
                    else:
                        # Semantically different - confirmed major update
                        result["change_type"] = "major_update"
                        result["detection_tier"] = 3
                        result["similarity_score"] = embedding_similarity
                        result["requires_processing"] = True
                        
                        logger.info("major_update_confirmed",
                            url=url,
                            embedding_similarity=embedding_similarity
                        )
                else:
                    # No old embedding - assume major update
                    result["requires_processing"] = True
                    logger.info("major_update_no_old_embedding", url=url)
                
            except Exception as e:
                logger.error("embedding_generation_failed", url=url, error=str(e))
                # Fallback: assume major update
                result["requires_processing"] = True
            
            return result
        
        # Shouldn't reach here
        logger.warn("unexpected_change_type", change_type=change_type, url=url)
        result["requires_processing"] = False
        return result
    
    async def should_update_content(
        self,
        old_monitored_url: Optional[Dict[str, Any]],
        new_html: str,
        new_title: str,
        new_summary: Optional[str] = None,
        company_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """High-level: Should we update this monitored URL?
        
        Args:
            old_monitored_url: Previous monitored_url record
            new_html: New HTML content
            new_title: New title
            new_summary: New summary
            company_id: Company UUID
            
        Returns:
            Dict with:
            - should_update: bool
            - change_info: Full change detection result
        """
        url = old_monitored_url.get("url") if old_monitored_url else "unknown"
        
        change_info = await self.detect_change(
            old_content=old_monitored_url,
            new_html=new_html,
            new_title=new_title,
            new_summary=new_summary,
            company_id=company_id,
            url=url
        )
        
        should_update = change_info["requires_processing"]
        
        logger.info("should_update_content_decision",
            url=url,
            should_update=should_update,
            change_type=change_info["change_type"],
            detection_tier=change_info["detection_tier"]
        )
        
        return {
            "should_update": should_update,
            "change_info": change_info
        }


# Global detector instance
_change_detector: Optional[ChangeDetector] = None


def get_change_detector(
    simhash_threshold: float = 0.95,
    embedding_threshold: float = 0.90,
    use_embeddings: bool = True
) -> ChangeDetector:
    """Get or create global change detector singleton.
    
    Args:
        simhash_threshold: Threshold for SimHash similarity
        embedding_threshold: Threshold for embedding similarity
        use_embeddings: Enable Tier 3 embedding checks
        
    Returns:
        ChangeDetector instance
    """
    global _change_detector
    
    if _change_detector is None:
        _change_detector = ChangeDetector(
            simhash_threshold=simhash_threshold,
            embedding_threshold=embedding_threshold,
            use_embeddings=use_embeddings
        )
    
    return _change_detector


# Convenience functions

async def detect_url_change(
    old_url_data: Optional[Dict[str, Any]],
    new_html: str,
    new_title: str,
    new_summary: Optional[str] = None,
    company_id: Optional[str] = None,
    url: Optional[str] = None
) -> Dict[str, Any]:
    """Convenience function for detecting URL changes.
    
    Args:
        old_url_data: Previous monitored_url record
        new_html: New HTML content
        new_title: New title
        new_summary: New summary
        company_id: Company UUID
        url: URL being checked
        
    Returns:
        Change detection result
    """
    detector = get_change_detector()
    
    return await detector.detect_change(
        old_content=old_url_data,
        new_html=new_html,
        new_title=new_title,
        new_summary=new_summary,
        company_id=company_id,
        url=url
    )


async def check_if_content_changed(
    old_hash: Optional[str],
    new_html: str,
    simhash_threshold: float = 0.95
) -> bool:
    """Quick check: Has content changed? (No embedding check)
    
    Args:
        old_hash: Previous SHA256 hash
        new_hash: New content to hash
        simhash_threshold: Threshold for trivial changes
        
    Returns:
        True if content has meaningfully changed
    """
    from .content_hasher import compute_content_hashes
    
    new_hash, new_simhash = compute_content_hashes(html=new_html)
    
    # First time seeing content
    if not old_hash:
        return True
    
    # Exact match
    if old_hash == new_hash:
        return False
    
    # Changed, but we don't have old simhash to compare
    # Assume it changed
    return True
