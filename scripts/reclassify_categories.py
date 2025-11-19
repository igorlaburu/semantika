"""Reclassify context units that are in 'general' category.

Uses the same classification logic as analyze_atomic to properly categorize
existing context units based on their title and summary.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv()

from utils.supabase_client import get_supabase_client
from utils.llm_registry import get_llm_registry
from utils.logger import get_logger

logger = get_logger("reclassify_categories")

# Category classification prompt (same as analyze_atomic)
CLASSIFICATION_PROMPT = """Classify this news content into ONE category from this list:
- política: Government, legislation, councils, elections, institutions
- economía: Business, employment, finance, commerce, industry
- sociedad: Social services, education, housing, citizenship
- cultura: Cultural events, art, heritage, festivals, museums
- deportes: Sports competitions, teams, facilities
- tecnología: Technology, innovation, digital, startups
- medio_ambiente: Environment, climate, sustainability, nature
- infraestructuras: Infrastructure, construction, transportation, urban planning
- seguridad: Safety, police, emergencies, civil protection
- salud: Health, hospitals, public health, medicine
- turismo: Tourism, hotels, visitors, destinations
- internacional: International relations, global news
- general: Generic information, no clear category

Title: {title}
Summary: {summary}

Respond with ONLY the category name (one word, lowercase, using underscore if needed).
Choose the MOST relevant category. Only use "general" if the content truly doesn't fit any specific category.

Category:"""


async def classify_content(title: str, summary: str, registry) -> str:
    """Classify content using LLM.

    Args:
        title: Content title
        summary: Content summary
        registry: LLM registry

    Returns:
        Category name
    """
    try:
        provider = registry.get('groq_fast')

        prompt = CLASSIFICATION_PROMPT.format(
            title=title or "Sin título",
            summary=summary or "Sin resumen"
        )

        messages = [
            {"role": "system", "content": "You are a news categorization expert."},
            {"role": "user", "content": prompt}
        ]

        response = await provider.ainvoke(messages)
        category = response.content.strip().lower()

        # Validate category
        valid_categories = [
            'política', 'economía', 'sociedad', 'cultura', 'deportes',
            'tecnología', 'medio_ambiente', 'infraestructuras', 'seguridad',
            'salud', 'turismo', 'internacional', 'general'
        ]

        if category not in valid_categories:
            logger.warn("invalid_category_returned",
                category=category,
                title=title[:50]
            )
            return 'general'

        return category

    except Exception as e:
        logger.error("classification_error",
            error=str(e),
            title=title[:50]
        )
        return 'general'


async def reclassify_general_units(batch_size: int = 10, limit: int = None):
    """Reclassify context units in 'general' category.

    Args:
        batch_size: Number of units to process concurrently
        limit: Maximum number of units to process (None for all)
    """
    logger.info("reclassify_start", batch_size=batch_size, limit=limit)

    supabase = get_supabase_client()
    registry = get_llm_registry()

    # Fetch units with category='general'
    query = supabase.client.table("press_context_units")\
        .select("id, title, summary, category")\
        .eq("category", "general")

    if limit:
        query = query.limit(limit)

    result = query.execute()

    if not result.data:
        logger.info("no_units_to_reclassify")
        return

    units = result.data
    total = len(units)

    logger.info("units_fetched", total=total)

    # Process in batches
    updated = 0
    errors = 0
    category_counts = {}

    for i in range(0, total, batch_size):
        batch = units[i:i+batch_size]
        logger.info("processing_batch",
            batch_num=i//batch_size + 1,
            batch_size=len(batch),
            progress=f"{i}/{total}"
        )

        # Classify batch
        tasks = [
            classify_content(unit['title'], unit['summary'], registry)
            for unit in batch
        ]
        categories = await asyncio.gather(*tasks)

        # Update database
        for unit, category in zip(batch, categories):
            try:
                if category != 'general':
                    supabase.client.table("press_context_units")\
                        .update({"category": category})\
                        .eq("id", unit['id'])\
                        .execute()

                    updated += 1
                    category_counts[category] = category_counts.get(category, 0) + 1

                    logger.info("unit_reclassified",
                        unit_id=unit['id'],
                        title=unit['title'][:50],
                        old_category='general',
                        new_category=category
                    )
                else:
                    logger.debug("unit_remains_general",
                        unit_id=unit['id'],
                        title=unit['title'][:50]
                    )

            except Exception as e:
                errors += 1
                logger.error("update_error",
                    unit_id=unit['id'],
                    error=str(e)
                )

        # Small delay between batches to avoid rate limits
        if i + batch_size < total:
            await asyncio.sleep(1)

    logger.info("reclassify_completed",
        total=total,
        updated=updated,
        errors=errors,
        still_general=total - updated - errors,
        category_distribution=category_counts
    )

    print(f"\n✅ Reclassification completed:")
    print(f"   Total processed: {total}")
    print(f"   Updated: {updated}")
    print(f"   Errors: {errors}")
    print(f"   Still general: {total - updated - errors}")
    print(f"\n📊 New category distribution:")
    for cat, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"   {cat}: {count}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Reclassify context units from 'general' category")
    parser.add_argument("--batch-size", type=int, default=10,
                       help="Number of units to process concurrently (default: 10)")
    parser.add_argument("--limit", type=int, default=None,
                       help="Maximum number of units to process (default: all)")

    args = parser.parse_args()

    asyncio.run(reclassify_general_units(
        batch_size=args.batch_size,
        limit=args.limit
    ))
