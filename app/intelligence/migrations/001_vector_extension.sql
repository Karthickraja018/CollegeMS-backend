-- =============================================================================
-- AGENT INTELLIGENCE LAYER — Migration 001
-- Enable pgvector + Create Knowledge Store Tables
-- Run once on Supabase via SQL Editor (requires superuser for EXTENSION)
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 1: VECTOR EXTENSION
-- ─────────────────────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS vector;

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 2: SEMANTIC ENTITIES
-- Academic entities understood by all agents
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS semantic_entities (
    id              SERIAL PRIMARY KEY,
    entity_name     VARCHAR(100)    NOT NULL UNIQUE,
    description     TEXT            NOT NULL,
    primary_table   VARCHAR(100)    NOT NULL,       -- actual DB table name
    join_key        VARCHAR(100),                   -- primary key column
    aliases         JSONB           NOT NULL DEFAULT '[]',  -- ["student", "learner"]
    attributes      JSONB           NOT NULL DEFAULT '[]',  -- attribute name list
    business_rules  JSONB           NOT NULL DEFAULT '[]',  -- e.g. "attendance threshold is 75%"
    display_name    VARCHAR(100),
    version         INTEGER         NOT NULL DEFAULT 1,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_semantic_entities_name ON semantic_entities(entity_name);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 3: SEMANTIC ATTRIBUTES
-- Column-level metadata for all key fields
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS semantic_attributes (
    id              SERIAL PRIMARY KEY,
    entity_id       INTEGER         NOT NULL REFERENCES semantic_entities(id) ON DELETE CASCADE,
    attribute_name  VARCHAR(100)    NOT NULL,       -- db column name
    display_name    VARCHAR(100),
    description     TEXT            NOT NULL,
    data_type       VARCHAR(50),                    -- numeric, text, boolean, date, enum
    business_meaning TEXT,                          -- "Percentage of classes attended"
    aliases         JSONB           NOT NULL DEFAULT '[]',
    example_values  JSONB           NOT NULL DEFAULT '[]',
    is_metric       BOOLEAN         NOT NULL DEFAULT FALSE,
    is_filterable   BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (entity_id, attribute_name)
);

CREATE INDEX IF NOT EXISTS idx_semantic_attributes_entity ON semantic_attributes(entity_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 4: SEMANTIC RELATIONSHIPS
-- Join paths between entities
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS semantic_relationships (
    id              SERIAL PRIMARY KEY,
    from_entity     VARCHAR(100)    NOT NULL,       -- entity_name
    relationship    VARCHAR(50)     NOT NULL,       -- belongs_to, has_many, has_one
    to_entity       VARCHAR(100)    NOT NULL,       -- entity_name
    join_sql        TEXT            NOT NULL,       -- "JOIN departments d ON d.id = s.department_id"
    description     TEXT,
    confidence      NUMERIC(3,2)    NOT NULL DEFAULT 1.0,  -- 0.0-1.0
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sem_rel_from ON semantic_relationships(from_entity);
CREATE INDEX IF NOT EXISTS idx_sem_rel_to   ON semantic_relationships(to_entity);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 5: ACADEMIC TERMINOLOGY
-- Domain-specific college terms used in India
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS academic_terminology (
    id              SERIAL PRIMARY KEY,
    term            VARCHAR(100)    NOT NULL UNIQUE,
    full_form       VARCHAR(255),
    definition      TEXT            NOT NULL,
    category        VARCHAR(50),   -- exam_type | status | accreditation | metric | policy | grading
    db_mapping      VARCHAR(255),  -- actual DB value/column if directly mappable
    db_table        VARCHAR(100),  -- table where this applies
    aliases         JSONB           NOT NULL DEFAULT '[]',
    usage_examples  JSONB           NOT NULL DEFAULT '[]',
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_terminology_category ON academic_terminology(category);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 6: QUERY EXAMPLES (Query Memory Store)
-- Successful past queries used for pattern matching
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS query_examples (
    id              SERIAL PRIMARY KEY,
    question        TEXT            NOT NULL,
    generated_sql   TEXT            NOT NULL,
    result_summary  TEXT,
    entities_used   JSONB           NOT NULL DEFAULT '[]',
    metrics_used    JSONB           NOT NULL DEFAULT '[]',
    tables_used     JSONB           NOT NULL DEFAULT '[]',
    agent_used      VARCHAR(50),
    query_type      VARCHAR(50),    -- descriptive | comparative | trend | ranking | predictive
    feedback_score  NUMERIC(3,2),   -- 0.0-1.0 user rating
    exec_time_ms    INTEGER,
    success         BOOLEAN         NOT NULL DEFAULT TRUE,
    source          VARCHAR(50)     NOT NULL DEFAULT 'system',  -- system | user | feedback
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_query_examples_success ON query_examples(success, feedback_score DESC);
CREATE INDEX IF NOT EXISTS idx_query_examples_agent   ON query_examples(agent_used);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 7: QUERY FEEDBACK
-- Runtime feedback captured after each query execution
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS query_feedback (
    id              SERIAL PRIMARY KEY,
    query_example_id INTEGER        REFERENCES query_examples(id) ON DELETE SET NULL,
    original_question TEXT          NOT NULL,
    generated_sql   TEXT,
    exec_time_ms    INTEGER,
    success         BOOLEAN         NOT NULL DEFAULT TRUE,
    error_message   TEXT,
    user_rating     SMALLINT,       -- 1-5 stars
    agent_used      VARCHAR(50),
    user_role       VARCHAR(50),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_query_feedback_created ON query_feedback(created_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 8: CONTEXT REGISTRY
-- Versioned configuration per agent type
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS context_registry (
    id              SERIAL PRIMARY KEY,
    agent_type      VARCHAR(50)     NOT NULL UNIQUE,  -- query | performance | report | analytics
    top_k_entities  INTEGER         NOT NULL DEFAULT 10,
    top_k_terms     INTEGER         NOT NULL DEFAULT 8,
    top_k_queries   INTEGER         NOT NULL DEFAULT 5,
    score_threshold NUMERIC(3,2)    NOT NULL DEFAULT 0.60,
    extra_config    JSONB           NOT NULL DEFAULT '{}',
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 9: VECTOR EMBEDDING TABLES
-- Separate tables for vector columns (cleaner for ivfflat index management)
-- ─────────────────────────────────────────────────────────────────────────────

-- Entity embeddings: embed (entity_name + description + aliases)
CREATE TABLE IF NOT EXISTS entity_embeddings (
    entity_id       INTEGER         PRIMARY KEY REFERENCES semantic_entities(id) ON DELETE CASCADE,
    embedding       vector(768),
    model_version   VARCHAR(50)     NOT NULL DEFAULT 'text-embedding-004',
    embedding_text  TEXT,           -- the text that was embedded (for debugging)
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Terminology embeddings: embed (term + full_form + definition)
CREATE TABLE IF NOT EXISTS terminology_embeddings (
    term_id         INTEGER         PRIMARY KEY REFERENCES academic_terminology(id) ON DELETE CASCADE,
    embedding       vector(768),
    model_version   VARCHAR(50)     NOT NULL DEFAULT 'text-embedding-004',
    embedding_text  TEXT,
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Query embeddings: embed the question text
CREATE TABLE IF NOT EXISTS query_embeddings (
    query_id        INTEGER         PRIMARY KEY REFERENCES query_examples(id) ON DELETE CASCADE,
    embedding       vector(768),
    model_version   VARCHAR(50)     NOT NULL DEFAULT 'text-embedding-004',
    embedding_text  TEXT,
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 10: VECTOR INDEXES (ivfflat for cosine similarity)
-- Create AFTER rows are inserted (ivfflat requires at least 1 row)
-- These are created by the seeder after initial data load.
-- ─────────────────────────────────────────────────────────────────────────────

-- Indexes created by KnowledgeSeeder after seeding:
-- CREATE INDEX idx_entity_embeddings_cosine ON entity_embeddings
--   USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);
-- CREATE INDEX idx_term_embeddings_cosine ON terminology_embeddings
--   USING ivfflat (embedding vector_cosine_ops) WITH (lists = 30);
-- CREATE INDEX idx_query_embeddings_cosine ON query_embeddings
--   USING ivfflat (embedding vector_cosine_ops) WITH (lists = 20);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 11: DEFAULT CONTEXT REGISTRY ROWS
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO context_registry (agent_type, top_k_entities, top_k_terms, top_k_queries, score_threshold)
VALUES
    ('query',       10, 8, 5, 0.60),
    ('performance',  8, 6, 4, 0.60),
    ('report',      12, 10, 6, 0.55),
    ('analytics',    8, 6, 4, 0.60),
    ('supervisor',   6, 4, 3, 0.65)
ON CONFLICT (agent_type) DO NOTHING;
