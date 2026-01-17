-- Migration: 012_mcp_oauth
-- Description: Create tables for MCP OAuth 2.1 authentication
-- Date: 2026-01-17

-- ============================================
-- Table: mcp_oauth_clients (Dynamic Client Registration)
-- ============================================
-- Stores clients registered via DCR endpoint
-- Each client is associated with a company for multi-tenancy

CREATE TABLE IF NOT EXISTS mcp_oauth_clients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id VARCHAR(64) UNIQUE NOT NULL,
    client_secret_hash VARCHAR(255),  -- bcrypt hash of client_secret (NULL for public clients)
    client_name VARCHAR(255) NOT NULL,
    redirect_uris TEXT[] NOT NULL,
    grant_types TEXT[] DEFAULT ARRAY['authorization_code', 'refresh_token'],
    scope VARCHAR(500) DEFAULT 'mcp:read mcp:write',
    company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Index for client_id lookups (most common query)
CREATE INDEX IF NOT EXISTS idx_mcp_oauth_clients_client_id ON mcp_oauth_clients(client_id);
CREATE INDEX IF NOT EXISTS idx_mcp_oauth_clients_company_id ON mcp_oauth_clients(company_id);

-- ============================================
-- Table: mcp_oauth_codes (Authorization Codes)
-- ============================================
-- Temporary codes generated during authorization flow
-- Short-lived (10 minutes), single-use

CREATE TABLE IF NOT EXISTS mcp_oauth_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(128) UNIQUE NOT NULL,  -- Opaque random code
    client_id VARCHAR(64) NOT NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    code_challenge VARCHAR(128) NOT NULL,  -- PKCE code_challenge
    code_challenge_method VARCHAR(10) DEFAULT 'S256',  -- Only S256 supported
    scope VARCHAR(500),
    redirect_uri TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,  -- Set when code is exchanged for token (prevents replay)
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Index for code lookup during token exchange
CREATE INDEX IF NOT EXISTS idx_mcp_oauth_codes_code ON mcp_oauth_codes(code);
-- Index for cleanup of expired codes
CREATE INDEX IF NOT EXISTS idx_mcp_oauth_codes_expires_at ON mcp_oauth_codes(expires_at);

-- ============================================
-- Table: mcp_oauth_tokens (Access & Refresh Tokens)
-- ============================================
-- Active tokens for authenticated MCP access
-- Access tokens: 1 hour, Refresh tokens: 30 days

CREATE TABLE IF NOT EXISTS mcp_oauth_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    access_token_hash VARCHAR(255) UNIQUE NOT NULL,  -- SHA256 hash
    refresh_token_hash VARCHAR(255) UNIQUE,  -- SHA256 hash (NULL if no refresh)
    client_id VARCHAR(64) NOT NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    scope VARCHAR(500),
    access_token_expires_at TIMESTAMPTZ NOT NULL,
    refresh_token_expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,  -- Set to revoke token
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Index for token lookup (most common operation)
CREATE INDEX IF NOT EXISTS idx_mcp_oauth_tokens_access_token ON mcp_oauth_tokens(access_token_hash);
CREATE INDEX IF NOT EXISTS idx_mcp_oauth_tokens_refresh_token ON mcp_oauth_tokens(refresh_token_hash);
-- Index for user's active tokens
CREATE INDEX IF NOT EXISTS idx_mcp_oauth_tokens_user_id ON mcp_oauth_tokens(user_id);
-- Index for cleanup of expired tokens
CREATE INDEX IF NOT EXISTS idx_mcp_oauth_tokens_expires_at ON mcp_oauth_tokens(access_token_expires_at);

-- ============================================
-- Row Level Security (RLS) Policies
-- ============================================
-- Note: These tables are accessed by the service role key,
-- so RLS is primarily for defense-in-depth

ALTER TABLE mcp_oauth_clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE mcp_oauth_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE mcp_oauth_tokens ENABLE ROW LEVEL SECURITY;

-- Service role can do everything
CREATE POLICY mcp_oauth_clients_service_policy ON mcp_oauth_clients
    FOR ALL
    USING (true)
    WITH CHECK (true);

CREATE POLICY mcp_oauth_codes_service_policy ON mcp_oauth_codes
    FOR ALL
    USING (true)
    WITH CHECK (true);

CREATE POLICY mcp_oauth_tokens_service_policy ON mcp_oauth_tokens
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- ============================================
-- Cleanup function for expired data
-- ============================================
-- Call this periodically to clean up expired codes and tokens

CREATE OR REPLACE FUNCTION cleanup_mcp_oauth_expired()
RETURNS void AS $$
BEGIN
    -- Delete expired authorization codes (older than 1 hour past expiry)
    DELETE FROM mcp_oauth_codes
    WHERE expires_at < NOW() - INTERVAL '1 hour';

    -- Delete expired tokens (older than 1 day past expiry)
    DELETE FROM mcp_oauth_tokens
    WHERE access_token_expires_at < NOW() - INTERVAL '1 day'
      AND (refresh_token_expires_at IS NULL OR refresh_token_expires_at < NOW() - INTERVAL '1 day');

    -- Note: We keep revoked tokens for audit purposes
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================
-- Comments for documentation
-- ============================================
COMMENT ON TABLE mcp_oauth_clients IS 'OAuth 2.1 clients registered via Dynamic Client Registration for MCP access';
COMMENT ON TABLE mcp_oauth_codes IS 'Temporary authorization codes for OAuth 2.1 PKCE flow';
COMMENT ON TABLE mcp_oauth_tokens IS 'Active access and refresh tokens for MCP authentication';
COMMENT ON FUNCTION cleanup_mcp_oauth_expired IS 'Cleanup expired OAuth codes and tokens. Run periodically via scheduler.';
