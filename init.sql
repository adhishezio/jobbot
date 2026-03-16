-- 1. Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. Settings
CREATE TABLE app_settings (
  key   VARCHAR(100) PRIMARY KEY,
  value TEXT
);

CREATE TABLE settings (
  key   VARCHAR(100) PRIMARY KEY,
  value TEXT
);

INSERT INTO app_settings VALUES
  ('search_keywords',        '["machine learning","computer vision","AI engineer","data scientist"]'),
  ('locations',              '["Berlin","Munich","Hamburg","Remote"]'),
  ('platforms',              '["linkedin","indeed","stepstone","google"]'),
  ('min_match_score',        '65'),
  ('scrape_frequency_hours', '6'),
  ('notify_min_score',       '80');

INSERT INTO settings (key, value) VALUES (
  'resume_summary',
  'Add your own resume summary here, or replace /files/master_resume.txt with your structured resume text before generating cover letters.'
) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

-- 3. Jobs Table
CREATE TABLE jobs (
  id                SERIAL PRIMARY KEY,
  title             VARCHAR(255) NOT NULL,
  company           VARCHAR(255),
  location          VARCHAR(255),
  platform          VARCHAR(50),
  job_url           TEXT,
  jd_raw            TEXT,
  jd_summary        TEXT,
  keywords          TEXT[],
  salary            VARCHAR(100),
  match_score       INTEGER,
  jd_embedding      vector(768),
  posted_date       DATE,
  language_pref     VARCHAR(5) DEFAULT 'de',
  status            VARCHAR(50) DEFAULT 'pending',
  screenshot_paths  TEXT[],
  local_folder_path VARCHAR(500),
  application_id    INTEGER,
  created_at        TIMESTAMP DEFAULT NOW()
);

-- 4. Applications Table
CREATE TABLE applications (
  id                SERIAL PRIMARY KEY,
  company           VARCHAR(255),
  company_address   TEXT,
  position          VARCHAR(255),
  language          VARCHAR(5),
  jd_raw            TEXT,
  jd_summary        TEXT,
  keywords          TEXT[],
  cl_text           TEXT,
  cl_pdf_path       VARCHAR(500),
  final_score       INTEGER,
  iterations        INTEGER,
  status            VARCHAR(50) DEFAULT 'pending',
  notes             TEXT,
  platform          VARCHAR(50),
  resume_pdf_path   VARCHAR(500),
  local_folder_path VARCHAR(500),
  cover_letter_id   INTEGER,
  source_job_id     INTEGER REFERENCES jobs(id),
  created_at        TIMESTAMP DEFAULT NOW()
);

-- 5. Notifications Table
CREATE TABLE notifications (
  id              SERIAL PRIMARY KEY,
  type            VARCHAR(50),
  title           VARCHAR(255),
  message         TEXT,
  application_id  INTEGER REFERENCES applications(id),
  job_id          INTEGER REFERENCES jobs(id),
  is_read         BOOLEAN DEFAULT FALSE,
  created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cover_letters (
  id           SERIAL PRIMARY KEY,
  company      VARCHAR(255) NOT NULL,
  position     VARCHAR(255),
  language     VARCHAR(10) DEFAULT 'de',
  score        INTEGER,
  iterations   INTEGER DEFAULT 1,
  pdf_filename VARCHAR(500),
  latex_source TEXT,
  created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS email_analyses (
  id               SERIAL PRIMARY KEY,
  gmail_message_id VARCHAR(255) UNIQUE NOT NULL,
  sender           TEXT,
  subject          TEXT,
  snippet          TEXT,
  email_type       VARCHAR(50),
  company          VARCHAR(255),
  action_required  TEXT,
  suggested_reply  TEXT,
  message_date     TIMESTAMP,
  is_unread        BOOLEAN DEFAULT TRUE,
  analysed_at      TIMESTAMP DEFAULT NOW()
);

-- 6. Circular FK (jobs -> applications)
ALTER TABLE jobs
  ADD CONSTRAINT fk_application
  FOREIGN KEY (application_id) REFERENCES applications(id);

ALTER TABLE applications
  ADD CONSTRAINT fk_cover_letter
  FOREIGN KEY (cover_letter_id) REFERENCES cover_letters(id);

-- 7. Indexes - Performance, Semantic Search, and Trigrams
CREATE INDEX idx_jobs_status            ON jobs(status);
CREATE INDEX idx_jobs_match_score       ON jobs(match_score DESC);
CREATE INDEX idx_jobs_platform          ON jobs(platform);
CREATE INDEX idx_jobs_embedding         ON jobs USING hnsw (jd_embedding vector_cosine_ops);
CREATE INDEX idx_jobs_company_trgm      ON jobs USING gin(company gin_trgm_ops);
CREATE INDEX idx_apps_company_trgm      ON applications USING gin(company gin_trgm_ops);
CREATE INDEX idx_email_analyses_company ON email_analyses(company);
CREATE INDEX idx_jobs_fts               ON jobs USING gin(to_tsvector('german', COALESCE(title,'') || ' ' || COALESCE(company,'') || ' ' || COALESCE(jd_raw,'')));
CREATE INDEX idx_apps_fts               ON applications USING gin(to_tsvector('german', COALESCE(position,'') || ' ' || COALESCE(company,'') || ' ' || COALESCE(cl_text,'')));
