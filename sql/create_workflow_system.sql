-- Workflow configuration and usage tracking system
-- Simple approach: limits per tier defined at workflow registration

-- ============================================
-- WORKFLOW_CONFIGS TABLE
-- ============================================
-- Configuration for each workflow type
CREATE TABLE IF NOT EXISTS workflow_configs (
    workflow_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Workflow identification
    workflow_code VARCHAR(50) NOT NULL UNIQUE, -- e.g., 'micro_edit', 'analyze', 'redact_news'
    workflow_name TEXT NOT NULL,
    description TEXT,
    
    -- API endpoint (if exposed via API)
    api_endpoint TEXT, -- e.g., '/api/process/micro-edit'
    is_api_enabled BOOLEAN DEFAULT FALSE,
    
    -- Usage limits per tier (simple approach)
    limits_starter JSONB DEFAULT '{"monthly": 1000, "daily": 50}'::JSONB,
    limits_pro JSONB DEFAULT '{"monthly": 5000, "daily": 200}'::JSONB,
    
    -- Defaults for unlimited usage prevention
    default_monthly_limit INTEGER DEFAULT 100,
    default_daily_limit INTEGER DEFAULT 10,
    
    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- WORKFLOW_USAGE TABLE
-- ============================================
-- Track usage per company per workflow
CREATE TABLE IF NOT EXISTS workflow_usage (
    usage_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- References
    company_id UUID NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    workflow_id UUID NOT NULL REFERENCES workflow_configs(workflow_id) ON DELETE CASCADE,
    client_id UUID REFERENCES clients(client_id) ON DELETE SET NULL,
    
    -- Usage data
    execution_date DATE NOT NULL DEFAULT CURRENT_DATE,
    execution_count INTEGER DEFAULT 1,
    
    -- Constraints
    UNIQUE(company_id, workflow_id, execution_date)
);

-- ============================================
-- INDEXES
-- ============================================
CREATE INDEX IF NOT EXISTS idx_workflow_configs_code ON workflow_configs(workflow_code);
CREATE INDEX IF NOT EXISTS idx_workflow_configs_api ON workflow_configs(api_endpoint) WHERE is_api_enabled = TRUE;

CREATE INDEX IF NOT EXISTS idx_workflow_usage_company ON workflow_usage(company_id);
CREATE INDEX IF NOT EXISTS idx_workflow_usage_workflow ON workflow_usage(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_usage_date ON workflow_usage(execution_date);
CREATE INDEX IF NOT EXISTS idx_workflow_usage_company_date ON workflow_usage(company_id, execution_date);

-- ============================================
-- FUNCTIONS
-- ============================================

-- Update trigger for workflow_configs
CREATE TRIGGER update_workflow_configs_updated_at BEFORE UPDATE ON workflow_configs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Function to check workflow usage limits
CREATE OR REPLACE FUNCTION check_workflow_usage_limit(
    p_company_id UUID,
    p_workflow_code TEXT,
    p_tier TEXT DEFAULT 'starter'
) RETURNS JSONB AS $$
DECLARE
    config_record RECORD;
    monthly_usage INTEGER;
    daily_usage INTEGER;
    monthly_limit INTEGER;
    daily_limit INTEGER;
    result JSONB;
BEGIN
    -- Get workflow config
    SELECT * INTO config_record
    FROM workflow_configs 
    WHERE workflow_code = p_workflow_code AND is_active = TRUE;
    
    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'allowed', false,
            'error', 'Workflow not found or inactive'
        );
    END IF;
    
    -- Extract limits based on tier
    IF p_tier = 'pro' THEN
        monthly_limit := COALESCE((config_record.limits_pro->>'monthly')::INTEGER, config_record.default_monthly_limit);
        daily_limit := COALESCE((config_record.limits_pro->>'daily')::INTEGER, config_record.default_daily_limit);
    ELSE
        monthly_limit := COALESCE((config_record.limits_starter->>'monthly')::INTEGER, config_record.default_monthly_limit);
        daily_limit := COALESCE((config_record.limits_starter->>'daily')::INTEGER, config_record.default_daily_limit);
    END IF;
    
    -- Get current usage
    SELECT COALESCE(SUM(execution_count), 0) INTO monthly_usage
    FROM workflow_usage wu
    WHERE wu.company_id = p_company_id 
        AND wu.workflow_id = config_record.workflow_id
        AND wu.execution_date >= (CURRENT_DATE - INTERVAL '30 days');
    
    SELECT COALESCE(SUM(execution_count), 0) INTO daily_usage
    FROM workflow_usage wu
    WHERE wu.company_id = p_company_id 
        AND wu.workflow_id = config_record.workflow_id
        AND wu.execution_date = CURRENT_DATE;
    
    -- Check limits
    IF daily_usage >= daily_limit THEN
        RETURN jsonb_build_object(
            'allowed', false,
            'error', 'Daily limit exceeded',
            'daily_usage', daily_usage,
            'daily_limit', daily_limit
        );
    END IF;
    
    IF monthly_usage >= monthly_limit THEN
        RETURN jsonb_build_object(
            'allowed', false,
            'error', 'Monthly limit exceeded',
            'monthly_usage', monthly_usage,
            'monthly_limit', monthly_limit
        );
    END IF;
    
    -- Return success with usage info
    RETURN jsonb_build_object(
        'allowed', true,
        'daily_usage', daily_usage,
        'daily_limit', daily_limit,
        'monthly_usage', monthly_usage,
        'monthly_limit', monthly_limit
    );
END;
$$ LANGUAGE plpgsql;

-- Function to record workflow usage
CREATE OR REPLACE FUNCTION record_workflow_usage(
    p_company_id UUID,
    p_workflow_code TEXT,
    p_client_id UUID DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    workflow_id_var UUID;
BEGIN
    -- Get workflow ID
    SELECT workflow_id INTO workflow_id_var
    FROM workflow_configs 
    WHERE workflow_code = p_workflow_code AND is_active = TRUE;
    
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;
    
    -- Insert or update usage
    INSERT INTO workflow_usage (company_id, workflow_id, client_id, execution_date, execution_count)
    VALUES (p_company_id, workflow_id_var, p_client_id, CURRENT_DATE, 1)
    ON CONFLICT (company_id, workflow_id, execution_date)
    DO UPDATE SET 
        execution_count = workflow_usage.execution_count + 1,
        client_id = COALESCE(EXCLUDED.client_id, workflow_usage.client_id);
    
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- SEED DATA
-- ============================================
-- Insert basic workflow configurations
INSERT INTO workflow_configs (workflow_code, workflow_name, description, api_endpoint, is_api_enabled, limits_starter, limits_pro) 
VALUES 
    ('micro_edit', 'Micro Edit', 'Text micro-editing with LLM', '/api/process/micro-edit', TRUE, 
     '{"monthly": 500, "daily": 25}', '{"monthly": 2000, "daily": 100}'),
    
    ('analyze', 'Text Analysis', 'Extract title, summary, tags from text', '/process/analyze', TRUE,
     '{"monthly": 1000, "daily": 50}', '{"monthly": 5000, "daily": 200}'),
     
    ('analyze_atomic', 'Atomic Analysis', 'Extract atomic facts from text', '/process/analyze-atomic', TRUE,
     '{"monthly": 500, "daily": 25}', '{"monthly": 2000, "daily": 100}'),
     
    ('redact_news', 'News Generation', 'Generate news articles from facts', '/process/redact-news', TRUE,
     '{"monthly": 200, "daily": 10}', '{"monthly": 1000, "daily": 50}'),
     
    ('style_generation', 'Style Guide Generation', 'Generate writing style guides', '/styles/generate', TRUE,
     '{"monthly": 10, "daily": 2}', '{"monthly": 50, "daily": 5}')
ON CONFLICT (workflow_code) DO NOTHING;

-- ============================================
-- COMMENTS
-- ============================================
COMMENT ON TABLE workflow_configs IS 'Configuration and limits for each workflow type';
COMMENT ON TABLE workflow_usage IS 'Daily usage tracking per company per workflow';

COMMENT ON COLUMN workflow_configs.limits_starter IS 'Usage limits for starter tier (monthly/daily)';
COMMENT ON COLUMN workflow_configs.limits_pro IS 'Usage limits for pro tier (monthly/daily)';
COMMENT ON COLUMN workflow_configs.default_monthly_limit IS 'Fallback limit if tier limits not defined';
COMMENT ON FUNCTION check_workflow_usage_limit IS 'Check if company can execute workflow based on usage limits';
COMMENT ON FUNCTION record_workflow_usage IS 'Record workflow execution for usage tracking';