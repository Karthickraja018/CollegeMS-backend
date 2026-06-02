-- =============================================================================
-- AGENT INTELLIGENCE LAYER — Migration 003
-- Hardening & Production Readiness (Phases 2, 3, 4, 5, 9, 10, 12, 14, 6, 15)
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- PHASE 2: ADD SEMANTIC METRICS REGISTRY
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS semantic_metrics (
    id              SERIAL PRIMARY KEY,
    metric_name     VARCHAR(100)    NOT NULL UNIQUE,
    description     TEXT            NOT NULL,
    formula         TEXT            NOT NULL,
    entity_name     VARCHAR(100)    NOT NULL, -- logical connection to an entity
    aggregation_type VARCHAR(50)    NOT NULL, -- SUM, AVG, COUNT, PERCENTAGE
    unit            VARCHAR(50),              -- %, days, absolute
    version         INTEGER         NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_semantic_metrics_name ON semantic_metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_semantic_metrics_entity ON semantic_metrics(entity_name);

-- ─────────────────────────────────────────────────────────────────────────────
-- PHASE 3: ADD CONTEXT PACKS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS context_packs (
    id              SERIAL PRIMARY KEY,
    entity_name     VARCHAR(100)    NOT NULL UNIQUE,
    context_json    JSONB           NOT NULL,
    version         INTEGER         NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_context_packs_entity ON context_packs(entity_name);

-- ─────────────────────────────────────────────────────────────────────────────
-- PHASE 4: CONTEXT VERSIONING
-- ─────────────────────────────────────────────────────────────────────────────

-- Add versions to entity_embeddings
ALTER TABLE entity_embeddings
ADD COLUMN IF NOT EXISTS context_version INTEGER NOT NULL DEFAULT 1,
ADD COLUMN IF NOT EXISTS embedding_version INTEGER NOT NULL DEFAULT 1,
ADD COLUMN IF NOT EXISTS schema_version INTEGER NOT NULL DEFAULT 1;

-- Add versions to terminology_embeddings
ALTER TABLE terminology_embeddings
ADD COLUMN IF NOT EXISTS context_version INTEGER NOT NULL DEFAULT 1,
ADD COLUMN IF NOT EXISTS embedding_version INTEGER NOT NULL DEFAULT 1,
ADD COLUMN IF NOT EXISTS schema_version INTEGER NOT NULL DEFAULT 1;

-- Add versions to query_embeddings
ALTER TABLE query_embeddings
ADD COLUMN IF NOT EXISTS context_version INTEGER NOT NULL DEFAULT 1,
ADD COLUMN IF NOT EXISTS embedding_version INTEGER NOT NULL DEFAULT 1,
ADD COLUMN IF NOT EXISTS schema_version INTEGER NOT NULL DEFAULT 1;

-- Add versions to context_registry
ALTER TABLE context_registry
ADD COLUMN IF NOT EXISTS schema_version INTEGER NOT NULL DEFAULT 1;

-- ─────────────────────────────────────────────────────────────────────────────
-- PHASE 5: EMBEDDING REFRESH QUEUE
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS embedding_jobs (
    id              SERIAL PRIMARY KEY,
    entity_type     VARCHAR(50)     NOT NULL, -- entity, terminology, query, metric
    entity_id       INTEGER         NOT NULL,
    job_type        VARCHAR(50)     NOT NULL DEFAULT 'INSERT', -- INSERT, UPDATE, DELETE
    status          VARCHAR(50)     NOT NULL DEFAULT 'PENDING', -- PENDING, PROCESSING, COMPLETED, FAILED
    attempts        INTEGER         NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_embedding_jobs_status ON embedding_jobs(status);

-- ─────────────────────────────────────────────────────────────────────────────
-- PHASE 9: QUERY CONTEXT OBSERVABILITY
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS context_retrieval_logs (
    id                  SERIAL PRIMARY KEY,
    question            TEXT            NOT NULL,
    retrieved_entities  JSONB           NOT NULL DEFAULT '[]',
    retrieved_metrics   JSONB           NOT NULL DEFAULT '[]',
    retrieved_relationships JSONB       NOT NULL DEFAULT '[]',
    similarity_scores   JSONB           NOT NULL DEFAULT '{}',
    execution_result    TEXT,           -- Success/Fail status
    execution_time_ms   INTEGER,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- PHASE 10: QUERY MEMORY IMPROVEMENTS
-- ─────────────────────────────────────────────────────────────────────────────

-- Query memory (query_examples) already has:
-- question, generated_sql, result_summary, entities_used, metrics_used, tables_used, exec_time_ms, feedback_score
-- We just need to ensure embedding_version exists
ALTER TABLE query_examples
ADD COLUMN IF NOT EXISTS embedding_version INTEGER NOT NULL DEFAULT 1,
ADD COLUMN IF NOT EXISTS relationships_used JSONB NOT NULL DEFAULT '[]';

-- ─────────────────────────────────────────────────────────────────────────────
-- PHASE 12: DATASET SEMANTIC COVERAGE
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS dataset_semantic_profiles (
    id                  SERIAL PRIMARY KEY,
    dataset             VARCHAR(100)    NOT NULL UNIQUE,
    mapped_fields       INTEGER         NOT NULL DEFAULT 0,
    total_fields        INTEGER         NOT NULL DEFAULT 0,
    coverage_score      NUMERIC(3,2)    NOT NULL DEFAULT 0.00,
    relationship_score  NUMERIC(3,2)    NOT NULL DEFAULT 0.00,
    metric_score        NUMERIC(3,2)    NOT NULL DEFAULT 0.00,
    quality_score       NUMERIC(3,2)    NOT NULL DEFAULT 0.00,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- PHASE 14: SUPABASE SECURITY (RLS)
-- ─────────────────────────────────────────────────────────────────────────────

-- Enable RLS
ALTER TABLE semantic_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE semantic_attributes ENABLE ROW LEVEL SECURITY;
ALTER TABLE semantic_relationships ENABLE ROW LEVEL SECURITY;
ALTER TABLE semantic_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE query_examples ENABLE ROW LEVEL SECURITY;
ALTER TABLE query_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE context_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE context_packs ENABLE ROW LEVEL SECURITY;
ALTER TABLE embedding_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE dataset_semantic_profiles ENABLE ROW LEVEL SECURITY;

-- Create basic admin policies
CREATE POLICY admin_all_entities ON semantic_entities AS PERMISSIVE FOR ALL TO authenticated USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY admin_all_attributes ON semantic_attributes AS PERMISSIVE FOR ALL TO authenticated USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY admin_all_relationships ON semantic_relationships AS PERMISSIVE FOR ALL TO authenticated USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY admin_all_metrics ON semantic_metrics AS PERMISSIVE FOR ALL TO authenticated USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY admin_all_query_ex ON query_examples AS PERMISSIVE FOR ALL TO authenticated USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY admin_all_query_fb ON query_feedback AS PERMISSIVE FOR ALL TO authenticated USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY admin_all_context_reg ON context_registry AS PERMISSIVE FOR ALL TO authenticated USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY admin_all_context_packs ON context_packs AS PERMISSIVE FOR ALL TO authenticated USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY admin_all_jobs ON embedding_jobs AS PERMISSIVE FOR ALL TO authenticated USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY admin_all_profiles ON dataset_semantic_profiles AS PERMISSIVE FOR ALL TO authenticated USING (TRUE) WITH CHECK (TRUE);

-- ─────────────────────────────────────────────────────────────────────────────
-- PHASE 6: LIVE UPDATE PIPELINE (Triggers)
-- ─────────────────────────────────────────────────────────────────────────────

-- Trigger function to enqueue an embedding job
CREATE OR REPLACE FUNCTION enqueue_embedding_job()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_TABLE_NAME = 'semantic_entities' THEN
        INSERT INTO embedding_jobs (entity_type, entity_id, job_type)
        VALUES ('entity', NEW.id, TG_OP);
    ELSIF TG_TABLE_NAME = 'academic_terminology' THEN
        INSERT INTO embedding_jobs (entity_type, entity_id, job_type)
        VALUES ('terminology', NEW.id, TG_OP);
    ELSIF TG_TABLE_NAME = 'query_examples' THEN
        INSERT INTO embedding_jobs (entity_type, entity_id, job_type)
        VALUES ('query', NEW.id, TG_OP);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply triggers
DROP TRIGGER IF EXISTS trg_semantic_entities_embedding ON semantic_entities;
CREATE TRIGGER trg_semantic_entities_embedding
AFTER INSERT OR UPDATE ON semantic_entities
FOR EACH ROW EXECUTE FUNCTION enqueue_embedding_job();

DROP TRIGGER IF EXISTS trg_academic_terminology_embedding ON academic_terminology;
CREATE TRIGGER trg_academic_terminology_embedding
AFTER INSERT OR UPDATE ON academic_terminology
FOR EACH ROW EXECUTE FUNCTION enqueue_embedding_job();

DROP TRIGGER IF EXISTS trg_query_examples_embedding ON query_examples;
CREATE TRIGGER trg_query_examples_embedding
AFTER INSERT OR UPDATE ON query_examples
FOR EACH ROW EXECUTE FUNCTION enqueue_embedding_job();

-- ─────────────────────────────────────────────────────────────────────────────
-- PHASE 15: PERFORMANCE OPTIMIZATION (Materialized Views)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_semantic_entities_attributes AS
SELECT 
    se.id AS entity_id,
    se.entity_name,
    se.primary_table,
    jsonb_agg(jsonb_build_object(
        'attribute_name', sa.attribute_name,
        'description', sa.description,
        'data_type', sa.data_type,
        'is_metric', sa.is_metric
    )) AS attributes_list
FROM semantic_entities se
LEFT JOIN semantic_attributes sa ON sa.entity_id = se.id
GROUP BY se.id, se.entity_name, se.primary_table;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_semantic_ent_attr ON mv_semantic_entities_attributes(entity_id);
