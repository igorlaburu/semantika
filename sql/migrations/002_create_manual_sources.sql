-- Migration: Create Manual source for all existing companies
-- Purpose: Backfill Manual sources (source.id = company.id) for companies created before this migration
-- Date: 2025-11-22

-- Create Manual source for each company that doesn't have one
INSERT INTO sources (
    id,                  -- source.id = company.id (key insight!)
    company_id,
    source_type,
    source_name,
    is_active,
    config,
    schedule_config,
    created_at
)
SELECT 
    c.id as id,                                    -- source.id = company.id
    c.id as company_id,
    'manual' as source_type,
    'Manual' as source_name,
    true as is_active,
    '{"description": "Contenido manual (API/Frontend/Email)"}'::jsonb as config,
    '{}'::jsonb as schedule_config,
    NOW() as created_at
FROM companies c
WHERE NOT EXISTS (
    SELECT 1 
    FROM sources s 
    WHERE s.id = c.id  -- Check if Manual source already exists with id = company_id
)
AND c.is_active = true;

-- Verify results
DO $$
DECLARE
    inserted_count INT;
BEGIN
    GET DIAGNOSTICS inserted_count = ROW_COUNT;
    RAISE NOTICE 'Created % Manual sources for existing companies', inserted_count;
END $$;

-- Check final state
SELECT 
    COUNT(*) as total_companies,
    (SELECT COUNT(*) FROM sources WHERE source_type = 'manual') as manual_sources_count
FROM companies 
WHERE is_active = true;
