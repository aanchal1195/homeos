-- M3D compatible extension: staged worker pipeline added alongside M3C 003 direct vision analysis.
CREATE TABLE IF NOT EXISTS visual_analysis_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id uuid NOT NULL,
  session_id uuid NOT NULL,
  media_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'QUEUED'
    CHECK(status IN ('QUEUED','PROCESSING','FRAMES_READY','COMPLETED','FAILED')),
  analyzer_name text NOT NULL,
  analyzer_version text NOT NULL,
  idempotency_key text NOT NULL,
  requested_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz,
  error_code text,
  error_detail text,
  FOREIGN KEY (household_id,session_id,media_id) REFERENCES visual_session_media(household_id,session_id,media_id),
  UNIQUE(household_id,id),
  UNIQUE(household_id,idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_visual_analysis_jobs_status
  ON visual_analysis_jobs(household_id,status,requested_at);

CREATE TABLE IF NOT EXISTS visual_frames (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id uuid NOT NULL,
  job_id uuid NOT NULL,
  media_id uuid NOT NULL,
  frame_timestamp_ms integer NOT NULL CHECK(frame_timestamp_ms >= 0),
  storage_key text NOT NULL UNIQUE,
  sha256 text NOT NULL CHECK(sha256 ~ '^[a-f0-9]{64}$'),
  byte_size bigint NOT NULL CHECK(byte_size > 0),
  width integer NOT NULL CHECK(width > 0),
  height integer NOT NULL CHECK(height > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (household_id,job_id) REFERENCES visual_analysis_jobs(household_id,id),
  FOREIGN KEY (household_id,media_id) REFERENCES memory_media(household_id,id),
  UNIQUE(household_id,id),
  UNIQUE(household_id,job_id,frame_timestamp_ms)
);
CREATE INDEX IF NOT EXISTS idx_visual_frames_job
  ON visual_frames(household_id,job_id,frame_timestamp_ms);

CREATE TABLE IF NOT EXISTS visual_analysis_findings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id uuid NOT NULL,
  job_id uuid NOT NULL,
  frame_id uuid NOT NULL,
  observation_id uuid NOT NULL,
  finding_type text NOT NULL,
  summary text NOT NULL,
  severity text NOT NULL CHECK(severity IN ('INFO','LOW','MEDIUM','HIGH','CRITICAL')),
  confidence double precision NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (household_id,job_id) REFERENCES visual_analysis_jobs(household_id,id),
  FOREIGN KEY (household_id,frame_id) REFERENCES visual_frames(household_id,id),
  FOREIGN KEY (household_id,observation_id) REFERENCES memory_observations(household_id,id),
  UNIQUE(household_id,id)
);
CREATE INDEX IF NOT EXISTS idx_visual_findings_job
  ON visual_analysis_findings(household_id,job_id,created_at);
