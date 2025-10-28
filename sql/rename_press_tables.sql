-- SQL Script para renombrar tablas con prefijo press_
-- IMPORTANTE: Ejecutar DESPUÉS de create_companies_schema.sql
-- Ejecutar en Supabase SQL Editor

-- ============================================
-- 1. RENOMBRAR TABLAS
-- ============================================

-- Renombrar tablas principales
ALTER TABLE IF EXISTS articles RENAME TO press_articles;
ALTER TABLE IF EXISTS news RENAME TO press_news;
ALTER TABLE IF EXISTS context_units RENAME TO press_context_units;
ALTER TABLE IF EXISTS styles RENAME TO press_styles;

-- ============================================
-- 2. RENOMBRAR ÍNDICES
-- ============================================

-- Índices de press_articles (si existen)
ALTER INDEX IF EXISTS articles_pkey RENAME TO press_articles_pkey;
ALTER INDEX IF EXISTS idx_articles_company_id RENAME TO idx_press_articles_company_id;
ALTER INDEX IF EXISTS idx_articles_created_at RENAME TO idx_press_articles_created_at;
ALTER INDEX IF EXISTS idx_articles_is_active RENAME TO idx_press_articles_is_active;

-- Índices de press_news (si existen)
ALTER INDEX IF EXISTS news_pkey RENAME TO press_news_pkey;
ALTER INDEX IF EXISTS idx_news_company_id RENAME TO idx_press_news_company_id;
ALTER INDEX IF EXISTS idx_news_created_at RENAME TO idx_press_news_created_at;
ALTER INDEX IF EXISTS idx_news_is_active RENAME TO idx_press_news_is_active;

-- Índices de press_context_units (si existen)
ALTER INDEX IF EXISTS context_units_pkey RENAME TO press_context_units_pkey;
ALTER INDEX IF EXISTS idx_context_units_company_id RENAME TO idx_press_context_units_company_id;
ALTER INDEX IF EXISTS idx_context_units_organization_id RENAME TO idx_press_context_units_organization_id;
ALTER INDEX IF EXISTS idx_context_units_created_at RENAME TO idx_press_context_units_created_at;
ALTER INDEX IF EXISTS idx_context_units_source_type RENAME TO idx_press_context_units_source_type;

-- Índices de press_styles (si existen)
ALTER INDEX IF EXISTS styles_pkey RENAME TO press_styles_pkey;
ALTER INDEX IF EXISTS idx_styles_company_id RENAME TO idx_press_styles_company_id;
ALTER INDEX IF EXISTS idx_styles_created_at RENAME TO idx_press_styles_created_at;
ALTER INDEX IF EXISTS idx_styles_is_active RENAME TO idx_press_styles_is_active;

-- ============================================
-- 3. RENOMBRAR CONSTRAINTS (FOREIGN KEYS) - SOLO LOS QUE EXISTEN
-- ============================================

-- Solo recrear foreign keys para company_id (que sabemos que existe)
DO $$ 
BEGIN
    -- press_context_units company_id FK
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'press_context_units') THEN
        ALTER TABLE press_context_units 
            DROP CONSTRAINT IF EXISTS context_units_company_id_fkey;
        ALTER TABLE press_context_units 
            ADD CONSTRAINT press_context_units_company_id_fkey 
            FOREIGN KEY (company_id) REFERENCES companies(id);
    END IF;
    
    -- press_context_units organization_id FK (si existe la columna)
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'press_context_units')
       AND EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'press_context_units' AND column_name = 'organization_id') THEN
        ALTER TABLE press_context_units 
            DROP CONSTRAINT IF EXISTS context_units_organization_id_fkey;
        ALTER TABLE press_context_units 
            ADD CONSTRAINT press_context_units_organization_id_fkey 
            FOREIGN KEY (organization_id) REFERENCES organizations(id);
    END IF;
    
    -- press_articles company_id FK (si existe la tabla)
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'press_articles') THEN
        ALTER TABLE press_articles 
            DROP CONSTRAINT IF EXISTS articles_company_id_fkey;
        ALTER TABLE press_articles 
            ADD CONSTRAINT press_articles_company_id_fkey 
            FOREIGN KEY (company_id) REFERENCES companies(id);
    END IF;
    
    -- press_news company_id FK (si existe la tabla)
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'press_news') THEN
        ALTER TABLE press_news 
            DROP CONSTRAINT IF EXISTS news_company_id_fkey;
        ALTER TABLE press_news 
            ADD CONSTRAINT press_news_company_id_fkey 
            FOREIGN KEY (company_id) REFERENCES companies(id);
    END IF;
    
    -- press_styles company_id FK (si existe la tabla)
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'press_styles') THEN
        ALTER TABLE press_styles 
            DROP CONSTRAINT IF EXISTS styles_company_id_fkey;
        ALTER TABLE press_styles 
            ADD CONSTRAINT press_styles_company_id_fkey 
            FOREIGN KEY (company_id) REFERENCES companies(id);
    END IF;
END $$;

-- ============================================
-- 4. RECREAR ÍNDICES ADICIONALES SI ES NECESARIO
-- ============================================

-- Índices de performance para press_context_units
CREATE INDEX IF NOT EXISTS idx_press_context_units_source_type_company 
    ON press_context_units (source_type, company_id);

CREATE INDEX IF NOT EXISTS idx_press_context_units_processed_at 
    ON press_context_units (processed_at DESC);

-- Índices de performance para press_articles
CREATE INDEX IF NOT EXISTS idx_press_articles_published_at 
    ON press_articles (published_at DESC);

CREATE INDEX IF NOT EXISTS idx_press_articles_status_company 
    ON press_articles (status, company_id);

-- Índices de performance para press_styles
CREATE INDEX IF NOT EXISTS idx_press_styles_name_company 
    ON press_styles (style_name, company_id);

-- ============================================
-- 5. VERIFICACIÓN
-- ============================================

-- Verificar que las tablas fueron renombradas correctamente
SELECT 
    table_name, 
    table_type 
FROM information_schema.tables 
WHERE table_schema = 'public' 
    AND table_name LIKE 'press_%'
ORDER BY table_name;

-- Verificar foreign keys
SELECT 
    tc.table_name, 
    tc.constraint_name, 
    tc.constraint_type,
    ccu.table_name AS foreign_table_name,
    ccu.column_name AS foreign_column_name
FROM information_schema.table_constraints AS tc 
JOIN information_schema.constraint_column_usage AS ccu
    ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY' 
    AND tc.table_name LIKE 'press_%'
ORDER BY tc.table_name, tc.constraint_name;

-- Verificar índices
SELECT 
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes 
WHERE tablename LIKE 'press_%'
ORDER BY tablename, indexname;