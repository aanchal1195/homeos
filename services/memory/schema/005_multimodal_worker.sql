-- M3D: durable leases and bounded retries for an opt-in multimodal model worker.
-- Additive migration. Apply only after 004_staged_visual_worker.sql.
ALTER TABLE visual_analysis_jobs
  DROP CONSTRAINT IF EXISTS visual_analysis_jobs_status_check;
ALTER TABLE visual_analysis_jobs
  ADD CONSTRAINT visual_analysis_jobs_status_check
  CHECK(status IN ('QUEUED','PROCESSING','FRAMES_READY','ANALYZING','COMPLETED','FAILED'));
ALTER TABLE visual_analysis_jobs
  ADD COLUMN IF NOT EXISTS attempt_count integer NOT NULL DEFAULT 0
    CHECK (attempt_count >= 0),
  ADD COLUMN IF NOT EXISTS next_attempt_at timestamptz,
  ADD COLUMN IF NOT EXISTS lease_token uuid,
  ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz;
CREATE INDEX IF NOT EXISTS idx_visual_analysis_ready_worker
  ON visual_analysis_jobs (household_id,analyzer_name,analyzer_version,status,next_attempt_at,requested_at)
  WHERE status IN ('FRAMES_READY','ANALYZING');
