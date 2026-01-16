"""Shared helper functions for API endpoints."""

import re
import time
import hashlib
import markdown


def generate_slug_from_title(title: str) -> str:
    """Generate WordPress-compatible slug from title with short unique suffix."""
    # Convert to lowercase and replace common Spanish characters
    slug = title.lower()

    # Replace Spanish characters
    replacements = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ü': 'u',
        'ñ': 'n', 'ç': 'c'
    }

    for char, replacement in replacements.items():
        slug = slug.replace(char, replacement)

    # Remove special characters and replace spaces with hyphens
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = slug.strip('-')

    # Limit base slug length
    base_slug = slug[:200]

    # Generate 4-char alphanumeric hash from timestamp for uniqueness
    timestamp = str(time.time_ns())
    hash_suffix = hashlib.md5(timestamp.encode()).hexdigest()[:4]

    return f"{base_slug}-{hash_suffix}"


def strip_markdown(text: str) -> str:
    """Strip markdown formatting from text, returning plain text.

    Removes: **bold**, *italic*, `code`, [links](url), # headers, etc.
    Equivalent to frontend's marked.parse() + HTML stripping.
    """
    if not text:
        return ""

    # Remove bold (**text** or __text__)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)

    # Remove italic (*text* or _text_)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)

    # Remove inline code (`code`)
    text = re.sub(r'`(.+?)`', r'\1', text)

    # Remove links [text](url) -> text
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)

    # Remove headers (# Header)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # Remove strikethrough (~~text~~)
    text = re.sub(r'~~(.+?)~~', r'\1', text)

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def markdown_to_html(markdown_text: str) -> str:
    """Convert markdown to HTML.

    Uses Python markdown library (equivalent to frontend's marked.parse()).
    """
    if not markdown_text:
        return ""

    # Convert markdown to HTML with common extensions
    html = markdown.markdown(
        markdown_text,
        extensions=['extra', 'sane_lists', 'smarty']
    )

    return html


def extract_statements_from_context_units(context_units: list) -> list:
    """Extract all statements from context units for working_json.

    Returns list of statement objects with context_unit_id reference.
    """
    statements = []

    for cu in context_units:
        cu_id = cu.get("id")
        cu_title = cu.get("title", "")

        # Get atomic statements (may be None from DB)
        atomic_statements = cu.get("atomic_statements") or []

        for stmt in atomic_statements:
            if isinstance(stmt, dict):
                statements.append({
                    "context_unit_id": cu_id,
                    "context_unit_title": cu_title,
                    "text": stmt.get("text", ""),
                    "type": stmt.get("type", "fact"),
                    "order": stmt.get("order", 0),
                    "speaker": stmt.get("speaker")
                })
            elif isinstance(stmt, str) and stmt:
                # Legacy string format
                statements.append({
                    "context_unit_id": cu_id,
                    "context_unit_title": cu_title,
                    "text": stmt,
                    "type": "fact",
                    "order": 0,
                    "speaker": None
                })

        # Get enriched statements (may be None from DB)
        enriched_statements = cu.get("enriched_statements") or []

        for stmt in enriched_statements:
            if isinstance(stmt, dict):
                statements.append({
                    "context_unit_id": cu_id,
                    "context_unit_title": cu_title,
                    "text": stmt.get("text", ""),
                    "type": stmt.get("type", "enriched"),
                    "order": stmt.get("order", 9999),
                    "speaker": stmt.get("speaker")
                })
            elif isinstance(stmt, str) and stmt:
                statements.append({
                    "context_unit_id": cu_id,
                    "context_unit_title": cu_title,
                    "text": stmt,
                    "type": "enriched",
                    "order": 9999,
                    "speaker": None
                })

    # Sort by order
    statements.sort(key=lambda x: x.get("order", 0))

    return statements


def generate_placeholder_image() -> bytes:
    """Generate SVG placeholder image with 1.91:1 aspect ratio.

    Returns:
        SVG bytes for placeholder (600x314px, scales to any size)
    """
    svg = """<svg width="600" height="314" xmlns="http://www.w3.org/2000/svg">
  <rect width="600" height="314" fill="#f0f0f0"/>
  <text x="50%" y="50%" font-family="Arial, sans-serif" font-size="18"
        fill="#999" text-anchor="middle" dominant-baseline="middle">
    Sin imagen
  </text>
</svg>"""
    return svg.encode('utf-8')
