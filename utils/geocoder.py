"""Geocoding service - Convert location names to GPS coordinates.

Architecture:
- Tier 1: Static DB (instant, 99% hits for common locations)
- Tier 2: Cache DB (fast, perpetual storage)
- Tier 3: Nominatim API (fallback, rate limited)

Usage:
    locations_from_llm = [
        {"name": "Vitoria-Gasteiz", "type": "city", "level": "primary"},
        {"name": "Álava", "type": "province", "level": "context"},
        {"name": "España", "type": "country", "level": "context"}
    ]
    
    result = await geocode_with_context(locations_from_llm)
    # {"lat": 42.850, "lon": -2.672, "name": "Vitoria-Gasteiz", "country": "ES"}
"""

import asyncio
import aiohttp
from typing import Optional, Dict, List
from datetime import datetime

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client

logger = get_logger("geocoder")

# Static database of common locations (Tier 1: instant lookup)
# Covers ~99% of cases for Spanish institutional content
STATIC_LOCATIONS = {
    # País Vasco - Cities
    "vitoria-gasteiz": {"lat": 42.850, "lon": -2.672, "country": "ES", "province": "Álava"},
    "gasteiz": {"lat": 42.850, "lon": -2.672, "country": "ES", "province": "Álava"},
    "vitoria": {"lat": 42.850, "lon": -2.672, "country": "ES", "province": "Álava"},
    "bilbao": {"lat": 43.263, "lon": -2.935, "country": "ES", "province": "Bizkaia"},
    "bilbo": {"lat": 43.263, "lon": -2.935, "country": "ES", "province": "Bizkaia"},
    "donostia": {"lat": 43.318, "lon": -1.981, "country": "ES", "province": "Gipuzkoa"},
    "donostia-san sebastián": {"lat": 43.318, "lon": -1.981, "country": "ES", "province": "Gipuzkoa"},
    "san sebastián": {"lat": 43.318, "lon": -1.981, "country": "ES", "province": "Gipuzkoa"},
    
    # País Vasco - Provinces
    "álava": {"lat": 42.850, "lon": -2.672, "country": "ES", "type": "province"},
    "araba": {"lat": 42.850, "lon": -2.672, "country": "ES", "type": "province"},
    "bizkaia": {"lat": 43.263, "lon": -2.935, "country": "ES", "type": "province"},
    "vizcaya": {"lat": 43.263, "lon": -2.935, "country": "ES", "type": "province"},
    "gipuzkoa": {"lat": 43.194, "lon": -2.011, "country": "ES", "type": "province"},
    "guipúzcoa": {"lat": 43.194, "lon": -2.011, "country": "ES", "type": "province"},
    
    # País Vasco - Region
    "país vasco": {"lat": 43.000, "lon": -2.500, "country": "ES", "type": "region"},
    "euskadi": {"lat": 43.000, "lon": -2.500, "country": "ES", "type": "region"},
    "euskal herria": {"lat": 43.000, "lon": -2.500, "country": "ES", "type": "region"},
    
    # Other major Spanish cities
    "madrid": {"lat": 40.416, "lon": -3.703, "country": "ES"},
    "barcelona": {"lat": 41.385, "lon": 2.173, "country": "ES"},
    "valencia": {"lat": 39.469, "lon": -0.376, "country": "ES"},
    "sevilla": {"lat": 37.389, "lon": -5.984, "country": "ES"},
    "zaragoza": {"lat": 41.656, "lon": -0.877, "country": "ES"},
    "málaga": {"lat": 36.721, "lon": -4.421, "country": "ES"},
    "murcia": {"lat": 37.992, "lon": -1.130, "country": "ES"},
    "palma": {"lat": 39.569, "lon": 2.650, "country": "ES"},
    "las palmas": {"lat": 28.124, "lon": -15.428, "country": "ES"},
    "alicante": {"lat": 38.345, "lon": -0.481, "country": "ES"},
    
    # Spain as country
    "españa": {"lat": 40.463, "lon": -3.749, "country": "ES", "type": "country"},
    "spain": {"lat": 40.463, "lon": -3.749, "country": "ES", "type": "country"},
}

# In-memory cache (loaded from DB on startup)
GEOCODING_CACHE: Dict[str, Dict] = {}

# Country code mapping
COUNTRY_CODES = {
    "españa": "es",
    "spain": "es",
    "francia": "fr",
    "france": "fr",
    "portugal": "pt",
    "alemania": "de",
    "germany": "de",
    "italia": "it",
    "italy": "it",
    "reino unido": "gb",
    "united kingdom": "gb",
    "canadá": "ca",
    "canada": "ca",
    "estados unidos": "us",
    "united states": "us",
    "méxico": "mx",
    "mexico": "mx",
    "brasil": "br",
    "brazil": "br",
}


