-- Migration 004: Create DFA Subsidies source for igor@gako.ai
-- Purpose: Setup automated monitoring of DFA forestry subsidies
-- Date: 2025-11-26

-- ================================================================
-- CREATE SOURCE: DFA Subsidies Monitor
-- ================================================================
-- Automated daily check of https://egoitza.araba.eus/es/-/tr-solicitar-ayudas-forestales
-- Detects changes, extracts subsidy information, downloads PDFs, generates reports

-- Insert source for DFA subsidies monitoring
INSERT INTO sources (
    id,
    company_id,
    source_type,
    source_name,
    is_active,
    
    -- Configuration
    config,
    
    -- Schedule configuration
    schedule_config,
    
    created_at
)
VALUES (
    gen_random_uuid(),
    
    -- company_id: gako.ai (igor@gako.ai)
    -- NOTE: Update this UUID with actual company_id from companies table
    (SELECT id FROM companies WHERE company_code = 'gako' LIMIT 1),
    
    -- Source type
    'dfa_subsidies',
    
    -- Source name
    'Subvenciones Forestales DFA',
    
    -- Active
    TRUE,
    
    -- Config: URL and extraction settings
    jsonb_build_object(
        'target_url', 'https://egoitza.araba.eus/es/-/tr-solicitar-ayudas-forestales',
        'description', 'Monitorización automática de subvenciones forestales de la Diputación Foral de Álava',
        
        -- Change detection config
        'change_detection', jsonb_build_object(
            'method', 'simhash',
            'simhash_threshold', 0.90,
            'check_before_processing', TRUE
        ),
        
        -- PDF extraction config
        'pdf_extraction', jsonb_build_object(
            'enabled', TRUE,
            'max_file_size_mb', 10,
            'timeout_seconds', 30,
            'extract_methods', jsonb_build_array('pypdf2', 'pdfplumber'),
            'summarize_with_llm', TRUE
        ),
        
        -- Report generation config
        'report_generation', jsonb_build_object(
            'format', 'markdown',
            'template', 'subsidy_detailed',
            'include_pdf_summaries', TRUE,
            'include_deadlines', TRUE,
            'include_documentation_links', TRUE
        ),
        
        -- LLM extraction config
        'llm_extraction', jsonb_build_object(
            'model', 'openrouter/meta-llama/llama-3.3-70b-instruct',
            'extract_fields', jsonb_build_array(
                'plazos',
                'documentacion_presentar', 
                'solicitudes_pago',
                'explicacion_general'
            )
        ),
        
        -- Notification config (optional)
        'notifications', jsonb_build_object(
            'enabled', TRUE,
            'notify_on_changes', TRUE,
            'recipients', jsonb_build_array('igor@gako.ai')
        )
    ),
    
    -- Schedule config: Daily at 08:00 UTC
    jsonb_build_object(
        'enabled', TRUE,
        'cron_expression', '0 8 * * *',
        'timezone', 'UTC',
        'description', 'Ejecución diaria a las 08:00 UTC (09:00 CET en invierno, 10:00 CEST en verano)',
        
        -- Alternative: explicit hour/minute for scheduler
        'schedule_type', 'cron',
        'hour', 8,
        'minute', 0,
        'day_of_week', '*',
        'day_of_month', '*',
        'month', '*'
    ),
    
    -- Created timestamp
    NOW()
)
ON CONFLICT (id) DO NOTHING;

-- ================================================================
-- VERIFICATION
-- ================================================================

-- Verify source was created
DO $$
DECLARE
    source_count INT;
    source_id_var UUID;
    company_name_var TEXT;
BEGIN
    SELECT COUNT(*), MAX(s.id), MAX(c.company_name)
    INTO source_count, source_id_var, company_name_var
    FROM sources s
    JOIN companies c ON s.company_id = c.id
    WHERE s.source_type = 'dfa_subsidies'
    AND s.source_name = 'Subvenciones Forestales DFA';
    
    IF source_count > 0 THEN
        RAISE NOTICE 'Source created successfully:';
        RAISE NOTICE '  - Source ID: %', source_id_var;
        RAISE NOTICE '  - Company: %', company_name_var;
        RAISE NOTICE '  - Schedule: Daily at 08:00 UTC';
    ELSE
        RAISE WARNING 'Source was not created. Check if company "gako" exists in companies table.';
    END IF;
END $$;

-- Show source details
SELECT 
    s.id as source_id,
    s.source_type,
    s.source_name,
    s.is_active,
    c.company_name,
    c.company_code,
    s.config->>'target_url' as target_url,
    s.schedule_config->>'cron_expression' as schedule,
    s.schedule_config->>'timezone' as timezone,
    s.created_at
FROM sources s
JOIN companies c ON s.company_id = c.id
WHERE s.source_type = 'dfa_subsidies'
ORDER BY s.created_at DESC
LIMIT 1;

-- ================================================================
-- NOTES
-- ================================================================

-- IMPORTANT: 
-- 1. Verify that company 'gako' exists before running this migration
-- 2. If company doesn't exist, create it first or update company_id in INSERT
-- 3. Schedule is 08:00 UTC = 09:00/10:00 local time in Spain (depending on DST)
-- 4. To change schedule, update schedule_config JSONB field
-- 5. To disable monitoring, set is_active = FALSE

-- Example: Update schedule to run at 09:00 UTC instead:
-- UPDATE sources 
-- SET schedule_config = jsonb_set(
--     schedule_config, 
--     '{hour}', 
--     '9'
-- )
-- WHERE source_type = 'dfa_subsidies';
