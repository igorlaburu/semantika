-- Migration 007: Link existing clients table to organizations
-- This maintains backward compatibility while adding organization support

ALTER TABLE clients ADD COLUMN organization_id UUID REFERENCES organizations(id);

CREATE INDEX idx_clients_org ON clients(organization_id);

COMMENT ON COLUMN clients.organization_id IS 'Optional: Link client (API key) to organization';