async def load_cache_from_db():
    """Load geocoding cache from DB into memory on startup."""
    global GEOCODING_CACHE
    
    try:
        supabase = get_supabase_client()
        result = supabase.client.table("geocoding_cache")\
            .select("location_query, lat, lon, display_name, country_code")\
            .execute()
        
        for row in result.data:
            GEOCODING_CACHE[row["location_query"]] = {
                "lat": row["lat"],
                "lon": row["lon"],
                "display_name": row["display_name"],
                "country": row["country_code"]
            }
        
        logger.info("geocoding_cache_loaded", size=len(GEOCODING_CACHE))
    
    except Exception as e:
        logger.warn("geocoding_cache_load_failed", error=str(e))
        # Continue without cache (will use static DB + API)


def infer_country_code(country_name: str) -> Optional[str]:
    """Map country name to ISO 3166-1 alpha-2 code."""
    if not country_name:
        return None
    return COUNTRY_CODES.get(country_name.lower().strip())


async def get_from_cache(location_query: str) -> Optional[Dict]:
    """Get geocoded location from cache (memory or DB).
    
    Args:
        location_query: Normalized location query string
        
    Returns:
        {"lat": 42.850, "lon": -2.672, "display_name": "...", "country": "ES"}
    """
    normalized_query = location_query.lower().strip()
    
    # Try memory cache first (instant)
    if normalized_query in GEOCODING_CACHE:
        logger.debug("geocode_cache_hit_memory", location=location_query)
        return GEOCODING_CACHE[normalized_query]
    
    # Try DB cache (10-50ms)
    try:
        supabase = get_supabase_client()
        result = supabase.client.table("geocoding_cache")\
            .select("*")\
            .eq("location_query", normalized_query)\
            .execute()
        
        if result.data:
            # Increment hit counter
            cache_id = result.data[0]["id"]
            supabase.client.table("geocoding_cache")\
                .update({"hits": result.data[0]["hits"] + 1})\
                .eq("id", cache_id)\
                .execute()
            
            cached_data = {
                "lat": result.data[0]["lat"],
                "lon": result.data[0]["lon"],
                "display_name": result.data[0]["display_name"],
                "country": result.data[0]["country_code"]
            }
            
            # Add to memory cache
            GEOCODING_CACHE[normalized_query] = cached_data
            
            logger.debug("geocode_cache_hit_db", 
                location=location_query,
                hits=result.data[0]["hits"] + 1
            )
            
            return cached_data
    
    except Exception as e:
        logger.warn("geocode_cache_read_error", error=str(e))
    
    return None


async def save_to_cache(location_query: str, geocoded: Dict):
    """Save geocoded location to cache (DB).
    
    Args:
        location_query: Original location query
        geocoded: Geocoded result with lat, lon, display_name, country
    """
    try:
        supabase = get_supabase_client()
        
        # Extract normalized name (first part before comma)
        normalized = location_query.split(",")[0].strip().lower()
        
        data = {
            "location_query": location_query.lower().strip(),
            "location_normalized": normalized,
            "lat": geocoded["lat"],
            "lon": geocoded["lon"],
            "display_name": geocoded.get("display_name", location_query),
            "country_code": geocoded.get("country", ""),
            "hits": 0
        }
        
        # Upsert (insert or ignore if exists)
        supabase.client.table("geocoding_cache")\
            .upsert(data, on_conflict="location_query")\
            .execute()
        
        # Add to memory cache
        GEOCODING_CACHE[data["location_query"]] = {
            "lat": geocoded["lat"],
            "lon": geocoded["lon"],
            "display_name": geocoded.get("display_name"),
            "country": geocoded.get("country")
        }
        
        logger.info("geocode_cached", location=location_query)
    
    except Exception as e:
        logger.error("geocode_cache_save_error", 
            location=location_query,
            error=str(e)
        )


async def query_nominatim(location: str, country_hint: Optional[str] = None) -> Optional[Dict]:
    """Query Nominatim API for geocoding.
    
    Rate limit: 1 request/second (enforced by sleep)
    
    Args:
        location: Location name or query
        country_hint: Optional ISO country code for bias (e.g., "es")
        
    Returns:
        {"lat": 42.850, "lon": -2.672, "display_name": "...", "country": "ES"}
    """
    try:
        # Enforce rate limit: 1.1 sec between requests
        await asyncio.sleep(1.1)
        
        params = {
            "q": location,
            "format": "json",
            "limit": 1,
            "addressdetails": 1
        }
        
        if country_hint:
            params["countrycodes"] = country_hint.lower()
        
        headers = {
            "User-Agent": "Semantika/1.0 (info@ekimen.ai)"  # Required by Nominatim
        }
        
        async with aiohttp.ClientSession() as session:
            url = "https://nominatim.openstreetmap.org/search"
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    logger.error("nominatim_error", 
                        status=resp.status,
                        location=location
                    )
                    return None
                
                data = await resp.json()
                
                if data:
                    result = {
                        "lat": float(data[0]["lat"]),
                        "lon": float(data[0]["lon"]),
                        "display_name": data[0].get("display_name", location),
                        "country": data[0].get("address", {}).get("country_code", "").upper()
                    }
                    
                    logger.info("nominatim_success", 
                        location=location,
                        result_name=result["display_name"][:80]
                    )
                    
                    return result
                else:
                    logger.warn("nominatim_no_results", location=location)
                    return None
    
    except Exception as e:
        logger.error("nominatim_error", 
            location=location,
            error=str(e),
            error_type=type(e).__name__
        )
        return None


