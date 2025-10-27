-- Migration 004: Create organizations table
-- Organizations represent clients/media outlets with multiple input channels

CREATE TABLE IF NOT EXISTS organizations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  slug VARCHAR(100) UNIQUE NOT NULL,
  name VARCHAR(255) NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  is_active BOOLEAN DEFAULT true,

  -- Channel configuration (flexible JSONB for different source types)
  -- Example: {"email": {"addresses": ["news@org.com"], "enabled": true}}
  channels JSONB DEFAULT '{}',

  -- Processing settings
  -- Example: {"language": "es", "store_in_qdrant": false}
  settings JSONB DEFAULT '{}'
);

-- Constraint: slug validation (alphanumeric, hyphens, dots only)
ALTER TABLE organizations ADD CONSTRAINT slug_format
  CHECK (slug ~ '^[a-zA-Z0-9\-\.]+$');

-- Constraint: slug length
ALTER TABLE organizations ADD CONSTRAINT slug_length
  CHECK (char_length(slug) >= 3 AND char_length(slug) <= 100);

-- Indexes
CREATE INDEX idx_organizations_slug ON organizations(slug);
CREATE INDEX idx_organizations_is_active ON organizations(is_active);

-- GIN index for channels JSONB queries
CREATE INDEX idx_organizations_channels ON organizations USING gin(channels);

-- Comments
COMMENT ON TABLE organizations IS 'Organizations with multiple content input channels';
COMMENT ON COLUMN organizations.slug IS 'URL-safe identifier (3-100 chars, alphanumeric + hyphen + dot)';
COMMENT ON COLUMN organizations.channels IS 'JSONB config for email, webhook, file, API sources';
COMMENT ON COLUMN organizations.settings IS 'JSONB processing settings (language, storage, etc.)';
