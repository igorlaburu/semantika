"""Featured image extraction from HTML with cascading fallback.

Extraction priority:
1. Open Graph (og:image) - Most reliable, used by 90% of sites
2. Twitter Card (twitter:image) - Fallback for sites without OG
3. JSON-LD Schema.org - For technical/news sites
4. First article image - Last resort fallback

Returns standardized image metadata for source_metadata.featured_image
"""

from typing import Optional, Dict, Any
import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

from utils.logger import get_logger

logger = get_logger("image_extractor")


def extract_featured_image(
    soup: BeautifulSoup,
    page_url: str
) -> Optional[Dict[str, Any]]:
    """Extract featured image with cascading fallback.
    
    Args:
        soup: BeautifulSoup parsed HTML
        page_url: Page URL (for relative URL resolution)
        
    Returns:
        {
            "url": "https://...",
            "source": "og:image" | "twitter:image" | "jsonld" | "content",
            "width": 1200,  # Optional
            "height": 630,  # Optional
            "alt": "..."    # Optional
        }
        or None if no image found
    """
    # Priority 1: Open Graph
    og_image = extract_og_image(soup, page_url)
    if og_image:
        return og_image
    
    # Priority 2: Twitter Card
    twitter_image = extract_twitter_image(soup, page_url)
    if twitter_image:
        return twitter_image
    
    # Priority 3: JSON-LD Schema.org
    jsonld_image = extract_jsonld_image(soup, page_url)
    if jsonld_image:
        return jsonld_image
    
    # Priority 4: First article image
    content_image = extract_first_article_image(soup, page_url)
    if content_image:
        return content_image
    
    logger.debug("no_featured_image_found", url=page_url)
    return None


def extract_og_image(soup: BeautifulSoup, page_url: str) -> Optional[Dict[str, Any]]:
    """Extract Open Graph image metadata.
    
    Example HTML:
        <meta property="og:image" content="https://example.com/img.jpg" />
        <meta property="og:image:width" content="1200" />
        <meta property="og:image:height" content="630" />
        <meta property="og:image:alt" content="Description" />
    """
    og_image_tag = soup.find('meta', property='og:image')
    if not og_image_tag or not og_image_tag.get('content'):
        return None
    
    image_url = og_image_tag['content'].strip()
    
    # Resolve relative URLs
    image_url = urljoin(page_url, image_url)
    
    # Validate URL
    if not is_valid_image_url(image_url):
        logger.debug("og_image_invalid_url", url=image_url)
        return None
    
    # Extract optional metadata
    width = None
    height = None
    alt = None
    
    width_tag = soup.find('meta', property='og:image:width')
    if width_tag and width_tag.get('content'):
        try:
            width = int(width_tag['content'])
        except (ValueError, TypeError):
            pass
    
    height_tag = soup.find('meta', property='og:image:height')
    if height_tag and height_tag.get('content'):
        try:
            height = int(height_tag['content'])
        except (ValueError, TypeError):
            pass
    
    alt_tag = soup.find('meta', property='og:image:alt')
    if alt_tag and alt_tag.get('content'):
        alt = alt_tag['content'].strip()
    
    result = {
        "url": image_url,
        "source": "og:image"
    }
    
    if width:
        result["width"] = width
    if height:
        result["height"] = height
    if alt:
        result["alt"] = alt
    
    logger.debug("og_image_extracted", url=image_url, width=width, height=height)
    return result


def extract_twitter_image(soup: BeautifulSoup, page_url: str) -> Optional[Dict[str, Any]]:
    """Extract Twitter Card image metadata.
    
    Example HTML:
        <meta name="twitter:image" content="https://example.com/img.jpg" />
        <meta name="twitter:image:alt" content="Description" />
    """
    twitter_image_tag = soup.find('meta', attrs={'name': 'twitter:image'})
    if not twitter_image_tag or not twitter_image_tag.get('content'):
        return None
    
    image_url = twitter_image_tag['content'].strip()
    image_url = urljoin(page_url, image_url)
    
    if not is_valid_image_url(image_url):
        logger.debug("twitter_image_invalid_url", url=image_url)
        return None
    
    # Extract alt text
    alt = None
    alt_tag = soup.find('meta', attrs={'name': 'twitter:image:alt'})
    if alt_tag and alt_tag.get('content'):
        alt = alt_tag['content'].strip()
    
    result = {
        "url": image_url,
        "source": "twitter:image"
    }
    
    if alt:
        result["alt"] = alt
    
    logger.debug("twitter_image_extracted", url=image_url)
    return result


