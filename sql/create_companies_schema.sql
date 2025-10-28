-- SQL Script para crear esquema de multi-tenancy
-- Ejecutar ANTES del rename de tablas

-- ============================================
-- 1. CREAR TABLA COMPANIES
-- ============================================

CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_code VARCHAR(50) UNIQUE NOT NULL,
    company_name VARCHAR(200) NOT NULL,
    settings JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- Índices para companies
CREATE INDEX IF NOT EXISTS idx_companies_code ON companies (company_code);
CREATE INDEX IF NOT EXISTS idx_companies_active ON companies (is_active);
CREATE INDEX IF NOT EXISTS idx_companies_created_at ON companies (created_at DESC);

-- ============================================
-- 2. AGREGAR COMPANY_ID A TABLAS EXISTENTES
-- ============================================

-- Agregar company_id a clients (si no existe)
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'clients' AND column_name = 'company_id') THEN
        ALTER TABLE clients ADD COLUMN company_id UUID REFERENCES companies(id);
    END IF;
END $$;

-- Agregar company_id a tasks (si no existe)
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'tasks' AND column_name = 'company_id') THEN
        ALTER TABLE tasks ADD COLUMN company_id UUID REFERENCES companies(id);
    END IF;
END $$;

-- Agregar company_id a llm_usage (si no existe)
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'llm_usage' AND column_name = 'company_id') THEN
        ALTER TABLE llm_usage ADD COLUMN company_id UUID;
    END IF;
END $$;

-- Agregar company_id a organizations (si no existe)
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'organizations' AND column_name = 'company_id') THEN
        ALTER TABLE organizations ADD COLUMN company_id UUID REFERENCES companies(id);
    END IF;
END $$;

-- Agregar company_id a api_credentials (si no existe)
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'api_credentials' AND column_name = 'company_id') THEN
        ALTER TABLE api_credentials ADD COLUMN company_id UUID REFERENCES companies(id);
    END IF;
END $$;

-- ============================================
-- 3. AGREGAR COMPANY_ID A TABLAS QUE SERÁN RENOMBRADAS
-- ============================================

-- Agregar company_id a context_units (si existe)
DO $$ 
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'context_units') 
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns 
                       WHERE table_name = 'context_units' AND column_name = 'company_id') THEN
        ALTER TABLE context_units ADD COLUMN company_id UUID REFERENCES companies(id);
    END IF;
END $$;

-- Agregar company_id a articles (si existe)
DO $$ 
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'articles') 
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns 
                       WHERE table_name = 'articles' AND column_name = 'company_id') THEN
        ALTER TABLE articles ADD COLUMN company_id UUID REFERENCES companies(id);
    END IF;
END $$;

-- Agregar company_id a news (si existe)
DO $$ 
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'news') 
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns 
                       WHERE table_name = 'news' AND column_name = 'company_id') THEN
        ALTER TABLE news ADD COLUMN company_id UUID REFERENCES companies(id);
    END IF;
END $$;

-- Agregar company_id a styles (si existe)
DO $$ 
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'styles') 
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns 
                       WHERE table_name = 'styles' AND column_name = 'company_id') THEN
        ALTER TABLE styles ADD COLUMN company_id UUID REFERENCES companies(id);
    END IF;
END $$;

-- ============================================
-- 4. CREAR EMPRESA DE EJEMPLO/DEFAULT
-- ============================================

-- Insertar empresa de ejemplo (evitar duplicados)
INSERT INTO companies (company_code, company_name, settings)
VALUES ('default', 'Default Company', '{"store_in_qdrant": true}')
ON CONFLICT (company_code) DO NOTHING;

-- ============================================
-- 5. ACTUALIZAR DATOS EXISTENTES (TEMPORAL)
-- ============================================

-- Obtener el ID de la empresa default
DO $$ 
DECLARE
    default_company_id UUID;
BEGIN
    SELECT id INTO default_company_id FROM companies WHERE company_code = 'default';
    
    -- Actualizar clients existentes sin company_id
    UPDATE clients SET company_id = default_company_id WHERE company_id IS NULL;
    
    -- Actualizar tasks existentes sin company_id
    UPDATE tasks SET company_id = default_company_id WHERE company_id IS NULL;
    
    -- Actualizar organizations existentes sin company_id
    UPDATE organizations SET company_id = default_company_id WHERE company_id IS NULL;
    
    -- Actualizar llm_usage existentes sin company_id
    UPDATE llm_usage SET company_id = default_company_id WHERE company_id IS NULL;
    
    -- Actualizar api_credentials existentes sin company_id  
    UPDATE api_credentials SET company_id = default_company_id WHERE company_id IS NULL;
    
    -- Actualizar tablas que serán renombradas (si existen)
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'context_units') THEN
        UPDATE context_units SET company_id = default_company_id WHERE company_id IS NULL;
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'articles') THEN
        UPDATE articles SET company_id = default_company_id WHERE company_id IS NULL;
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'news') THEN
        UPDATE news SET company_id = default_company_id WHERE company_id IS NULL;
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'styles') THEN
        UPDATE styles SET company_id = default_company_id WHERE company_id IS NULL;
    END IF;
END $$;

-- ============================================
-- 6. CREAR ÍNDICES PARA COMPANY_ID
-- ============================================

-- Índices en tablas principales
CREATE INDEX IF NOT EXISTS idx_clients_company_id ON clients (company_id);
CREATE INDEX IF NOT EXISTS idx_tasks_company_id ON tasks (company_id);
CREATE INDEX IF NOT EXISTS idx_llm_usage_company_id ON llm_usage (company_id);
CREATE INDEX IF NOT EXISTS idx_organizations_company_id ON organizations (company_id);
CREATE INDEX IF NOT EXISTS idx_api_credentials_company_id ON api_credentials (company_id);

-- Índices en tablas que serán renombradas (si existen)
DO $$ 
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'context_units') THEN
        CREATE INDEX IF NOT EXISTS idx_context_units_company_id ON context_units (company_id);
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'articles') THEN
        CREATE INDEX IF NOT EXISTS idx_articles_company_id ON articles (company_id);
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'news') THEN
        CREATE INDEX IF NOT EXISTS idx_news_company_id ON news (company_id);
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'styles') THEN
        CREATE INDEX IF NOT EXISTS idx_styles_company_id ON styles (company_id);
    END IF;
END $$;

-- ============================================
-- 7. VERIFICACIÓN
-- ============================================

-- Verificar que companies fue creada
SELECT 
    table_name, 
    column_name, 
    data_type, 
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'companies'
ORDER BY ordinal_position;

-- Verificar company_id agregada a todas las tablas
SELECT 
    table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns 
WHERE column_name = 'company_id'
    AND table_schema = 'public'
ORDER BY table_name;

-- Verificar empresa default creada
SELECT company_code, company_name, is_active FROM companies;

-- Contar registros actualizados
SELECT 
    'clients' as table_name, 
    COUNT(*) as total_records,
    COUNT(company_id) as with_company_id
FROM clients
UNION ALL
SELECT 
    'tasks' as table_name,
    COUNT(*) as total_records,
    COUNT(company_id) as with_company_id  
FROM tasks
UNION ALL
SELECT 
    'llm_usage' as table_name,
    COUNT(*) as total_records,
    COUNT(company_id) as with_company_id
FROM llm_usage;