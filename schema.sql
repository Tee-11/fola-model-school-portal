CREATE TABLE IF NOT EXISTS students (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    class_name TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT 'General',
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS teachers (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admins (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_admins_name_lower
ON admins (LOWER(name));

CREATE TABLE IF NOT EXISTS subjects (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    class_name TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT 'General',
    term TEXT NOT NULL,
    note_path TEXT,
    note_filename TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS results (
    id BIGSERIAL PRIMARY KEY,
    student_id BIGINT NOT NULL,
    term TEXT NOT NULL,
    filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    mime_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT results_student_id_fkey
        FOREIGN KEY (student_id)
        REFERENCES students(id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS news (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_students_name
ON students (LOWER(name));

CREATE INDEX IF NOT EXISTS idx_teachers_name
ON teachers (LOWER(name));

CREATE INDEX IF NOT EXISTS idx_subjects_group
ON subjects (LOWER(class_name), LOWER(department), LOWER(term));

CREATE INDEX IF NOT EXISTS idx_results_student_term
ON results (student_id, term, created_at DESC);
