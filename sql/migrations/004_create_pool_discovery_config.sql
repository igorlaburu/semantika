-- Pool discovery configuration table
-- Allows SYSTEM company to configure geographic areas and queries for Pool discovery

CREATE TABLE IF NOT EXISTS pool_discovery_config (
    config_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Geographic focus
    geographic_area TEXT NOT NULL, -- e.g., "Álava", "Bizkaia", "Gipuzkoa", "Euskadi"
    search_query TEXT NOT NULL, -- e.g., "Álava noticias", "Vitoria-Gasteiz"
    
    -- GNews API parameters
    gnews_lang TEXT DEFAULT 'es',
    gnews_country TEXT DEFAULT 'es',
    max_articles INT DEFAULT 100,
    sample_rate FLOAT DEFAULT 0.05, -- 5% sampling
    
    -- Filtering
    excluded_domains TEXT[] DEFAULT '{}', -- Domains to skip (e.g., abc.es, elmundo.es)
    target_source_types TEXT[] DEFAULT ARRAY['press_room', 'institutional'], -- Only press rooms and institutions
    
    -- Status
    is_active BOOLEAN DEFAULT true,
    priority INT DEFAULT 1, -- Lower = higher priority
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES organizations(id), -- SYSTEM org
    notes TEXT
);

-- Index for active configs ordered by priority
CREATE INDEX idx_pool_discovery_config_active ON pool_discovery_config(is_active, priority);

-- Seed initial Álava config
INSERT INTO pool_discovery_config (
    geographic_area,
    search_query,
    target_source_types,
    is_active,
    priority,
    notes,
    created_by
)
SELECT
    'Álava',
    'Álava noticias Vitoria-Gasteiz',
    ARRAY['press_room', 'institutional'],
    true,
    1,
    'Initial config for Álava province - focuses on local government, companies, and institutions',
    id
FROM organizations
WHERE slug = 'system'
LIMIT 1;

COMMENT ON TABLE pool_discovery_config IS 'Configuration for Pool discovery jobs - defines geographic areas and search parameters';
COMMENT ON COLUMN pool_discovery_config.geographic_area IS 'Human-readable geographic area (e.g., Álava, Bizkaia)';
COMMENT ON COLUMN pool_discovery_config.search_query IS 'GNews search query for this area';
COMMENT ON COLUMN pool_discovery_config.sample_rate IS 'Percentage of articles to sample (0.05 = 5%)';
COMMENT ON COLUMN pool_discovery_config.excluded_domains IS 'Domains to exclude from discovery (media outlets)';
