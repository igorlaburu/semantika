"""Content hashing utilities for change detection.

Implements multi-tier hash strategy:
- Tier 1: SHA256 (exact match)
- Tier 2: SimHash (fuzzy match)
- Tier 3: Embeddings (semantic match - see embedding_generator.py)
"""

import hashlib
import re
from typing import Optional, Tuple
from bs4 import BeautifulSoup

from .logger import get_logger

logger = get_logger("content_hasher")


def normalize_html(html: str) -> str:
    """Extract semantic content from HTML, removing noise.
    
    Removes:
    - Scripts, styles, ads
    - Navigation, headers, footers
    - Comments, metadata
    
    Args:
        html: Raw HTML content
        
    Returns:
        Normalized plain text content
    """
    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove script, style, navigation, ads
        for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe']):
            tag.decompose()
        
        # Remove elements with ad-related classes/ids
        ad_patterns = ['ad', 'advertisement', 'sponsor', 'promo', 'banner', 'popup']
        for pattern in ad_patterns:
            for element in soup.find_all(class_=re.compile(pattern, re.I)):
                element.decompose()
            for element in soup.find_all(id=re.compile(pattern, re.I)):
                element.decompose()
        
        # Extract text
        text = soup.get_text(separator=' ', strip=True)
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        logger.debug("html_normalized", 
            original_length=len(html),
            normalized_length=len(text)
        )
        
        return text
        
    except Exception as e:
        logger.error("html_normalization_error", error=str(e))
        # Fallback: simple tag removal
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()
        return text


def normalize_text(text: str) -> str:
    """Normalize plain text for consistent hashing.
    
    - Lowercase
    - Remove extra whitespace
    - Remove punctuation (optional - preserves sentence structure)
    
    Args:
        text: Raw text
        
    Returns:
        Normalized text
    """
    # Lowercase
    text = text.lower()
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    
    return text


def compute_sha256(text: str) -> str:
    """Compute SHA256 hash of text (Tier 1 - exact match).
    
    Args:
        text: Text to hash
        
    Returns:
        SHA256 hex digest
    """
    normalized = normalize_text(text)
    hash_object = hashlib.sha256(normalized.encode('utf-8'))
    hash_hex = hash_object.hexdigest()
    
    logger.debug("sha256_computed", 
        text_length=len(text),
        hash=hash_hex[:16] + "..."
    )
    
    return hash_hex


def compute_simhash(text: str, hash_bits: int = 64) -> int:
    """Compute SimHash for fuzzy matching (Tier 2).
    
    SimHash properties:
    - Similar documents have similar hashes (Hamming distance)
    - Small changes = small hash differences
    - Fast comparison
    
    Args:
        text: Text to hash
        hash_bits: Number of bits (default 64)
        
    Returns:
        SimHash as integer
    """
    try:
        from simhash import Simhash
        
        normalized = normalize_text(text)
        
        # Generate SimHash
        simhash_obj = Simhash(normalized)
        simhash_value = simhash_obj.value
        
        logger.debug("simhash_computed",
            text_length=len(text),
            simhash=simhash_value
        )
        
        return simhash_value
        
    except ImportError:
        logger.warn("simhash_library_not_installed_using_fallback")
        # Fallback: use SHA256 truncated to 64 bits
        sha = compute_sha256(text)
        return int(sha[:16], 16)  # First 64 bits
    except Exception as e:
        logger.error("simhash_computation_error", error=str(e))
        return 0


def simhash_distance(hash1: int, hash2: int) -> int:
    """Calculate Hamming distance between two SimHashes.
    
    Args:
        hash1: First SimHash
        hash2: Second SimHash
        
    Returns:
        Hamming distance (number of differing bits)
    """
    # XOR to find differing bits
    xor = hash1 ^ hash2
    
    # Count set bits (Brian Kernighan's algorithm)
    distance = 0
    while xor:
        distance += 1
        xor &= xor - 1
    
    return distance


def simhash_similarity(hash1: int, hash2: int, hash_bits: int = 64) -> float:
    """Calculate similarity score between two SimHashes.
    
    Args:
        hash1: First SimHash
        hash2: Second SimHash
        hash_bits: Number of bits (default 64)
        
    Returns:
        Similarity score (0.0 to 1.0)
    """
    distance = simhash_distance(hash1, hash2)
    similarity = 1.0 - (distance / hash_bits)
    return max(0.0, min(1.0, similarity))


