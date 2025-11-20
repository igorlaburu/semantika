"""Unified novelty verification for all context unit sources.

Phase 1: Verify if content is novel BEFORE generating context unit.

Source-specific verification strategies:
- Scraping: Hash/SimHash comparison (reuse change_detector.py)
- Email: Message-ID lookup in database
- Perplexity: Title + date in 24h window
- API/Manual: Skip verification (always novel)
"""

from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from .change_detector import get_change_detector
from .supabase_client import get_supabase_client
from .logger import get_logger

logger = get_logger("unified_context_verifier")


async def verify_novelty(
    source_type: str,
    content_data: Dict[str, Any],
    company_id: str
) -> Dict[str, Any]:
    """Verify if content is novel before processing.

    Args:
        source_type: Source type (scraping/email/perplexity/api/manual)
        content_data: Source-specific data for verification
        company_id: Company UUID

    Returns:
        Dict with:
        - is_novel: bool (True if should be processed)
        - reason: str (explanation)
        - duplicate_id: Optional[str] (if duplicate found)
        - verification_metadata: Dict (source-specific verification data)
    """
    logger.debug("verify_novelty_start",
        source_type=source_type,
        company_id=company_id
    )

    if source_type == "scraping":
        return await _verify_scraping_novelty(content_data, company_id)

    elif source_type == "email":
        return await _verify_email_novelty(content_data, company_id)

    elif source_type == "perplexity":
        return await _verify_perplexity_novelty(content_data, company_id)

    elif source_type in ["api", "manual"]:
        # API and manual entries skip verification (always novel)
        logger.debug("skip_verification_api_manual", source_type=source_type)
        return {
            "is_novel": True,
            "reason": f"{source_type} source - verification skipped",
            "duplicate_id": None,
            "verification_metadata": {}
        }

    else:
        logger.warn("unknown_source_type", source_type=source_type)
        # Unknown source type - assume novel to avoid blocking
        return {
            "is_novel": True,
            "reason": f"Unknown source type: {source_type} - defaulting to novel",
            "duplicate_id": None,
            "verification_metadata": {}
        }


