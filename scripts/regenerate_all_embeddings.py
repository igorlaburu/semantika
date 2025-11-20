#!/usr/bin/env python3
"""Regenerate embeddings for all context units without embeddings."""

import asyncio
import os
from typing import List, Dict
from fastembed import TextEmbedding
from supabase import create_client, Client

# Supabase config
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://isqvgddijyweardygoah.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")  # Need service key for updates

if not SUPABASE_KEY:
    print("ERROR: SUPABASE_SERVICE_KEY environment variable not set")
    exit(1)

# Initialize clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
model = TextEmbedding(
    model_name="sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
)

print(f"✓ Supabase connected: {SUPABASE_URL}")
print(f"✓ FastEmbed model loaded: paraphrase-multilingual-mpnet-base-v2 (768d)\n")


async def fetch_units_without_embeddings(limit: int = 1000) -> List[Dict]:
    """Fetch context units that don't have embeddings."""
    result = supabase.table("press_context_units")\
        .select("id, title, summary")\
        .is_("embedding", "null")\
        .limit(limit)\
        .execute()

    return result.data


async def generate_embedding(text: str) -> List[float]:
    """Generate 768d embedding for text."""
    loop = asyncio.get_event_loop()
    embeddings = await loop.run_in_executor(
        None,
        lambda: list(model.embed([text[:512]]))
    )
    return embeddings[0].tolist()


async def update_embedding(unit_id: str, embedding: List[float]):
    """Update context unit with embedding."""
    embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'

    supabase.table("press_context_units")\
        .update({"embedding": embedding_str})\
        .eq("id", unit_id)\
        .execute()


async def process_batch(units: List[Dict], batch_num: int, total_batches: int):
    """Process a batch of context units."""
    print(f"\n{'='*60}")
    print(f"Batch {batch_num}/{total_batches} ({len(units)} units)")
    print(f"{'='*60}")

    for i, unit in enumerate(units, 1):
        unit_id = unit['id']
        title = unit.get('title', '')
        summary = unit.get('summary', '')
        text = f"{title} | {summary}"

        print(f"[{i}/{len(units)}] {title[:50]}...")

        try:
            # Generate embedding
            embedding = await generate_embedding(text)

            # Update database
            await update_embedding(unit_id, embedding)

            print(f"  ✓ Updated (768d)")

        except Exception as e:
            print(f"  ✗ Failed: {e}")


async def main():
    print("Fetching context units without embeddings...")
    units = await fetch_units_without_embeddings()

    if not units:
        print("\n✓ All context units already have embeddings!")
        return

    print(f"\nFound {len(units)} context units without embeddings")

    # Process in batches of 20
    batch_size = 20
    total_batches = (len(units) + batch_size - 1) // batch_size

    for i in range(0, len(units), batch_size):
        batch = units[i:i+batch_size]
        batch_num = (i // batch_size) + 1
        await process_batch(batch, batch_num, total_batches)

    print(f"\n{'='*60}")
    print(f"✓ COMPLETED: Regenerated {len(units)} embeddings")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