def compute_content_hashes(
    html: Optional[str] = None,
    text: Optional[str] = None
) -> Tuple[str, int]:
    """Compute both SHA256 and SimHash for content.
    
    Args:
        html: Raw HTML content (preferred)
        text: Plain text content (if HTML not available)
        
    Returns:
        Tuple of (sha256_hash, simhash)
    """
    if html:
        # Extract semantic content from HTML
        semantic_content = normalize_html(html)
    elif text:
        # Use plain text directly
        semantic_content = text
    else:
        logger.warn("no_content_provided_for_hashing")
        return ("", 0)
    
    # Compute both hashes
    sha256_hash = compute_sha256(semantic_content)
    simhash = compute_simhash(semantic_content)
    
    logger.info("content_hashes_computed",
        content_length=len(semantic_content),
        sha256_prefix=sha256_hash[:16],
        simhash=simhash
    )
    
    return (sha256_hash, simhash)


def detect_change_tier(
    old_hash: Optional[str],
    new_hash: str,
    old_simhash: Optional[int],
    new_simhash: int,
    simhash_threshold: float = 0.95
) -> Tuple[str, int, Optional[float]]:
    """Detect type of change using multi-tier hashing.
    
    Tiers:
    1. SHA256 exact match → 'identical'
    2. SimHash fuzzy match → 'trivial' or 'minor_update'
    3. Neither match → 'major_update' (requires embedding check)
    
    Args:
        old_hash: Previous SHA256 hash (None if new URL)
        new_hash: New SHA256 hash
        old_simhash: Previous SimHash (None if new URL)
        new_simhash: New SimHash
        simhash_threshold: Similarity threshold for trivial changes
        
    Returns:
        Tuple of (change_type, detection_tier, similarity_score)
    """
    # New content (first time seeing this URL)
    if old_hash is None or old_simhash is None:
        logger.info("change_detected", 
            change_type="new",
            detection_tier=1
        )
        return ("new", 1, None)
    
    # Tier 1: Exact match (SHA256)
    if old_hash == new_hash:
        logger.debug("change_detected",
            change_type="identical",
            detection_tier=1
        )
        return ("identical", 1, 1.0)
    
    # Tier 2: Fuzzy match (SimHash)
    similarity = simhash_similarity(old_simhash, new_simhash)
    
    if similarity >= simhash_threshold:
        # Very similar (e.g., timestamp changed, ad rotated)
        logger.info("change_detected",
            change_type="trivial",
            detection_tier=2,
            similarity=round(similarity, 4)
        )
        return ("trivial", 2, similarity)
    
    elif similarity >= 0.80:
        # Moderately similar (minor content update)
        logger.info("change_detected",
            change_type="minor_update",
            detection_tier=2,
            similarity=round(similarity, 4)
        )
        return ("minor_update", 2, similarity)
    
    else:
        # Low similarity - major change
        # Requires Tier 3 (embedding) check to confirm
        logger.info("change_detected",
            change_type="major_update",
            detection_tier=3,
            similarity=round(similarity, 4)
        )
        return ("major_update", 3, similarity)


# Convenience function for complete hash comparison

def compare_content(
    old_content: Optional[dict],
    new_html: Optional[str] = None,
    new_text: Optional[str] = None,
    simhash_threshold: float = 0.95
) -> dict:
    """Compare old and new content using multi-tier hashing.
    
    Args:
        old_content: Dict with 'content_hash' and 'simhash' (None if new)
        new_html: New HTML content
        new_text: New plain text content
        simhash_threshold: Similarity threshold
        
    Returns:
        Dict with:
        - change_type: new/identical/trivial/minor_update/major_update
        - detection_tier: 1/2/3
        - similarity_score: float or None
        - new_hash: SHA256 hash
        - new_simhash: SimHash value
    """
    # Compute new hashes
    new_hash, new_simhash = compute_content_hashes(html=new_html, text=new_text)
    
    # Get old hashes
    old_hash = old_content.get("content_hash") if old_content else None
    old_simhash = old_content.get("simhash") if old_content else None
    
    # Detect change
    change_type, detection_tier, similarity = detect_change_tier(
        old_hash=old_hash,
        new_hash=new_hash,
        old_simhash=old_simhash,
        new_simhash=new_simhash,
        simhash_threshold=simhash_threshold
    )
    
    return {
        "change_type": change_type,
        "detection_tier": detection_tier,
        "similarity_score": similarity,
        "new_hash": new_hash,
        "new_simhash": new_simhash
    }
