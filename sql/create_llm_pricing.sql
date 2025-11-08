-- LLM Model Pricing Table
-- Stores pricing information for all LLM models across providers

CREATE TABLE IF NOT EXISTS llm_model_pricing (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Model identification
    provider VARCHAR(50) NOT NULL,  -- 'openrouter', 'groq', 'anthropic'
    model_name VARCHAR(100) NOT NULL,  -- 'claude-3.5-sonnet-20241022'
    model_alias VARCHAR(50),  -- 'sonnet_premium', 'groq_fast'
    
    -- Pricing (USD per million tokens)
    price_input_per_mtok DECIMAL(10, 4) NOT NULL,  -- $3.00
    price_output_per_mtok DECIMAL(10, 4) NOT NULL,  -- $15.00
    
    -- Model capabilities
    context_window INTEGER,  -- 200000
    max_output_tokens INTEGER,  -- 4096
    
    -- Validity period
    effective_from TIMESTAMPTZ DEFAULT NOW(),
    effective_until TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(provider, model_name, effective_from)
);

-- Index for fast active pricing lookups (simplified - no NOW() in predicate)
CREATE INDEX IF NOT EXISTS idx_llm_pricing_active ON llm_model_pricing(provider, model_name) 
WHERE is_active = TRUE AND effective_until IS NULL;

-- Initial pricing data
INSERT INTO llm_model_pricing (provider, model_name, model_alias, price_input_per_mtok, price_output_per_mtok, context_window, max_output_tokens) VALUES
-- OpenRouter Models
('openrouter', 'anthropic/claude-3.5-sonnet-20241022', 'sonnet_premium', 3.00, 15.00, 200000, 8192),
('openrouter', 'openai/gpt-4o-mini', 'fast', 0.15, 0.60, 128000, 16384),

-- Groq Models
('groq', 'mixtral-8x7b-32768', 'groq_fast', 0.24, 0.24, 32768, 4096),
('groq', 'llama3-70b-8192', 'groq_writer', 0.59, 0.79, 8192, 4096)

ON CONFLICT (provider, model_name, effective_from) DO NOTHING;

-- Update llm_usage table to include cost tracking
ALTER TABLE llm_usage ADD COLUMN IF NOT EXISTS provider VARCHAR(50);
ALTER TABLE llm_usage ADD COLUMN IF NOT EXISTS pricing_id UUID REFERENCES llm_model_pricing(id);

-- Index for cost analysis queries
CREATE INDEX IF NOT EXISTS idx_usage_cost ON llm_usage(organization_id, timestamp, total_cost_usd);

-- Comments
COMMENT ON TABLE llm_model_pricing IS 'Pricing information for LLM models across providers';
COMMENT ON COLUMN llm_model_pricing.price_input_per_mtok IS 'Price in USD per million input tokens';
COMMENT ON COLUMN llm_model_pricing.price_output_per_mtok IS 'Price in USD per million output tokens';
COMMENT ON COLUMN llm_model_pricing.effective_from IS 'When this pricing becomes effective';
COMMENT ON COLUMN llm_model_pricing.effective_until IS 'When this pricing expires (NULL = current)';
