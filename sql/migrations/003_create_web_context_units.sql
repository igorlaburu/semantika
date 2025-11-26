-- Migration 003: Create web_context_units table
-- Purpose: Store web monitoring context units (subvenciones, formularios, etc.)
-- Similar to press_context_units but for web content monitoring
-- Date: 2025-11-26

-- ================================================================
-- TABLE: web_context_units
-- ================================================================
-- Context units from web monitoring (similar structure to press_context_units)
-- Used for: DFA subsidies, government forms, regulatory updates, etc.

CREATE TABLE IF NOT EXISTS web_context_units (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Multi-tenant isolation
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    
    -- Source tracking
    source_type TEXT NOT NULL CHECK (source_type IN ('dfa_subsidies', 'web_monitoring', 'custom_scraper', 'government_forms')),
    source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    
    -- Content fields
    title TEXT,
    summary TEXT,
    raw_text TEXT NOT NULL,
    
    -- LLM-generated metadata
    tags TEXT[],
    category TEXT,
    atomic_statements JSONB,
    
    -- Source metadata
    source_metadata JSONB DEFAULT '{}',
    
    -- Embeddings for semantic search (768d multilingual - FastEmbed)
    embedding vector(768),
    
    -- Change tracking
    content_hash TEXT,  -- SHA256 for exact match
    simhash BIGINT,     -- SimHash for fuzzy matching
    
    -- Versioning (for updates/replacements)
    version INT DEFAULT 1,
    replaced_by_id UUID REFERENCES web_context_units(id) ON DELETE SET NULL,
    is_latest BOOLEAN DEFAULT TRUE,
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraint: Only one latest version per source
    UNIQUE(source_id, is_latest) WHERE is_latest = TRUE
);

-- ================================================================
-- INDEXES
-- ================================================================

-- Multi-tenant isolation (critical for RLS)
CREATE INDEX IF NOT EXISTS idx_web_context_units_company 
ON web_context_units(company_id);

-- Source tracking
CREATE INDEX IF NOT EXISTS idx_web_context_units_source 
ON web_context_units(source_id);

CREATE INDEX IF NOT EXISTS idx_web_context_units_source_type 
ON web_context_units(source_type);

-- Timestamps (for sorting/filtering)
CREATE INDEX IF NOT EXISTS idx_web_context_units_created 
ON web_context_units(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_web_context_units_updated 
ON web_context_units(updated_at DESC);

-- Tags (GIN index for array search)
CREATE INDEX IF NOT EXISTS idx_web_context_units_tags 
ON web_context_units USING GIN(tags);

-- Category filtering
CREATE INDEX IF NOT EXISTS idx_web_context_units_category 
ON web_context_units(category) WHERE category IS NOT NULL;

-- Change detection
CREATE INDEX IF NOT EXISTS idx_web_context_units_hash 
ON web_context_units(content_hash);

CREATE INDEX IF NOT EXISTS idx_web_context_units_simhash 
ON web_context_units(simhash);

-- Latest version lookup
CREATE INDEX IF NOT EXISTS idx_web_context_units_latest 
ON web_context_units(source_id, is_latest) WHERE is_latest = TRUE;

-- Versioning chain
CREATE INDEX IF NOT EXISTS idx_web_context_units_replaced 
ON web_context_units(replaced_by_id) WHERE replaced_by_id IS NOT NULL;

-- Vector similarity search (768d FastEmbed multilingual)
CREATE INDEX IF NOT EXISTS idx_web_context_units_embedding 
ON web_context_units 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- ================================================================
-- ROW LEVEL SECURITY (RLS)
-- ================================================================

-- Enable RLS for multi-tenant isolation
ALTER TABLE web_context_units ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see their own company's context units
CREATE POLICY web_context_units_company_isolation 
ON web_context_units
FOR ALL
USING (company_id = current_setting('app.current_company_id', TRUE)::UUID);

-- ================================================================
-- TRIGGERS
-- ================================================================

-- Auto-update updated_at timestamp
CREATE TRIGGER update_web_context_units_updated_at 
BEFORE UPDATE ON web_context_units
FOR EACH ROW 
EXECUTE FUNCTION update_updated_at_column();

-- ================================================================
-- FUNCTIONS
-- ================================================================

-- Function to search similar web_context_units by embedding
CREATE OR REPLACE FUNCTION match_web_context_units(
    query_embedding vector(768),
    company_id_filter UUID,
    match_threshold FLOAT DEFAULT 0.95,
    match_count INT DEFAULT 5
)
RETURNS TABLE (
    id UUID,
    title TEXT,
    summary TEXT,
    similarity FLOAT,
    source_type TEXT,
    created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        wcu.id,
        wcu.title,
        wcu.summary,
        1 - (wcu.embedding <=> query_embedding) AS similarity,
        wcu.source_type,
        wcu.created_at
    FROM web_context_units wcu
    WHERE wcu.company_id = company_id_filter
        AND wcu.embedding IS NOT NULL
        AND wcu.is_latest = TRUE
        AND 1 - (wcu.embedding <=> query_embedding) >= match_threshold
    ORDER BY wcu.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- ================================================================
-- COMMENTS
-- ================================================================

COMMENT ON TABLE web_context_units IS 'Context units from web monitoring (subvenciones, forms, regulations, etc.)';
COMMENT ON COLUMN web_context_units.source_type IS 'Type of web source: dfa_subsidies, web_monitoring, custom_scraper, government_forms';
COMMENT ON COLUMN web_context_units.embedding IS 'FastEmbed multilingual embedding (768 dim) for semantic search and deduplication';
COMMENT ON COLUMN web_context_units.content_hash IS 'SHA256 hash for exact duplicate detection (Tier 1)';
COMMENT ON COLUMN web_context_units.simhash IS 'SimHash for fuzzy duplicate detection (Tier 2)';
COMMENT ON COLUMN web_context_units.version IS 'Version number (increments on updates)';
COMMENT ON COLUMN web_context_units.replaced_by_id IS 'Points to newer version if this was replaced';
COMMENT ON COLUMN web_context_units.is_latest IS 'TRUE only for the current version';
COMMENT ON COLUMN web_context_units.source_metadata IS 'JSON metadata: URL, extraction config, change detection info, etc.';

-- ================================================================
-- VERIFICATION
-- ================================================================

-- Verify table was created
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_name = 'web_context_units'
    ) THEN
        RAISE NOTICE 'Table web_context_units created successfully';
    ELSE
        RAISE EXCEPTION 'Failed to create web_context_units table';
    END IF;
END $$;

-- Show table info
SELECT 
    'web_context_units' as table_name,
    COUNT(*) as row_count,
    pg_size_pretty(pg_total_relation_size('web_context_units')) as total_size
FROM web_context_units;
