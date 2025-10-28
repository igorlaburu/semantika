-- Create demo user with unlimited plan
-- This maintains backward compatibility while implementing the new system

-- ============================================
-- DEMO COMPANY & ORGANIZATION
-- ============================================

-- Insert demo company (if not exists)
INSERT INTO companies (
    id,
    company_code,
    company_name,
    tier,
    is_active,
    settings
) VALUES (
    '00000000-0000-0000-0000-000000000001',
    'demo',
    'Demo Company (Unlimited)',
    'unlimited',
    true,
    '{"email_alias": "demo@ekimen.ai", "unlimited_usage": true}'::JSONB
) ON CONFLICT (id) DO UPDATE SET
    tier = 'unlimited',
    settings = '{"email_alias": "demo@ekimen.ai", "unlimited_usage": true}'::JSONB;

-- Insert demo organization (if not exists)
INSERT INTO organizations (
    id,
    company_id,
    slug,
    name,
    is_active,
    settings
) VALUES (
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000001',
    'demo',
    'Demo Organization',
    true,
    '{"store_in_qdrant": false, "unlimited_usage": true}'::JSONB
) ON CONFLICT (id) DO UPDATE SET
    company_id = '00000000-0000-0000-0000-000000000001',
    settings = '{"store_in_qdrant": false, "unlimited_usage": true}'::JSONB;

-- ============================================
-- DEMO CLIENT
-- ============================================

-- Insert demo client (if not exists)
INSERT INTO clients (
    client_id,
    company_id,
    organization_id,
    client_name,
    email,
    api_key,
    is_active,
    metadata
) VALUES (
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000001',
    'Demo User',
    'demo@ekimen.ai',
    'sk-demo-unlimited-test-key-0000000000000000000000000000',
    true,
    '{"tier": "unlimited", "unlimited_usage": true}'::JSONB
) ON CONFLICT (client_id) DO UPDATE SET
    company_id = '00000000-0000-0000-0000-000000000001',
    organization_id = '00000000-0000-0000-0000-000000000001',
    api_key = 'sk-demo-unlimited-test-key-0000000000000000000000000000',
    metadata = '{"tier": "unlimited", "unlimited_usage": true}'::JSONB;

-- ============================================
-- WORKFLOW CONFIGURATIONS
-- ============================================

-- Apply workflow system table if not exists
-- (This should be run after create_workflow_system.sql)

-- Update workflow configs to include unlimited tier
UPDATE workflow_configs SET 
    limits_unlimited = '{"monthly": -1, "daily": -1}'::JSONB,
    default_monthly_limit = 999999,
    default_daily_limit = 99999
WHERE limits_unlimited IS NULL;

-- Add unlimited tier column if missing
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'workflow_configs' 
        AND column_name = 'limits_unlimited'
    ) THEN
        ALTER TABLE workflow_configs 
        ADD COLUMN limits_unlimited JSONB DEFAULT '{"monthly": -1, "daily": -1}'::JSONB;
    END IF;
END $$;

-- ============================================
-- SEED WORKFLOW CONFIGS WITH UNLIMITED TIER
-- ============================================

INSERT INTO workflow_configs (
    workflow_code, 
    workflow_name, 
    description, 
    api_endpoint, 
    is_api_enabled,
    limits_starter,
    limits_pro,
    limits_unlimited,
    default_monthly_limit,
    default_daily_limit,
    estimated_cost_eur
) VALUES 
    ('micro_edit', 'Micro Edit', 'Text micro-editing with LLM', '/api/process/micro-edit', TRUE, 
     '{"monthly": 500, "daily": 25}', '{"monthly": 2000, "daily": 100}', '{"monthly": -1, "daily": -1}',
     100, 10, 0.0080),
    
    ('analyze', 'Text Analysis', 'Extract title, summary, tags from text', '/process/analyze', TRUE,
     '{"monthly": 1000, "daily": 50}', '{"monthly": 5000, "daily": 200}', '{"monthly": -1, "daily": -1}',
     1000, 50, 0.0020),
     
    ('analyze_atomic', 'Atomic Analysis', 'Extract atomic facts from text', '/process/analyze-atomic', TRUE,
     '{"monthly": 500, "daily": 25}', '{"monthly": 2000, "daily": 100}', '{"monthly": -1, "daily": -1}',
     500, 25, 0.0050),
     
    ('redact_news', 'News Generation', 'Generate news articles from facts', '/process/redact-news', TRUE,
     '{"monthly": 200, "daily": 10}', '{"monthly": 1000, "daily": 50}', '{"monthly": -1, "daily": -1}',
     200, 10, 0.0150),
     
    ('style_generation', 'Style Guide Generation', 'Generate writing style guides', '/styles/generate', TRUE,
     '{"monthly": 10, "daily": 2}', '{"monthly": 50, "daily": 5}', '{"monthly": -1, "daily": -1}',
     10, 2, 0.1200),

    ('url_processing', 'URL Processing', 'Scrape and process URL content', '/process/url', TRUE,
     '{"monthly": 500, "daily": 25}', '{"monthly": 2000, "daily": 100}', '{"monthly": -1, "daily": -1}',
     500, 25, 0.0080)

ON CONFLICT (workflow_code) DO UPDATE SET
    limits_unlimited = EXCLUDED.limits_unlimited,
    default_monthly_limit = EXCLUDED.default_monthly_limit,
    default_daily_limit = EXCLUDED.default_daily_limit,
    estimated_cost_eur = EXCLUDED.estimated_cost_eur;

-- ============================================
-- COMMENTS
-- ============================================
COMMENT ON COLUMN companies.tier IS 'Pricing tier: starter, pro, unlimited';
COMMENT ON COLUMN workflow_configs.limits_unlimited IS 'No limits (-1) for unlimited tier';

-- Success message
DO $$ 
BEGIN
    RAISE NOTICE 'Demo user created successfully:';
    RAISE NOTICE 'API Key: sk-demo-unlimited-test-key-0000000000000000000000000000';
    RAISE NOTICE 'Email: demo@ekimen.ai';
    RAISE NOTICE 'Tier: unlimited (no usage limits)';
    RAISE NOTICE 'Company: demo';
    RAISE NOTICE 'Organization: demo';
END $$;