async def geocode_location(
    location: str, 
    country_hint: Optional[str] = None
) -> Optional[Dict]:
    """Geocode location using 3-tier strategy.
    
    Tier 1: Static DB (instant, 0ms, ~99% hits)
    Tier 2: Cache DB/memory (fast, 10ms, perpetual)
    Tier 3: Nominatim API (slow, 200-500ms, rate limited)
    
    Args:
        location: Location name ("Bilbao", "Vitoria-Gasteiz")
        country_hint: Optional ISO country code for bias
        
    Returns:
        {"lat": 43.263, "lon": -2.935, "name": "Bilbao", "country": "ES"}
    """
    if not location:
        return None
    
    normalized = location.lower().strip()
    
    # TIER 1: Static DB (instant, 0ms)
    if normalized in STATIC_LOCATIONS:
        result = STATIC_LOCATIONS[normalized].copy()
        result["name"] = location  # Preserve original case
        logger.debug("geocode_static", location=location)
        return result
    
    # TIER 2: Cache (memory or DB, 0-10ms)
    cached = await get_from_cache(location)
    if cached:
        cached["name"] = location
        return cached
    
    # TIER 3: Nominatim API (slow, 200-500ms + rate limit)
    logger.info("geocode_api_call", location=location, country_hint=country_hint)
    
    result = await query_nominatim(location, country_hint)
    
    if result:
        result["name"] = location
        # Save to cache for future use
        await save_to_cache(location, result)
        return result
    
    logger.warn("geocode_failed", location=location)
    return None


async def geocode_with_context(locations: List[Dict]) -> Optional[Dict]:
    """Geocode primary location with geographic context from LLM.
    
    Uses hierarchical location data to avoid ambiguity:
    - "Vitoria" alone → Could be Brazil or Spain
    - "Vitoria-Gasteiz, Álava, España" → Unambiguous
    
    Args:
        locations: List from LLM analyze_atomic:
            [
                {"name": "Vitoria-Gasteiz", "type": "city", "level": "primary"},
                {"name": "Álava", "type": "province", "level": "context"},
                {"name": "España", "type": "country", "level": "context"}
            ]
    
    Returns:
        {
            "lat": 42.850, 
            "lon": -2.672, 
            "name": "Vitoria-Gasteiz",
            "country": "ES",
            "province": "Álava",
            "full_context": "Vitoria-Gasteiz, Álava, España"
        }
    """
    if not locations:
        return None
    
    # Get primary location (main place where event occurs)
    primary = next((loc for loc in locations if loc.get("level") == "primary"), None)
    if not primary:
        logger.debug("geocode_no_primary_location")
        return None
    
    # Get country context for bias
    country_context = next(
        (loc for loc in locations if loc.get("type") == "country"), 
        None
    )
    
    # Build query with geographic hierarchy for disambiguation
    query_parts = [primary["name"]]
    
    # Add province/region for disambiguation
    province = next(
        (loc for loc in locations if loc.get("type") in ["province", "region"]), 
        None
    )
    if province:
        query_parts.append(province["name"])
    
    # Add country
    if country_context:
        query_parts.append(country_context["name"])
    
    # Build full query: "Vitoria-Gasteiz, Álava, España"
    full_query = ", ".join(query_parts)
    
    # Infer country code for Nominatim bias
    country_code = None
    if country_context:
        country_code = infer_country_code(country_context["name"])
    
    logger.debug("geocode_with_context_query", 
        primary=primary["name"],
        full_query=full_query,
        country_code=country_code
    )
    
    # Geocode with context
    result = await geocode_location(
        location=full_query,
        country_hint=country_code
    )
    
    if result:
        # Add context metadata
        result["primary_name"] = primary["name"]
        result["full_context"] = full_query
        if province:
            result["province"] = province["name"]
        
        logger.info("geocode_with_context_success",
            primary=primary["name"],
            lat=result["lat"],
            lon=result["lon"],
            country=result.get("country")
        )
    
    return result
