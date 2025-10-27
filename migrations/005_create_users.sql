-- Migration 005: Create users table
-- Users belong to organizations and can submit content

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email VARCHAR(255) UNIQUE NOT NULL,
  name VARCHAR(255),
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  role VARCHAR(50) DEFAULT 'member',
  created_at TIMESTAMP DEFAULT NOW(),
  is_active BOOLEAN DEFAULT true
);

-- Constraint: email format validation
ALTER TABLE users ADD CONSTRAINT email_format
  CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$');

-- Constraint: role validation
ALTER TABLE users ADD CONSTRAINT role_valid
  CHECK (role IN ('admin', 'editor', 'member'));

-- Indexes
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_org ON users(organization_id);
CREATE INDEX idx_users_is_active ON users(is_active);

-- Comments
COMMENT ON TABLE users IS 'Users associated with organizations';
COMMENT ON COLUMN users.role IS 'User role: admin, editor, or member';
COMMENT ON COLUMN users.organization_id IS 'Organization this user belongs to';
