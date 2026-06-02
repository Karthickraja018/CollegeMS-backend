-- =============================================================================
-- AGENT INTELLIGENCE LAYER — Migration 002
-- RPC Functions for Semantic Similarity Search
-- Run after 001_vector_extension.sql
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- RPC 1: search_entities
-- Returns top-K semantic entities by cosine similarity
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION search_entities(
    query_embedding vector(768),
    match_count     INTEGER  DEFAULT 10,
    threshold       FLOAT    DEFAULT 0.60
)
RETURNS TABLE (
    entity_id       INTEGER,
    entity_name     VARCHAR(100),
    description     TEXT,
    primary_table   VARCHAR(100),
    join_key        VARCHAR(100),
    aliases         JSONB,
    attributes      JSONB,
    business_rules  JSONB,
    similarity      FLOAT
)
LANGUAGE sql STABLE
AS $$
    SELECT
        se.id               AS entity_id,
        se.entity_name,
        se.description,
        se.primary_table,
        se.join_key,
        se.aliases,
        se.attributes,
        se.business_rules,
        1 - (ee.embedding <=> query_embedding) AS similarity
    FROM entity_embeddings ee
    JOIN semantic_entities se ON se.id = ee.entity_id
    WHERE se.is_active = TRUE
      AND ee.embedding IS NOT NULL
      AND 1 - (ee.embedding <=> query_embedding) >= threshold
    ORDER BY ee.embedding <=> query_embedding
    LIMIT match_count;
$$;

-- ─────────────────────────────────────────────────────────────────────────────
-- RPC 2: search_terminology
-- Returns top-K academic terms by cosine similarity
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION search_terminology(
    query_embedding vector(768),
    match_count     INTEGER  DEFAULT 8,
    threshold       FLOAT    DEFAULT 0.55
)
RETURNS TABLE (
    term_id         INTEGER,
    term            VARCHAR(100),
    full_form       VARCHAR(255),
    definition      TEXT,
    category        VARCHAR(50),
    db_mapping      VARCHAR(255),
    db_table        VARCHAR(100),
    aliases         JSONB,
    similarity      FLOAT
)
LANGUAGE sql STABLE
AS $$
    SELECT
        at.id               AS term_id,
        at.term,
        at.full_form,
        at.definition,
        at.category,
        at.db_mapping,
        at.db_table,
        at.aliases,
        1 - (te.embedding <=> query_embedding) AS similarity
    FROM terminology_embeddings te
    JOIN academic_terminology at ON at.id = te.term_id
    WHERE at.is_active = TRUE
      AND te.embedding IS NOT NULL
      AND 1 - (te.embedding <=> query_embedding) >= threshold
    ORDER BY te.embedding <=> query_embedding
    LIMIT match_count;
$$;

-- ─────────────────────────────────────────────────────────────────────────────
-- RPC 3: search_query_examples
-- Returns top-K successful past queries by cosine similarity
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION search_query_examples(
    query_embedding vector(768),
    match_count     INTEGER  DEFAULT 5,
    threshold       FLOAT    DEFAULT 0.60,
    require_success BOOLEAN  DEFAULT TRUE
)
RETURNS TABLE (
    query_id        INTEGER,
    question        TEXT,
    generated_sql   TEXT,
    result_summary  TEXT,
    entities_used   JSONB,
    metrics_used    JSONB,
    tables_used     JSONB,
    agent_used      VARCHAR(50),
    query_type      VARCHAR(50),
    feedback_score  NUMERIC(3,2),
    similarity      FLOAT
)
LANGUAGE sql STABLE
AS $$
    SELECT
        qe.id               AS query_id,
        qe.question,
        qe.generated_sql,
        qe.result_summary,
        qe.entities_used,
        qe.metrics_used,
        qe.tables_used,
        qe.agent_used,
        qe.query_type,
        qe.feedback_score,
        1 - (qemb.embedding <=> query_embedding) AS similarity
    FROM query_embeddings qemb
    JOIN query_examples qe ON qe.id = qemb.query_id
    WHERE qemb.embedding IS NOT NULL
      AND (NOT require_success OR qe.success = TRUE)
      AND 1 - (qemb.embedding <=> query_embedding) >= threshold
    ORDER BY qemb.embedding <=> query_embedding
    LIMIT match_count;
$$;

-- ─────────────────────────────────────────────────────────────────────────────
-- RPC 4: get_entity_relationships
-- Get all join paths for a given set of entity names
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION get_entity_relationships(
    entity_names TEXT[]
)
RETURNS TABLE (
    from_entity     VARCHAR(100),
    relationship    VARCHAR(50),
    to_entity       VARCHAR(100),
    join_sql        TEXT,
    description     TEXT,
    confidence      NUMERIC(3,2)
)
LANGUAGE sql STABLE
AS $$
    SELECT
        sr.from_entity,
        sr.relationship,
        sr.to_entity,
        sr.join_sql,
        sr.description,
        sr.confidence
    FROM semantic_relationships sr
    WHERE sr.from_entity = ANY(entity_names)
       OR sr.to_entity   = ANY(entity_names)
    ORDER BY sr.confidence DESC;
$$;

-- ─────────────────────────────────────────────────────────────────────────────
-- RPC 5: get_intelligence_status
-- Returns counts for monitoring
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
    SELECT 'query_embeddings'::TEXT,          COUNT(*)::BIGINT FROM query_embeddings WHERE embedding IS NOT NULL;
$$;
