-- M3C: reproducible visual-analysis runs; never automatically promote observations to graph assertions.
CREATE TABLE IF NOT EXISTS visual_analysis_runs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 household_id uuid NOT NULL,
 session_id uuid NOT NULL,
 media_id uuid NOT NULL,
 status text NOT NULL CHECK(status IN ('PENDING','RUNNING','COMPLETED','FAILED','SKIPPED')),
 provider text NOT NULL,
 model_version text NOT NULL,
 result_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
 error_code text,
 created_at timestamptz NOT NULL DEFAULT now(),
 completed_at timestamptz,
 FOREIGN KEY (household_id,session_id,media_id)
  REFERENCES visual_session_media(household_id,session_id,media_id),
 UNIQUE(household_id,session_id,media_id,provider,model_version),
 UNIQUE(household_id,id)
);
CREATE INDEX IF NOT EXISTS idx_visual_analysis_run_session ON visual_analysis_runs(household_id,session_id,created_at);
ALTER TABLE memory_observations
 ADD COLUMN IF NOT EXISTS analysis_run_id uuid,
 ADD COLUMN IF NOT EXISTS review_reason text;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_observation_analysis_run') THEN
  ALTER TABLE memory_observations ADD CONSTRAINT fk_observation_analysis_run
  FOREIGN KEY(household_id,analysis_run_id) REFERENCES visual_analysis_runs(household_id,id);
 END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_memory_observation_run ON memory_observations(household_id,analysis_run_id);
