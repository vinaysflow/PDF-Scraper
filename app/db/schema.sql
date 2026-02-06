-- Question Bank database schema for Supabase (Postgres)
-- Run this in the Supabase SQL Editor to create all tables.

-- Documents table
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    exam_title TEXT,
    subject TEXT,
    total_marks INT,
    total_questions INT,
    sections JSONB DEFAULT '[]'::jsonb,
    ingested_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Questions table
CREATE TABLE IF NOT EXISTS questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    question_number INT NOT NULL,
    section TEXT,
    page_number INT NOT NULL,
    text TEXT NOT NULL,
    question_type TEXT,            -- mcq, short_answer, long_answer, proof, construction
    marks INT,
    topic TEXT,
    difficulty TEXT,
    has_or_alternative BOOLEAN DEFAULT FALSE,
    or_question_id UUID REFERENCES questions(id),  -- self-ref for OR alternatives
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(document_id, question_number)
);

-- Question options (MCQ choices)
CREATE TABLE IF NOT EXISTS question_options (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID REFERENCES questions(id) ON DELETE CASCADE,
    label TEXT NOT NULL,           -- "A", "B", "C", "D"
    text TEXT NOT NULL,
    sort_order INT DEFAULT 0
);

-- Question images (stored in Supabase Storage)
CREATE TABLE IF NOT EXISTS question_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID REFERENCES questions(id) ON DELETE CASCADE,
    storage_path TEXT NOT NULL,    -- path in Supabase Storage bucket
    public_url TEXT,               -- public URL from Supabase
    format TEXT DEFAULT 'png',
    width INT,
    height INT,
    description TEXT,              -- VLM description
    bbox JSONB
);

-- Question sub-parts
CREATE TABLE IF NOT EXISTS question_parts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID REFERENCES questions(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    text TEXT NOT NULL,
    marks INT,
    sort_order INT DEFAULT 0
);

-- Useful indexes
CREATE INDEX IF NOT EXISTS idx_questions_document ON questions(document_id);
CREATE INDEX IF NOT EXISTS idx_questions_topic ON questions(topic);
CREATE INDEX IF NOT EXISTS idx_questions_type ON questions(question_type);
CREATE INDEX IF NOT EXISTS idx_questions_marks ON questions(marks);
CREATE INDEX IF NOT EXISTS idx_question_options_question ON question_options(question_id);
CREATE INDEX IF NOT EXISTS idx_question_images_question ON question_images(question_id);
CREATE INDEX IF NOT EXISTS idx_question_parts_question ON question_parts(question_id);