async def _verify_scraping_novelty(
    content_data: Dict[str, Any],
    company_id: str
) -> Dict[str, Any]:
    """Verify novelty for scraping source using hash/SimHash/embedding detection.

    Args:
        content_data: Dict with:
            - old_monitored_url: Optional[Dict] (previous monitored_url record)
            - new_html: str (new HTML content)
            - new_title: str (new title)
            - new_summary: Optional[str] (new summary)
            - url: str (URL being scraped)
            - url_type: str (single/multi_noticia)
            - content_items: Optional[List[Dict]] (for multi_noticia)

    Returns:
        Novelty verification result
    """
    old_monitored_url = content_data.get("old_monitored_url")
    new_html = content_data.get("new_html")
    new_title = content_data.get("new_title")
    new_summary = content_data.get("new_summary")
    url = content_data.get("url")
    url_type = content_data.get("url_type", "single")

    logger.debug("verify_scraping_novelty",
        url=url,
        url_type=url_type,
        has_old_content=bool(old_monitored_url)
    )

    # Multi-noticia handling: Check for new titles
    if url_type == "multi_noticia":
        content_items = content_data.get("content_items", [])

        if old_monitored_url and old_monitored_url.get("url_content_units"):
            # Get existing titles from url_content_units
            supabase = get_supabase_client()

            try:
                # Fetch existing url_content_units for this monitored URL
                result = supabase.client.table("url_content_units").select(
                    "title"
                ).eq("monitored_url_id", old_monitored_url["id"]).execute()

                existing_titles = {unit["title"] for unit in result.data}

                # Check for new items
                new_items = [
                    item for item in content_items
                    if item.get("title") not in existing_titles
                ]

                if new_items:
                    logger.info("multi_noticia_new_items_found",
                        url=url,
                        new_count=len(new_items),
                        total_count=len(content_items)
                    )
                    return {
                        "is_novel": True,
                        "reason": f"Found {len(new_items)} new items in multi-noticia page",
                        "duplicate_id": None,
                        "verification_metadata": {
                            "url_type": "multi_noticia",
                            "new_items_count": len(new_items),
                            "new_items": [item.get("title") for item in new_items]
                        }
                    }
                else:
                    logger.debug("multi_noticia_no_new_items",
                        url=url,
                        existing_count=len(existing_titles)
                    )
                    return {
                        "is_novel": False,
                        "reason": "No new items in multi-noticia page",
                        "duplicate_id": None,
                        "verification_metadata": {
                            "url_type": "multi_noticia",
                            "existing_count": len(existing_titles)
                        }
                    }

            except Exception as e:
                logger.error("multi_noticia_title_check_error",
                    url=url,
                    error=str(e)
                )
                # On error, assume novel to avoid blocking
                return {
                    "is_novel": True,
                    "reason": "Error checking multi-noticia titles - defaulting to novel",
                    "duplicate_id": None,
                    "verification_metadata": {"error": str(e)}
                }
        else:
            # First time scraping this multi-noticia page
            logger.info("multi_noticia_first_scrape", url=url)
            return {
                "is_novel": True,
                "reason": "First scrape of multi-noticia page",
                "duplicate_id": None,
                "verification_metadata": {
                    "url_type": "multi_noticia",
                    "items_count": len(content_items)
                }
            }

    # Single article: Use change_detector
    try:
        detector = get_change_detector()

        change_info = await detector.detect_change(
            old_content=old_monitored_url,
            new_html=new_html,
            new_title=new_title,
            new_summary=new_summary,
            company_id=company_id,
            url=url
        )

        is_novel = change_info["requires_processing"]

        if is_novel:
            logger.info("scraping_change_detected",
                url=url,
                change_type=change_info["change_type"],
                detection_tier=change_info["detection_tier"]
            )
        else:
            logger.debug("scraping_no_change",
                url=url,
                change_type=change_info["change_type"]
            )

        return {
            "is_novel": is_novel,
            "reason": f"Change detection: {change_info['change_type']} (tier {change_info['detection_tier']})",
            "duplicate_id": None,
            "verification_metadata": {
                "url_type": "single",
                "change_type": change_info["change_type"],
                "detection_tier": change_info["detection_tier"],
                "similarity_score": change_info.get("similarity_score"),
                "new_hash": change_info.get("new_hash"),
                "new_simhash": change_info.get("new_simhash"),
                "new_embedding": change_info.get("new_embedding")
            }
        }

    except Exception as e:
        logger.error("scraping_change_detection_error",
            url=url,
            error=str(e)
        )
        # On error, assume novel to avoid blocking
        return {
            "is_novel": True,
            "reason": "Error during change detection - defaulting to novel",
            "duplicate_id": None,
            "verification_metadata": {"error": str(e)}
        }


