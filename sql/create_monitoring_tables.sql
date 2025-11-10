-- ================================================================
-- SISTEMA INTELIGENTE DE MONITORIZACIÓN DE FUENTES
-- ================================================================
-- Crear tablas para tracking de URLs, detección de cambios,
-- y embeddings con pgvector (FastEmbed)
--
-- Tablas nuevas:
-- 1. monitored_urls: Tracking de URLs monitorizadas
-- 2. url_content_units: Unidades de contenido extraídas (multi-noticia)
-- 3. url_change_log: Historial de cambios detectados
--
-- Actualización:
-- 4. press_context_units: Añadir columna embedding (pgvector)
-- ================================================================

-- Habilitar extensión pgvector si no está activa
CREATE EXTENSION IF NOT EXISTS vector;

-- ================================================================
-- 1. TABLA: monitored_urls
-- ================================================================
-- Tracking de URLs monitorizadas (índices y artículos)
-- Almacena hashes, fechas, y metadata para detección de cambios

CREATE TABLE IF NOT EXISTS monitored_urls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    
    -- URL tracking
    url TEXT NOT NULL,
    url_type TEXT NOT NULL CHECK (url_type IN ('index', 'article')),
    parent_url_id UUID REFERENCES monitored_urls(id) ON DELETE SET NULL,  -- Jerarquía (article → index)
    
    -- Contenido normalizado
    title TEXT,
    semantic_content TEXT,  -- Contenido sin HTML, normalizado (para hash)
    
    -- Detección de cambios (multi-tier)
    content_hash TEXT,  -- SHA256 de semantic_content
    simhash BIGINT,  -- SimHash para fuzzy matching
    last_embedding_check TIMESTAMPTZ,  -- Última vez que usamos embeddings (tier 3)
    
    -- Fechas
    published_at TIMESTAMPTZ,  -- Fecha publicación detectada (la más antigua)
    date_source TEXT CHECK (date_source IN ('meta_tag', 'jsonld', 'url_pattern', 'css_selector', 'llm', 'unknown')),
    date_confidence FLOAT CHECK (date_confidence >= 0 AND date_confidence <= 1),
    last_scraped_at TIMESTAMPTZ,
    last_modified_at TIMESTAMPTZ,
    
    -- Estado
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'archived', 'error')),
    error_message TEXT,  -- Si status='error', motivo del error
    
    -- Metadata
    metadata JSONB DEFAULT '{}',  -- Snapshot de hashes, selectores usados, etc.
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    UNIQUE(company_id, url)  -- Una URL solo una vez por empresa
);

