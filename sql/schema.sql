-- Schema for semantika multi-tenant semantic data pipeline
-- Execute this in Supabase SQL Editor

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- CLIENTS TABLE
-- ============================================
-- Stores client information and API keys
CREATE TABLE IF NOT EXISTS clients (
    client_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_name TEXT NOT NULL,
    email TEXT UNIQUE,
    api_key TEXT UNIQUE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Metadata
    metadata JSONB DEFAULT '{}'::JSONB
);

-- Index for fast API key lookup
CREATE INDEX IF NOT EXISTS idx_clients_api_key ON clients(api_key);
CREATE INDEX IF NOT EXISTS idx_clients_is_active ON clients(is_active);

-- ============================================
-- TASKS TABLE
-- ============================================
-- Stores scheduled ingestion tasks
CREATE TABLE IF NOT EXISTS tasks (
    task_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,

    -- Task configuration
    source_type TEXT NOT NULL CHECK (source_type IN ('web_llm', 'twitter', 'api_efe', 'api_reuters', 'api_wordpress', 'manual')),
    target TEXT NOT NULL, -- URL, search query, or endpoint
    frequency_min INTEGER NOT NULL CHECK (frequency_min > 0), -- Frequency in minutes

    -- Task status
    is_active BOOLEAN DEFAULT TRUE,
    last_run_at TIMESTAMP WITH TIME ZONE,
    next_run_at TIMESTAMP WITH TIME ZONE,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Additional configuration
    config JSONB DEFAULT '{}'::JSONB
);

-- Indexes for task scheduling
CREATE INDEX IF NOT EXISTS idx_tasks_client_id ON tasks(client_id);
CREATE INDEX IF NOT EXISTS idx_tasks_is_active ON tasks(is_active);
CREATE INDEX IF NOT EXISTS idx_tasks_next_run ON tasks(next_run_at) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_tasks_source_type ON tasks(source_type);

-- ============================================
-- API_CREDENTIALS TABLE
-- ============================================
-- Stores external API credentials per client
CREATE TABLE IF NOT EXISTS api_credentials (
    credential_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,

    -- Service identification
    service_name TEXT NOT NULL, -- 'scraper_tech', 'api_efe', 'api_reuters', etc.

    -- Encrypted credentials
    credentials JSONB NOT NULL, -- Store API keys, tokens, etc.

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Unique constraint: one credential per service per client
    UNIQUE(client_id, service_name)
);

-- Index for credential lookup
CREATE INDEX IF NOT EXISTS idx_credentials_client_id ON api_credentials(client_id);
CREATE INDEX IF NOT EXISTS idx_credentials_service ON api_credentials(service_name);

-- ============================================
-- FUNCTIONS
-- ============================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers for updated_at
CREATE TRIGGER update_clients_updated_at BEFORE UPDATE ON clients
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tasks_updated_at BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_credentials_updated_at BEFORE UPDATE ON api_credentials
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- HELPER FUNCTIONS
-- ============================================

-- Function to generate API key (sk-xxxx format)
CREATE OR REPLACE FUNCTION generate_api_key()
RETURNS TEXT AS $$
DECLARE
    random_string TEXT;
BEGIN
    -- Generate random 40 character string
    random_string := encode(gen_random_bytes(20), 'hex');
    RETURN 'sk-' || random_string;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- COMMENTS
-- ============================================
COMMENT ON TABLE clients IS 'Multi-tenant client information with API keys';
COMMENT ON TABLE tasks IS 'Scheduled ingestion tasks per client';
COMMENT ON TABLE api_credentials IS 'External API credentials stored per client';

COMMENT ON COLUMN clients.api_key IS 'API key for authentication (format: sk-xxxx)';
COMMENT ON COLUMN tasks.source_type IS 'Type of data source to ingest from';
COMMENT ON COLUMN tasks.frequency_min IS 'How often to run this task (in minutes)';
COMMENT ON COLUMN tasks.config IS 'Additional configuration in JSON format';
COMMENT ON COLUMN api_credentials.credentials IS 'Encrypted API keys/tokens in JSON format';