async def _verify_email_novelty(
    content_data: Dict[str, Any],
    company_id: str
) -> Dict[str, Any]:
    """Verify novelty for email source using Message-ID lookup.

    Args:
        content_data: Dict with:
            - message_id: str (email Message-ID header)
            - subject: Optional[str] (for logging)
            - source_id: str (email source UUID)

    Returns:
        Novelty verification result
    """
    message_id = content_data.get("message_id")
    subject = content_data.get("subject", "No subject")
    source_id = content_data.get("source_id")

    if not message_id:
        logger.warn("email_no_message_id", subject=subject[:50])
        # No Message-ID - assume novel (risky but avoids blocking)
        return {
            "is_novel": True,
            "reason": "No Message-ID header - cannot verify",
            "duplicate_id": None,
            "verification_metadata": {}
        }

    logger.debug("verify_email_novelty",
        message_id=message_id,
        subject=subject[:50]
    )

    try:
        supabase = get_supabase_client()

        # Check if context unit with this Message-ID already exists
        result = supabase.client.table("press_context_units").select(
            "id, title, created_at"
        ).eq("company_id", company_id).eq(
            "source_id", source_id
        ).contains(
            "source_metadata", {"message_id": message_id}
        ).limit(1).execute()

        if result.data and len(result.data) > 0:
            existing = result.data[0]
            logger.info("email_duplicate_found",
                message_id=message_id,
                duplicate_id=existing["id"],
                duplicate_title=existing.get("title", "")[:50]
            )
            return {
                "is_novel": False,
                "reason": f"Email with Message-ID already processed",
                "duplicate_id": existing["id"],
                "verification_metadata": {
                    "message_id": message_id,
                    "duplicate_created_at": existing.get("created_at")
                }
            }
        else:
            logger.debug("email_novel",
                message_id=message_id,
                subject=subject[:50]
            )
            return {
                "is_novel": True,
                "reason": "Email Message-ID not found in database",
                "duplicate_id": None,
                "verification_metadata": {
                    "message_id": message_id
                }
            }

    except Exception as e:
        logger.error("email_novelty_check_error",
            message_id=message_id,
            error=str(e)
        )
        # On error, assume novel to avoid blocking
        return {
            "is_novel": True,
            "reason": "Error checking Message-ID - defaulting to novel",
            "duplicate_id": None,
            "verification_metadata": {"error": str(e)}
        }


async def _verify_perplexity_novelty(
    content_data: Dict[str, Any],
    company_id: str
) -> Dict[str, Any]:
    """Verify novelty for Perplexity source using title + date in 24h window.

    Args:
        content_data: Dict with:
            - title: str (news item title)
            - source_id: str (perplexity source UUID)
            - date_published: Optional[str] (ISO format)

    Returns:
        Novelty verification result
    """
    title = content_data.get("title")
    source_id = content_data.get("source_id")
    date_published = content_data.get("date_published")

    if not title:
        logger.warn("perplexity_no_title")
        # No title - assume novel (risky but avoids blocking)
        return {
            "is_novel": True,
            "reason": "No title provided - cannot verify",
            "duplicate_id": None,
            "verification_metadata": {}
        }

    logger.debug("verify_perplexity_novelty",
        title=title[:50],
        date_published=date_published
    )

    try:
        supabase = get_supabase_client()

        # Check for duplicate title in last 24h
        # (Perplexity news items are typically recent)
        time_threshold = (datetime.utcnow() - timedelta(hours=24)).isoformat()

        result = supabase.client.table("press_context_units").select(
            "id, title, created_at"
        ).eq("company_id", company_id).eq(
            "source_id", source_id
        ).eq("source_type", "perplexity").eq(
            "title", title
        ).gte("created_at", time_threshold).limit(1).execute()

        if result.data and len(result.data) > 0:
            existing = result.data[0]
            logger.info("perplexity_duplicate_found",
                title=title[:50],
                duplicate_id=existing["id"],
                created_at=existing.get("created_at")
            )
            return {
                "is_novel": False,
                "reason": "Perplexity item with same title found in last 24h",
                "duplicate_id": existing["id"],
                "verification_metadata": {
                    "title": title,
                    "duplicate_created_at": existing.get("created_at"),
                    "window_hours": 24
                }
            }
        else:
            logger.debug("perplexity_novel",
                title=title[:50]
            )
            return {
                "is_novel": True,
                "reason": "Perplexity item title not found in last 24h",
                "duplicate_id": None,
                "verification_metadata": {
                    "title": title,
                    "window_hours": 24
                }
            }

    except Exception as e:
        logger.error("perplexity_novelty_check_error",
            title=title[:50] if title else "No title",
            error=str(e)
        )
        # On error, assume novel to avoid blocking
        return {
            "is_novel": True,
            "reason": "Error checking Perplexity title - defaulting to novel",
            "duplicate_id": None,
            "verification_metadata": {"error": str(e)}
        }
