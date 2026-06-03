
-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 13 : PRINCIPAL INTELLIGENCE MODULES
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE institution_metrics (
    id SERIAL PRIMARY KEY,
    college_id INTEGER NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    academic_health NUMERIC(5,2),
    attendance_rate NUMERIC(5,2),
    pass_rate NUMERIC(5,2),
    placement_rate NUMERIC(5,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE department_metrics (
    id SERIAL PRIMARY KEY,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    attendance_rate NUMERIC(5,2),
    pass_rate NUMERIC(5,2),
    health_score NUMERIC(5,2),
    risk_students_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE student_risk_scores (
    id SERIAL PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    risk_score NUMERIC(5,2),
    risk_level VARCHAR(20),
    dropout_probability NUMERIC(4,2),
    arrear_probability NUMERIC(4,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE accreditation_metrics (
    id SERIAL PRIMARY KEY,
    college_id INTEGER NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    nba_score NUMERIC(5,2),
    naac_score NUMERIC(5,2),
    documentation_score NUMERIC(5,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE executive_insights (
    id SERIAL PRIMARY KEY,
    college_id INTEGER NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    summary TEXT NOT NULL,
    recommendation TEXT,
    priority VARCHAR(20),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