def extract_jsonld_image(soup: BeautifulSoup, page_url: str) -> Optional[Dict[str, Any]]:
    """Extract image from JSON-LD Schema.org markup.
    
    Example HTML:
        <script type="application/ld+json">
        {
          "@type": "NewsArticle",
          "image": {
            "@type": "ImageObject",
            "url": "https://example.com/img.jpg",
            "width": 1200,
            "height": 630
          }
        }
        </script>
    """
    jsonld_scripts = soup.find_all('script', type='application/ld+json')
    
    for script in jsonld_scripts:
        if not script.string:
            continue
        
        try:
            data = json.loads(script.string)
            
            # Handle array of objects
            if isinstance(data, list):
                for item in data:
                    image_data = extract_image_from_jsonld_object(item, page_url)
                    if image_data:
                        return image_data
            else:
                image_data = extract_image_from_jsonld_object(data, page_url)
                if image_data:
                    return image_data
                    
        except json.JSONDecodeError as e:
            logger.debug("jsonld_parse_error", error=str(e))
            continue
    
    return None


def extract_image_from_jsonld_object(obj: Dict, page_url: str) -> Optional[Dict[str, Any]]:
    """Extract image from a JSON-LD object."""
    if not isinstance(obj, dict):
        return None
    
    # Check for image field
    image = obj.get('image')
    if not image:
        return None
    
    # Handle different image formats
    image_url = None
    width = None
    height = None
    
    if isinstance(image, str):
        # Simple string URL
        image_url = image
    elif isinstance(image, dict):
        # ImageObject with metadata
        image_url = image.get('url') or image.get('@id')
        width = image.get('width')
        height = image.get('height')
    elif isinstance(image, list) and len(image) > 0:
        # Array of images - take first
        first = image[0]
        if isinstance(first, str):
            image_url = first
        elif isinstance(first, dict):
            image_url = first.get('url') or first.get('@id')
            width = first.get('width')
            height = first.get('height')
    
    if not image_url:
        return None
    
    image_url = urljoin(page_url, image_url)
    
    if not is_valid_image_url(image_url):
        return None
    
    result = {
        "url": image_url,
        "source": "jsonld"
    }
    
    if width:
        result["width"] = width
    if height:
        result["height"] = height
    
    logger.debug("jsonld_image_extracted", url=image_url)
    return result


