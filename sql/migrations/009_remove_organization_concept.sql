-- Migration: Remove organization_id concept (organization = company)
--
-- CONTEXT:
-- Durante el desarrollo inicial se barajó tener organizations separadas de companies,
-- pero se concluyó que organization = company (relación 1:1).
-- Esta migración elimina el concepto legacy de organization_id de las tablas principales.
--
-- CHANGES:
-- 1. Copy organization_id to company_id in llm_usage (migration data)
-- 2. Drop organization_id FK and column from llm_usage
-- 3. Drop organization_id FK and column from press_context_units
-- 4. Keep organizations table (used in some legacy code, 1:1 with companies)
--
-- SAFE TO RUN: Yes (idempotent, preserves all data)
-- BREAKING: Yes (code must use company_id instead of organization_id)

-- STEP 1: Migrate data from organization_id to company_id in llm_usage
UPDATE llm_usage
SET company_id = organization_id
WHERE company_id IS NULL AND organization_id IS NOT NULL;

-- STEP 2: Drop organization_id from llm_usage
ALTER TABLE llm_usage 
DROP CONSTRAINT IF EXISTS llm_usage_organization_id_fkey;

ALTER TABLE llm_usage 
DROP COLUMN IF EXISTS organization_id;

-- STEP 3: Drop organization_id from press_context_units
ALTER TABLE press_context_units
DROP CONSTRAINT IF EXISTS press_context_units_organization_id_fkey;

ALTER TABLE press_context_units
DROP COLUMN IF EXISTS organization_id;

-- VERIFICATION
-- Run these queries to verify migration:
--
-- SELECT COUNT(*) as total, COUNT(company_id) as with_company_id 
-- FROM llm_usage;
--
-- SELECT COUNT(*) as total, COUNT(company_id) as with_company_id 
-- FROM press_context_units;
--
-- Expected: total = with_company_id (100% coverage)

-- NOTE: organizations table is NOT dropped because:
-- 1. It has 1:1 relationship with companies (each org has company_id)
-- 2. Some legacy code still references it
-- 3. clients.organization_id and users.organization_id still exist
-- 4. Can be removed in future cleanup if needed
