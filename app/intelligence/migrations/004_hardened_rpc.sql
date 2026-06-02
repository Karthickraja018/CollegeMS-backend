-- =============================================================================
-- AGENT INTELLIGENCE LAYER — Migration 004
-- RPC Functions for Metrics and Versioning (Phases 4, 8)
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- RPC 1: search_metrics (Phase 8: Metric-Aware Retrieval)
-- Returns top-K metrics by name similarity or keyword match (using ilike for now)
-- ─────────────────────────────────────────────────────────────────────────────
-- Ideally metrics would have embeddings, but for now we can match via ilike 
-- or we can search entities and pull their metrics. 
-- Let's create a direct metric retrieval function.

CREATE OR REPLACE FUNCTION search_metrics_by_keyword(
    keyword         TEXT,
    match_count     INTEGER  DEFAULT 5
)
RETURNS TABLE (
    metric_id       INTEGER,
    metric_name     VARCHAR(100),
    description     TEXT,
    formula         TEXT,
    entity_name     VARCHAR(100),
    aggregation_type VARCHAR(50),
    unit            VARCHAR(50),
    version         INTEGER
)
LANGUAGE sql STABLE
AS $$
    SELECT
        sm.id               AS metric_id,
        sm.metric_name,
        sm.description,
        sm.formula,
        sm.entity_name,
        sm.aggregation_type,
        sm.unit,
        sm.version
    FROM semantic_metrics sm
    WHERE sm.metric_name ILIKE '%' || keyword || '%'
       OR sm.description ILIKE '%' || keyword || '%'
    LIMIT match_count;
$$;

-- ─────────────────────────────────────────────────────────────────────────────
-- UPDATED RPC: get_intelligence_status (Phase 15 Monitoring & Versioning)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION get_intelligence_status()
RETURNS TABLE (
    metric  TEXT,
    value   BIGINT
)
LANGUAGE sql STABLE
AS $$
    SELECT 'semantic_entities'::TEXT,         COUNT(*)::BIGINT FROM semantic_entities WHERE is_active = TRUE
    UNION ALL
    SELECT 'semantic_attributes'::TEXT,       COUNT(*)::BIGINT FROM semantic_attributes
    UNION ALL
    SELECT 'semantic_relationships'::TEXT,    COUNT(*)::BIGINT FROM semantic_relationships
    UNION ALL
    SELECT 'academic_terminology'::TEXT,      COUNT(*)::BIGINT FROM academic_terminology WHERE is_active = TRUE
    UNION ALL
    SELECT 'query_examples'::TEXT,            COUNT(*)::BIGINT FROM query_examples WHERE success = TRUE
    UNION ALL
    SELECT 'entity_embeddings'::TEXT,         COUNT(*)::BIGINT FROM entity_embeddings WHERE embedding IS NOT NULL
    UNION ALL
    SELECT 'terminology_embeddings'::TEXT,    COUNT(*)::BIGINT FROM terminology_embeddings WHERE embedding IS NOT NULL
    UNION ALL
    SELECT 'query_embeddings'::TEXT,          COUNT(*)::BIGINT FROM query_embeddings WHERE embedding IS NOT NULL
    UNION ALL
    SELECT 'semantic_metrics'::TEXT,          COUNT(*)::BIGINT FROM semantic_metrics
    UNION ALL
    SELECT 'context_packs'::TEXT,             COUNT(*)::BIGINT FROM context_packs
    UNION ALL
    SELECT 'embedding_jobs_pending'::TEXT,    COUNT(*)::BIGINT FROM embedding_jobs WHERE status = 'PENDING';
$$;
