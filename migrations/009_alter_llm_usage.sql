-- =====================================================================
-- Migration 009: Alter llm_usage table
-- =====================================================================
-- Add client_id column and make organization_id NOT NULL
-- =====================================================================

-- Add client_id column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='llm_usage' AND column_name='client_id'
    ) THEN
        ALTER TABLE llm_usage ADD COLUMN client_id UUID REFERENCES clients(id) ON DELETE SET NULL;
        CREATE INDEX idx_llm_usage_client ON llm_usage(client_id);
    END IF;
END $$;

-- Make organization_id NOT NULL if it isn't already
DO $$
BEGIN
    ALTER TABLE llm_usage ALTER COLUMN organization_id SET NOT NULL;
EXCEPTION
    WHEN others THEN
        -- Column might already be NOT NULL, ignore error
        NULL;
END $$;

-- Update comments
COMMENT ON COLUMN llm_usage.organization_id IS 'Organization (for billing - always present)';
COMMENT ON COLUMN llm_usage.client_id IS 'Client/API key used (if from API)';
