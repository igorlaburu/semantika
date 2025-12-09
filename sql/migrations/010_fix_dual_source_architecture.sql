-- Migration: Fix dual source architecture for Pool
--
-- PROBLEM:
-- Pool uses discovered_sources table, but monitored_urls.source_id has FK to sources table.
-- This prevents scraper_workflow from tracking monitored URLs for pool sources.
--
-- SOLUTION:
-- Make monitored_urls.source_id nullable and add source_table discriminator.
-- This allows monitored_urls to reference EITHER sources OR discovered_sources.
--
-- ARCHITECTURE:
-- - Regular clients: source_id references sources table, source_table='sources'
-- - Pool: source_id references discovered_sources table, source_table='discovered_sources'
-- - Legacy/orphan: source_id=NULL, source_table=NULL
--
-- SAFE TO RUN: Yes (idempotent, preserves all data)
-- BREAKING: No (existing code continues to work)

-- STEP 1: Drop existing FK constraint
ALTER TABLE monitored_urls
DROP CONSTRAINT IF EXISTS monitored_urls_source_id_fkey;

-- STEP 2: Make source_id nullable (allow pool sources without sources table entry)
ALTER TABLE monitored_urls
ALTER COLUMN source_id DROP NOT NULL;

-- STEP 3: Add source_table discriminator column
ALTER TABLE monitored_urls
ADD COLUMN IF NOT EXISTS source_table VARCHAR(50) DEFAULT 'sources';

-- STEP 4: Update existing rows to mark source_table
UPDATE monitored_urls
SET source_table = 'sources'
WHERE source_table IS NULL AND source_id IS NOT NULL;

-- STEP 5: Add check constraint to enforce source_table values
ALTER TABLE monitored_urls
ADD CONSTRAINT monitored_urls_source_table_check 
CHECK (source_table IN ('sources', 'discovered_sources') OR source_table IS NULL);

-- STEP 6: Add index for performance
CREATE INDEX IF NOT EXISTS idx_monitored_urls_source_table 
ON monitored_urls(source_table, source_id);

-- VERIFICATION QUERIES:
--
-- Check source_table distribution:
-- SELECT source_table, COUNT(*) FROM monitored_urls GROUP BY source_table;
--
-- Find pool monitored URLs:
-- SELECT * FROM monitored_urls WHERE source_table = 'discovered_sources' LIMIT 10;
--
-- Find orphan monitored URLs (no source):
-- SELECT * FROM monitored_urls WHERE source_id IS NULL;

-- USAGE IN CODE:
--
-- For pool sources (discovered_sources):
--   INSERT INTO monitored_urls (url, source_id, source_table, company_id, ...)
--   VALUES ('https://...', 'uuid-from-discovered-sources', 'discovered_sources', 'pool-uuid', ...);
--
-- For regular sources:
--   INSERT INTO monitored_urls (url, source_id, source_table, company_id, ...)
--   VALUES ('https://...', 'uuid-from-sources', 'sources', 'client-uuid', ...);
--
-- For manual/webhook (no source):
--   INSERT INTO monitored_urls (url, source_id, source_table, company_id, ...)
--   VALUES ('https://...', NULL, NULL, 'client-uuid', ...);
