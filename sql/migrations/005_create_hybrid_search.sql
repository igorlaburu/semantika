-- Hybrid search: Semantic (pgvector) + Keyword (full-text) with union
--
-- PURPOSE:
-- Combines semantic vector search with PostgreSQL full-text search (FTS)
-- to provide better coverage and relevance for Spanish/Basque content.
--
-- STRATEGY:
-- 1. Semantic search: pgvector cosine similarity (good for concept matching)
-- 2. Keyword search: PostgreSQL ts_vector (good for exact term matching)
-- 3. Union both results and re-rank by combined score
--
-- SCORING:
-- - semantic_score: 1 - cosine_distance (0.0-1.0)
-- - keyword_score: ts_rank normalized (0.0-1.0)
-- - combined_score: 0.7 * semantic + 0.3 * keyword (semantic preferred)

CREATE OR REPLACE FUNCTION public.hybrid_search_context_units(
    p_company_id uuid,
    p_query_text text,
    p_query_embedding vector(768),
    p_semantic_threshold double precision DEFAULT 0.35,
    p_limit integer DEFAULT 20,
    p_max_days integer DEFAULT NULL,
    p_category text DEFAULT NULL,
    p_source_type text DEFAULT NULL,
    p_include_pool boolean DEFAULT false
)
RETURNS TABLE(
    id uuid,
    company_id uuid,
    title text,
    summary text,
    category varchar(50),
    tags text[],
    source_type varchar(50),
    created_at timestamp without time zone,
    semantic_score double precision,
    keyword_score double precision,
    combined_score double precision
) AS $$
DECLARE
    pool_uuid uuid := '99999999-9999-9999-9999-999999999999'::uuid;
BEGIN
    RETURN QUERY
    WITH semantic_results AS (
        -- Búsqueda semántica (pgvector)
        SELECT 
            pcu.id,
            pcu.company_id,
            pcu.title,
            pcu.summary,
            pcu.category,
            pcu.tags,
            pcu.source_type,
            pcu.created_at,
            (1 - (pcu.embedding <=> p_query_embedding))::double precision AS semantic_score,
            0.0::double precision AS keyword_score
        FROM press_context_units pcu
        WHERE
            -- Company filter: own company OR pool (if include_pool = true)
            (pcu.company_id = p_company_id OR (p_include_pool = true AND pcu.company_id = pool_uuid))
            -- Time filter
            AND (p_max_days IS NULL OR pcu.created_at > NOW() - (p_max_days || ' days')::interval)
            -- Category filter
            AND (p_category IS NULL OR pcu.category = p_category)
            -- Source type filter
            AND (p_source_type IS NULL OR pcu.source_type = p_source_type)
            -- Semantic similarity threshold
            AND (1 - (pcu.embedding <=> p_query_embedding)) >= p_semantic_threshold
            -- Ensure embedding exists
            AND pcu.embedding IS NOT NULL
        ORDER BY pcu.embedding <=> p_query_embedding
        LIMIT p_limit * 3  -- Get more candidates for union
    ),
    keyword_results AS (
        -- Búsqueda keyword (full-text search)
        -- Uses Spanish text search configuration for better stemming
        SELECT 
            pcu.id,
            pcu.company_id,
            pcu.title,
            pcu.summary,
            pcu.category,
            pcu.tags,
            pcu.source_type,
            pcu.created_at,
            0.0::double precision AS semantic_score,
            ts_rank(
                to_tsvector('spanish', COALESCE(pcu.title, '') || ' ' || COALESCE(pcu.summary, '')),
                plainto_tsquery('spanish', p_query_text)
            )::double precision AS keyword_score
        FROM press_context_units pcu
        WHERE
            -- Company filter: own company OR pool (if include_pool = true)
            (pcu.company_id = p_company_id OR (p_include_pool = true AND pcu.company_id = pool_uuid))
            -- Time filter
            AND (p_max_days IS NULL OR pcu.created_at > NOW() - (p_max_days || ' days')::interval)
            -- Category filter
            AND (p_category IS NULL OR pcu.category = p_category)
            -- Source type filter
            AND (p_source_type IS NULL OR pcu.source_type = p_source_type)
            -- Text search match
            AND to_tsvector('spanish', COALESCE(pcu.title, '') || ' ' || COALESCE(pcu.summary, '')) 
                @@ plainto_tsquery('spanish', p_query_text)
        ORDER BY keyword_score DESC
        LIMIT p_limit * 3  -- Get more candidates for union
    ),
    combined_results AS (
        -- UNION de ambos resultados con FULL OUTER JOIN para evitar duplicados
        SELECT 
            COALESCE(s.id, k.id) AS id,
            COALESCE(s.company_id, k.company_id) AS company_id,
            COALESCE(s.title, k.title) AS title,
            COALESCE(s.summary, k.summary) AS summary,
            COALESCE(s.category, k.category) AS category,
            COALESCE(s.tags, k.tags) AS tags,
            COALESCE(s.source_type, k.source_type) AS source_type,
            COALESCE(s.created_at, k.created_at) AS created_at,
            COALESCE(s.semantic_score, 0.0)::double precision AS semantic_score,
            COALESCE(k.keyword_score, 0.0)::double precision AS keyword_score,
            -- Combined score: 70% semantic + 30% keyword (semantic preferred)
            (COALESCE(s.semantic_score, 0.0) * 0.7 + COALESCE(k.keyword_score, 0.0) * 0.3)::double precision AS combined_score
        FROM semantic_results s
        FULL OUTER JOIN keyword_results k ON s.id = k.id
    )
    SELECT 
        cr.id,
        cr.company_id,
        cr.title,
        cr.summary,
        cr.category,
        cr.tags,
        cr.source_type,
        cr.created_at,
        cr.semantic_score,
        cr.keyword_score,
        cr.combined_score
    FROM combined_results cr
    ORDER BY cr.combined_score DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

-- Add comment
COMMENT ON FUNCTION public.hybrid_search_context_units IS 
'Hybrid search combining semantic (pgvector) and keyword (full-text) search with re-ranking';