-- Índices para monitored_urls
CREATE INDEX IF NOT EXISTS idx_monitored_urls_company ON monitored_urls(company_id);
CREATE INDEX IF NOT EXISTS idx_monitored_urls_source ON monitored_urls(source_id);
CREATE INDEX IF NOT EXISTS idx_monitored_urls_parent ON monitored_urls(parent_url_id);
CREATE INDEX IF NOT EXISTS idx_monitored_urls_hash ON monitored_urls(content_hash);
CREATE INDEX IF NOT EXISTS idx_monitored_urls_status_active ON monitored_urls(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_monitored_urls_url_type ON monitored_urls(url_type);

-- Comentarios
COMMENT ON TABLE monitored_urls IS 'Tracking de URLs monitorizadas (índices y artículos individuales)';
COMMENT ON COLUMN monitored_urls.url_type IS 'index = portada/listado, article = artículo individual';
COMMENT ON COLUMN monitored_urls.semantic_content IS 'Contenido normalizado sin HTML para cálculo de hash';
COMMENT ON COLUMN monitored_urls.content_hash IS 'SHA256 del semantic_content (Tier 1 detección)';
COMMENT ON COLUMN monitored_urls.simhash IS 'SimHash para detección fuzzy de cambios (Tier 2)';
COMMENT ON COLUMN monitored_urls.last_embedding_check IS 'Última verificación con embeddings (Tier 3 - costoso)';
COMMENT ON COLUMN monitored_urls.published_at IS 'Fecha de publicación detectada (multi-source, la más antigua gana)';

-- ================================================================
-- 2. TABLA: url_content_units
-- ================================================================
-- Unidades de contenido extraídas de URLs (para URLs multi-noticia)
-- Una URL puede tener N noticias → N filas aquí

CREATE TABLE IF NOT EXISTS url_content_units (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    monitored_url_id UUID NOT NULL REFERENCES monitored_urls(id) ON DELETE CASCADE,
    
    -- Posición en la página (para URLs multi-noticia)
    content_position INT NOT NULL DEFAULT 1,
    
    -- Contenido
    title TEXT NOT NULL,
    summary TEXT,
    raw_content TEXT,  -- Contenido bruto extraído
    
    -- Detección de cambios (específico de esta unidad)
    content_hash TEXT NOT NULL,  -- Hash específico de esta unidad
    simhash BIGINT,
    
    -- Fecha
    published_at TIMESTAMPTZ,
    date_source TEXT CHECK (date_source IN ('meta_tag', 'jsonld', 'url_pattern', 'css_selector', 'llm', 'unknown')),
    date_confidence FLOAT CHECK (date_confidence >= 0 AND date_confidence <= 1),
    
    -- Embedding (pgvector - 384 dimensiones para FastEmbed multilingual)
    embedding vector(384),
    
    -- Estado
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    
    -- Tracking de ingestión
    ingested_to_context_unit_id UUID,  -- Referencia a press_context_units si fue ingestado
    ingested_at TIMESTAMPTZ,
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraint: Una posición por URL
    UNIQUE(monitored_url_id, content_position)
);

-- Índices para url_content_units
CREATE INDEX IF NOT EXISTS idx_url_content_units_company ON url_content_units(company_id);
CREATE INDEX IF NOT EXISTS idx_url_content_units_monitored ON url_content_units(monitored_url_id);
CREATE INDEX IF NOT EXISTS idx_url_content_units_hash ON url_content_units(content_hash);
CREATE INDEX IF NOT EXISTS idx_url_content_units_status_active ON url_content_units(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_url_content_units_ingested ON url_content_units(ingested_to_context_unit_id) WHERE ingested_to_context_unit_id IS NOT NULL;

-- Índice vectorial para búsqueda de similitud (FastEmbed 384 dim)
CREATE INDEX IF NOT EXISTS idx_url_content_units_embedding 
ON url_content_units 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Comentarios
COMMENT ON TABLE url_content_units IS 'Unidades de contenido individuales extraídas de URLs (soporta multi-noticia)';
COMMENT ON COLUMN url_content_units.content_position IS 'Posición/orden de la noticia dentro de la URL (1, 2, 3...)';
COMMENT ON COLUMN url_content_units.embedding IS 'Embedding FastEmbed multilingual (384 dim) para detección de duplicados';
COMMENT ON COLUMN url_content_units.ingested_to_context_unit_id IS 'ID del press_context_unit generado (si fue procesado)';

-- ================================================================
-- 3. TABLA: url_change_log
-- ================================================================
-- Historial de cambios detectados en URLs monitorizadas

CREATE TABLE IF NOT EXISTS url_change_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    monitored_url_id UUID NOT NULL REFERENCES monitored_urls(id) ON DELETE CASCADE,
    
    -- Tipo de cambio detectado
    change_type TEXT NOT NULL CHECK (change_type IN (
        'new',           -- URL nueva, primera vez que se ve
        'identical',     -- Contenido idéntico (hash match)
        'trivial',       -- Cambio trivial (simhash muy similar)
        'minor_update',  -- Actualización menor (embedding similar)
        'major_update',  -- Actualización significativa
        'archived'       -- Contenido desapareció
    )),
    
    -- Detección (qué tier lo detectó)
    detection_tier INT CHECK (detection_tier IN (1, 2, 3)),  -- 1=hash, 2=simhash, 3=embedding
    similarity_score FLOAT,  -- Para tier 2 y 3 (0.0-1.0)
    
    -- Hashes (para debugging/auditoría)
    old_hash TEXT,
    new_hash TEXT,
    
    -- Metadata del cambio
    metadata JSONB DEFAULT '{}',  -- Detalles específicos del cambio
    
    -- Estado
    processed BOOLEAN DEFAULT FALSE,  -- ¿Ya se procesó este cambio?
    
    -- Timestamp
    detected_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para url_change_log
CREATE INDEX IF NOT EXISTS idx_url_change_log_monitored ON url_change_log(monitored_url_id);
CREATE INDEX IF NOT EXISTS idx_url_change_log_type ON url_change_log(change_type);
CREATE INDEX IF NOT EXISTS idx_url_change_log_detected ON url_change_log(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_url_change_log_processed ON url_change_log(processed) WHERE processed = FALSE;

-- Comentarios
COMMENT ON TABLE url_change_log IS 'Historial de cambios detectados en URLs monitorizadas';
COMMENT ON COLUMN url_change_log.detection_tier IS 'Tier de detección: 1=hash (exacto), 2=simhash (fuzzy), 3=embedding (semántico)';
COMMENT ON COLUMN url_change_log.change_type IS 'Tipo de cambio: new, identical, trivial, minor_update, major_update, archived';

-- ================================================================
-- 4. ACTUALIZAR: press_context_units (añadir embedding)
-- ================================================================
-- Añadir columna embedding para detección de duplicados universal
-- (usado por scraping, email, Perplexity, etc.)

-- Añadir columna embedding si no existe
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'press_context_units' 
        AND column_name = 'embedding'
    ) THEN
        ALTER TABLE press_context_units 
        ADD COLUMN embedding vector(384);
    END IF;
END $$;

-- Añadir columna url_content_unit_id si no existe (trazabilidad)
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'press_context_units' 
        AND column_name = 'url_content_unit_id'
    ) THEN
        ALTER TABLE press_context_units 
        ADD COLUMN url_content_unit_id UUID REFERENCES url_content_units(id) ON DELETE SET NULL;
    END IF;
END $$;

-- Índice vectorial para búsqueda de similitud
CREATE INDEX IF NOT EXISTS idx_context_units_embedding 
ON press_context_units 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Índice para trazabilidad
CREATE INDEX IF NOT EXISTS idx_context_units_url_content ON press_context_units(url_content_unit_id) 
WHERE url_content_unit_id IS NOT NULL;

-- Comentarios
COMMENT ON COLUMN press_context_units.embedding IS 'Embedding FastEmbed multilingual (384 dim) de title+summary para detección de duplicados';
COMMENT ON COLUMN press_context_units.url_content_unit_id IS 'Referencia al url_content_unit de origen (solo para source_type=scraping)';

-- ================================================================
-- 5. FUNCIONES AUXILIARES: Búsqueda de similitud
-- ================================================================

-- Función para buscar context units similares (detección de duplicados)
CREATE OR REPLACE FUNCTION match_context_units(
    query_embedding vector(384),
    company_id_filter UUID,
    match_threshold FLOAT DEFAULT 0.95,
    match_count INT DEFAULT 5
)
RETURNS TABLE (
    id UUID,
    title TEXT,
    summary TEXT,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        pcu.id,
        pcu.title,
        pcu.summary,
        1 - (pcu.embedding <=> query_embedding) AS similarity
    FROM press_context_units pcu
    WHERE pcu.company_id = company_id_filter
        AND pcu.embedding IS NOT NULL
        AND 1 - (pcu.embedding <=> query_embedding) >= match_threshold
    ORDER BY pcu.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- Función para buscar url_content_units similares
CREATE OR REPLACE FUNCTION match_url_content_units(
    query_embedding vector(384),
    company_id_filter UUID,
    match_threshold FLOAT DEFAULT 0.95,
    match_count INT DEFAULT 5
)
RETURNS TABLE (
    id UUID,
    title TEXT,
    summary TEXT,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        ucu.id,
        ucu.title,
        ucu.summary,
        1 - (ucu.embedding <=> query_embedding) AS similarity
    FROM url_content_units ucu
    WHERE ucu.company_id = company_id_filter
        AND ucu.embedding IS NOT NULL
        AND 1 - (ucu.embedding <=> query_embedding) >= match_threshold
    ORDER BY ucu.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- Comentarios de funciones
COMMENT ON FUNCTION match_context_units IS 'Busca context units similares por embedding (detección de duplicados)';
COMMENT ON FUNCTION match_url_content_units IS 'Busca url_content_units similares por embedding';

-- ================================================================
-- 6. TRIGGERS: Actualizar updated_at automáticamente
-- ================================================================

-- Función genérica para actualizar updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger para monitored_urls
DROP TRIGGER IF EXISTS update_monitored_urls_updated_at ON monitored_urls;
CREATE TRIGGER update_monitored_urls_updated_at
    BEFORE UPDATE ON monitored_urls
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Trigger para url_content_units
DROP TRIGGER IF EXISTS update_url_content_units_updated_at ON url_content_units;
CREATE TRIGGER update_url_content_units_updated_at
    BEFORE UPDATE ON url_content_units
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ================================================================
-- 7. RLS (Row Level Security) - Multi-tenancy
-- ================================================================

-- Habilitar RLS en las nuevas tablas
ALTER TABLE monitored_urls ENABLE ROW LEVEL SECURITY;
ALTER TABLE url_content_units ENABLE ROW LEVEL SECURITY;
ALTER TABLE url_change_log ENABLE ROW LEVEL SECURITY;

-- Políticas para monitored_urls
CREATE POLICY "Users read own company monitored_urls"
    ON monitored_urls FOR SELECT
    USING (company_id = (SELECT company_id FROM user_profiles WHERE id = auth.uid()));

CREATE POLICY "Users manage own company monitored_urls"
    ON monitored_urls FOR ALL
    USING (company_id = (SELECT company_id FROM user_profiles WHERE id = auth.uid()));

-- Políticas para url_content_units
CREATE POLICY "Users read own company url_content_units"
    ON url_content_units FOR SELECT
    USING (company_id = (SELECT company_id FROM user_profiles WHERE id = auth.uid()));

CREATE POLICY "Users manage own company url_content_units"
    ON url_content_units FOR ALL
    USING (company_id = (SELECT company_id FROM user_profiles WHERE id = auth.uid()));

-- Políticas para url_change_log (solo lectura para usuarios, escritura para sistema)
CREATE POLICY "Users read own company url_change_log"
    ON url_change_log FOR SELECT
    USING (EXISTS (
        SELECT 1 FROM monitored_urls mu
        WHERE mu.id = url_change_log.monitored_url_id
        AND mu.company_id = (SELECT company_id FROM user_profiles WHERE id = auth.uid())
    ));

-- ================================================================
-- FIN DEL SCRIPT
-- ================================================================

-- Verificar que todo se creó correctamente
DO $$
DECLARE
    table_count INT;
    index_count INT;
BEGIN
    -- Contar tablas nuevas
    SELECT COUNT(*) INTO table_count
    FROM information_schema.tables
    WHERE table_name IN ('monitored_urls', 'url_content_units', 'url_change_log');
    
    -- Contar índices vectoriales
    SELECT COUNT(*) INTO index_count
    FROM pg_indexes
    WHERE indexname LIKE '%embedding%';
    
    RAISE NOTICE 'Tablas creadas: %', table_count;
    RAISE NOTICE 'Índices vectoriales: %', index_count;
    RAISE NOTICE 'pgvector habilitado: %', (SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector');
    
    IF table_count >= 3 AND index_count >= 2 THEN
        RAISE NOTICE '✅ Sistema de monitorización instalado correctamente';
    ELSE
        RAISE WARNING '⚠️ Verificar instalación - algunas tablas o índices pueden estar faltando';
    END IF;
END $$;