def extract_first_article_image(soup: BeautifulSoup, page_url: str) -> Optional[Dict[str, Any]]:
    """Extract first significant image from article content.
    
    Looks for images in semantic HTML5 tags:
    - <article>
    - <main>
    - [role="main"]
    - <div class="content">
    
    Filters out:
    - Icons (< 100x100px)
    - Logos (in header/footer)
    - Tracking pixels
    - Images from different domains (cross-site images)
    """
    from urllib.parse import urlparse
    
    # Get domain from page URL for same-domain preference
    page_domain = urlparse(page_url).netloc.lower()
    
    # Find article/main content area
    content_areas = (
        soup.find_all('article') +
        soup.find_all('main') +
        soup.find_all(attrs={'role': 'main'}) +
        soup.find_all('div', class_=lambda c: c and 'content' in str(c).lower())
    )
    
    # If no semantic tags, search whole body
    if not content_areas:
        content_areas = [soup.find('body')] if soup.find('body') else [soup]
    
    # Collect all valid images with scoring
    candidate_images = []
    
    for area in content_areas:
        if not area:
            continue
        
        # Find all images in this area
        images = area.find_all('img', src=True)
        
        for img in images:
            src = img['src'].strip()

            # Skip data URIs
            if src.startswith('data:'):
                continue

            # If src is just a domain (Angular/lazy-load pattern), try srcset
            parsed_src = urlparse(src)
            if parsed_src.path in ('', '/') and img.get('srcset'):
                # Extract largest image from srcset (format: "url1 64w, url2 128w, ...")
                srcset = img.get('srcset', '')
                srcset_urls = []
                for part in srcset.split(','):
                    part = part.strip()
                    if ' ' in part:
                        url_part = part.rsplit(' ', 1)[0].strip()
                        srcset_urls.append(url_part)
                # Use largest (last) URL from srcset
                if srcset_urls:
                    src = srcset_urls[-1]
                    logger.debug("image_using_srcset", original_src=img['src'][:50], srcset_url=src[:100])
            
            # Skip common icon/logo patterns in URL
            if any(skip in src.lower() for skip in ['icon', 'logo', 'avatar', 'pixel', '1x1', 'back.png', 'escudo', 'badge', 'crest', 'shield']):
                continue

            # Skip common icon/logo patterns in alt text
            alt = img.get('alt', '').strip().lower()
            if any(skip in alt for skip in ['icono', 'icon', 'logo', 'avatar', 'ver más', 'ver mas', 'back', 'arrow', 'escudo', 'badge']):
                continue

            # Skip tiny images (likely icons) - require minimum 150px
            width = img.get('width')
            height = img.get('height')
            w, h = None, None
            if width and height:
                try:
                    w = int(width)
                    h = int(height)
                    # Skip small images
                    if w < 150 or h < 150:
                        continue
                    # Skip small square images (likely logos/avatars)
                    if w < 300 and h < 300 and 0.8 < (w/h) < 1.2:
                        logger.debug("skipping_small_square_image", url=src[:50], width=w, height=h)
                        continue
                except (ValueError, TypeError):
                    pass
            
            # Resolve URL
            image_url = urljoin(page_url, src)
            
            if not is_valid_image_url(image_url):
                continue
            
            # Check domain - prefer same domain images
            image_domain = urlparse(image_url).netloc.lower()
            is_same_domain = image_domain == page_domain
            
            # Calculate score for image selection priority
            score = 0

            # Same domain gets bonus (prevents cross-site images)
            if is_same_domain:
                score += 50
            else:
                # Log cross-domain images for debugging
                logger.debug("content_image_cross_domain",
                    page_domain=page_domain,
                    image_domain=image_domain,
                    image_url=image_url[:100]
                )
                # Still allow, but with lower score
                score += 5

            # Size bonus - HEAVILY favor larger images
            if w and h:
                # Area-based scoring (larger images = much higher score)
                area = w * h
                if area >= 400000:  # 800x500 or larger
                    score += 200
                elif area >= 200000:  # 500x400 or larger
                    score += 150
                elif area >= 100000:  # 400x250 or larger
                    score += 100
                elif area >= 50000:  # 250x200 or larger
                    score += 50
                else:
                    score += 10

                # Horizontal aspect ratio bonus (typical article images: 16:9, 1.91:1)
                aspect = w / h if h > 0 else 1
                if 1.3 < aspect < 2.5:  # Horizontal rectangle
                    score += 30
                elif 0.8 < aspect < 1.2:  # Square-ish (less preferred)
                    score -= 20

            # Alt text bonus (indicates meaningful image)
            if alt and len(alt) > 10:
                score += 15
            
            candidate_images.append({
                "url": image_url,
                "source": "content",
                "score": score,
                "width": w,
                "height": h,
                "alt": alt,
                "domain": image_domain,
                "same_domain": is_same_domain
            })
    
    # If no candidates found
    if not candidate_images:
        return None
    
    # Sort by score (highest first)
    candidate_images.sort(key=lambda x: x["score"], reverse=True)
    
    # Take best candidate
    best = candidate_images[0]
    
    # Log selection details for debugging
    logger.debug("content_image_selected",
        url=best["url"][:100],
        score=best["score"],
        same_domain=best["same_domain"],
        total_candidates=len(candidate_images)
    )
    
    # If the best image is cross-domain, log warning
    if not best["same_domain"]:
        logger.warn("content_image_cross_domain_selected",
            page_domain=page_domain,
            image_domain=best["domain"],
            image_url=best["url"][:100],
            score=best["score"]
        )
    
    # Build result
    result = {
        "url": best["url"],
        "source": "content"
    }
    
    if best["alt"]:
        result["alt"] = best["alt"]
    if best["width"]:
        result["width"] = best["width"]
    if best["height"]:
        result["height"] = best["height"]
    
    return result


def is_valid_image_url(url: str) -> bool:
    """Validate image URL.
    
    Rejects:
    - data: URIs
    - javascript: URIs
    - Non-http(s) schemes
    - Empty/invalid URLs
    """
    if not url or not url.strip():
        return False
    
    url = url.strip()
    
    # Reject data URIs
    if url.startswith('data:'):
        return False
    
    # Reject javascript
    if url.startswith('javascript:'):
        return False
    
    # Parse URL
    try:
        parsed = urlparse(url)
        
        # Must have http or https scheme
        if parsed.scheme not in ('http', 'https'):
            return False
        
        # Must have domain
        if not parsed.netloc:
            return False
        
        return True
        
    except Exception:
        return False
