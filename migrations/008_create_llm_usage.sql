-- =====================================================================
-- Migration 008: LLM Usage Tracking
-- =====================================================================
-- Tracks token usage and costs for all LLM operations
-- =====================================================================

CREATE TABLE IF NOT EXISTS llm_usage (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  context_unit_id UUID REFERENCES context_units(id) ON DELETE SET NULL,

  -- Timing
  timestamp TIMESTAMP DEFAULT NOW(),

  -- Model and operation
  model VARCHAR(100) NOT NULL,              -- "anthropic/claude-3.5-sonnet", etc.
  operation VARCHAR(50) NOT NULL,           -- "context_unit", "article", "style"

  -- Token counts
  input_tokens INT NOT NULL DEFAULT 0,
  output_tokens INT NOT NULL DEFAULT 0,
  total_tokens INT NOT NULL DEFAULT 0,

  -- Costs (USD)
  input_cost_usd DECIMAL(10,6) DEFAULT 0,
  output_cost_usd DECIMAL(10,6) DEFAULT 0,
  total_cost_usd DECIMAL(10,6) DEFAULT 0,

  -- Metadata
  metadata JSONB DEFAULT '{}'               -- source_type, duration_ms, etc.
);

-- Indexes
CREATE INDEX idx_llm_usage_org ON llm_usage(organization_id);
CREATE INDEX idx_llm_usage_timestamp ON llm_usage(timestamp DESC);
CREATE INDEX idx_llm_usage_model ON llm_usage(model);
CREATE INDEX idx_llm_usage_operation ON llm_usage(operation);
CREATE INDEX idx_llm_usage_context_unit ON llm_usage(context_unit_id);

-- Comments
COMMENT ON TABLE llm_usage IS 'LLM token usage and cost tracking';
COMMENT ON COLUMN llm_usage.model IS 'Full model name from OpenRouter (e.g., anthropic/claude-3.5-sonnet)';
COMMENT ON COLUMN llm_usage.operation IS 'Type of operation: context_unit, article, style, etc.';
COMMENT ON COLUMN llm_usage.input_tokens IS 'Prompt tokens consumed';
COMMENT ON COLUMN llm_usage.output_tokens IS 'Completion tokens generated';
COMMENT ON COLUMN llm_usage.total_cost_usd IS 'Total cost in USD (input_cost + output_cost)';
COMMENT ON COLUMN llm_usage.metadata IS 'Additional data: source_type, duration, error, etc.';
