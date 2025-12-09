-- Migration: Add base_id for context unit enrichments
--
-- PROBLEM:
-- Pool context units are shared, but enrichments (background research, updates, etc.)
-- should be private per journalist. Currently enriching a pool unit modifies the
-- shared record, making enrichments visible to all users.
--
-- SOLUTION:
-- Add base_id field to support "enrichment children" of pool units:
-- - Pool unit: id = base_id (self-reference)
-- - Enrichment: id = new UUID, base_id = pool unit id, company_id = journalist's company
--
-- When fetching a context unit, query by base_id to get base + user's enrichments.
--
-- ARCHITECTURE:
-- Base unit (pool):
--   id: d5475dd4-..., company_id: 99999999-..., base_id: d5475dd4-..., statements: [1,2,3]
--
-- Enrichment (journalist A):
--   id: new-uuid-1, company_id: journalist-A-uuid, base_id: d5475dd4-..., statements: [4,5,6]
--
-- Query:
--   SELECT * FROM press_context_units 
--   WHERE base_id = 'd5475dd4-...' 
--   AND company_id IN ('99999999-...', 'journalist-A-uuid')
--
-- Returns: [base, enrichment] → merge statements → [1,2,3,4,5,6]

-- STEP 1: Add base_id column (nullable initially)
ALTER TABLE press_context_units
ADD COLUMN IF NOT EXISTS base_id UUID;

-- STEP 2: Populate base_id for existing records (self-reference)
-- All existing context units are "base" units (no enrichments yet)
UPDATE press_context_units
SET base_id = id
WHERE base_id IS NULL;

-- STEP 3: Make base_id NOT NULL (now that all rows have values)
ALTER TABLE press_context_units
ALTER COLUMN base_id SET NOT NULL;

-- STEP 4: Add foreign key constraint (base_id references id)
ALTER TABLE press_context_units
ADD CONSTRAINT press_context_units_base_id_fkey 
FOREIGN KEY (base_id) REFERENCES press_context_units(id) ON DELETE CASCADE;

-- STEP 5: Create composite index for efficient queries
CREATE INDEX IF NOT EXISTS idx_context_units_base_company 
ON press_context_units(base_id, company_id);

-- STEP 6: Add comment
COMMENT ON COLUMN press_context_units.base_id IS 
'References the canonical/base context unit. For base units: base_id = id. For enrichments: base_id = parent unit id.';

-- VERIFICATION QUERIES:
--
-- Check all base_id populated:
-- SELECT COUNT(*) as total, COUNT(base_id) as with_base_id FROM press_context_units;
--
-- Check self-references (should be all existing units):
-- SELECT COUNT(*) FROM press_context_units WHERE id = base_id;
--
-- Find enrichments of a specific unit:
-- SELECT * FROM press_context_units WHERE base_id = 'd5475dd4-...' AND company_id != '99999999-...';

-- USAGE IN CODE:
--
-- Create enrichment:
--   INSERT INTO press_context_units (
--     id, company_id, base_id, client_id, source_id,
--     title, summary, category, tags, atomic_statements, ...
--   ) VALUES (
--     gen_random_uuid(),
--     'journalist-uuid',
--     'd5475dd4-...',  -- base_id = pool unit id
--     'client-uuid',
--     NULL,  -- enrichments don't need source_id
--     NULL,  -- inherit title from base
--     NULL,  -- inherit summary from base
--     NULL,  -- inherit category from base
--     '[]',  -- inherit tags from base
--     '[{new enrichment statements}]',
--     ...
--   );
--
-- Fetch base + enrichments:
--   SELECT * FROM press_context_units
--   WHERE base_id = (SELECT base_id FROM press_context_units WHERE id = :context_unit_id)
--   AND (company_id = :pool_uuid OR company_id = :user_company_id)
--   ORDER BY CASE WHEN id = base_id THEN 0 ELSE 1 END;  -- Base first, then enrichments
