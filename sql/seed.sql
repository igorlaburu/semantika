-- Seed data for testing semantika
-- Execute this AFTER schema.sql

-- ============================================
-- TEST CLIENT
-- ============================================
INSERT INTO clients (client_id, client_name, email, api_key, is_active, metadata)
VALUES (
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', -- Fixed UUID for testing
    'Test Client',
    'test@semantika.dev',
    'sk-test-' || encode(gen_random_bytes(20), 'hex'),
    TRUE,
    '{"tier": "dev", "max_tasks": 10}'::JSONB
)
ON CONFLICT (client_id) DO NOTHING;

-- ============================================
-- TEST TASKS
-- ============================================

-- Task 1: Web scraping with LLM
INSERT INTO tasks (task_id, client_id, source_type, target, frequency_min, is_active, config)
VALUES (
    uuid_generate_v4(),
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    'web_llm',
    'https://techcrunch.com/category/artificial-intelligence/',
    60, -- Every hour
    TRUE,
    '{"extract_multiple": true, "max_articles": 5}'::JSONB
)
ON CONFLICT DO NOTHING;

-- Task 2: Twitter monitoring
INSERT INTO tasks (task_id, client_id, source_type, target, frequency_min, is_active, config)
VALUES (
    uuid_generate_v4(),
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    'twitter',
    'artificial intelligence OR machine learning',
    30, -- Every 30 minutes
    TRUE,
    '{"max_results": 20, "lang": "en"}'::JSONB
)
ON CONFLICT DO NOTHING;

-- ============================================
-- TEST API CREDENTIALS
-- ============================================

-- ScraperTech credentials
INSERT INTO api_credentials (client_id, service_name, credentials)
VALUES (
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    'scraper_tech',
    '{"api_key": "YOUR_SCRAPERTECH_KEY", "endpoint": "https://api.scraper.tech"}'::JSONB
)
ON CONFLICT (client_id, service_name) DO UPDATE
SET credentials = EXCLUDED.credentials;

-- ============================================
-- VERIFY SEED DATA
-- ============================================

-- Display seeded client
DO $$
DECLARE
    test_client RECORD;
BEGIN
    SELECT client_id, client_name, api_key INTO test_client
    FROM clients
    WHERE client_id = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11';

    RAISE NOTICE 'Test Client Created:';
    RAISE NOTICE 'ID: %', test_client.client_id;
    RAISE NOTICE 'Name: %', test_client.client_name;
    RAISE NOTICE 'API Key: %', test_client.api_key;
END $$;

-- Count seeded tasks
DO $$
DECLARE
    task_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO task_count
    FROM tasks
    WHERE client_id = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11';

    RAISE NOTICE 'Tasks created: %', task_count;
END $$;
