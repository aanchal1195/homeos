-- M3B: durable private media ingestion and guided inspection coverage.
CREATE TABLE IF NOT EXISTS memory_media (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id uuid NOT NULL,
  sha256 text NOT NULL CHECK(sha256 ~ '^[a-f0-9]{64}$'),
  storage_key text NOT NULL UNIQUE,
  content_type text NOT NULL CHECK(content_type IN ('image/jpeg','image/png','image/webp','video/mp4','video/quicktime')),
  byte_size bigint NOT NULL CHECK(byte_size > 0),
  original_filename text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(household_id,id)
);
CREATE INDEX IF NOT EXISTS idx_memory_media_household ON memory_media(household_id,created_at DESC);
CREATE TABLE IF NOT EXISTS visual_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id uuid NOT NULL,
  session_type text NOT NULL CHECK(session_type IN ('WEEKLY_WALKTHROUGH','TASK_VERIFICATION','INVENTORY_SCAN','ISSUE_REPORT','ASSET_REGISTRATION')),
  expected_location_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','SUBMITTED','REVIEWED','CANCELLED')),
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  FOREIGN KEY (household_id,expected_location_id) REFERENCES memory_entities(household_id,id),
  UNIQUE(household_id,id)
);
CREATE TABLE IF NOT EXISTS visual_session_media (
  household_id uuid NOT NULL,
  session_id uuid NOT NULL,
  media_id uuid NOT NULL,
  attached_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(household_id,session_id,media_id),
  FOREIGN KEY (household_id,session_id) REFERENCES visual_sessions(household_id,id),
  FOREIGN KEY (household_id,media_id) REFERENCES memory_media(household_id,id)
);
CREATE TABLE IF NOT EXISTS visual_coverage (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id uuid NOT NULL,
  session_id uuid NOT NULL,
  location_id uuid NOT NULL,
  coverage_status text NOT NULL CHECK(coverage_status IN ('NOT_OBSERVED','PARTIAL','OBSERVED','UNVERIFIED')),
  evidence_media_id uuid,
  notes text,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (household_id,session_id) REFERENCES visual_sessions(household_id,id),
  FOREIGN KEY (household_id,location_id) REFERENCES memory_entities(household_id,id),
  FOREIGN KEY (household_id,evidence_media_id) REFERENCES memory_media(household_id,id),
  UNIQUE(household_id,session_id,location_id)
);
ALTER TABLE memory_observations
 ADD COLUMN IF NOT EXISTS media_id uuid,
 ADD COLUMN IF NOT EXISTS frame_timestamp_ms integer,
 ADD COLUMN IF NOT EXISTS model_version text;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_observation_media') THEN
  ALTER TABLE memory_observations ADD CONSTRAINT fk_observation_media
  FOREIGN KEY(household_id,media_id) REFERENCES memory_media(household_id,id);
 END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_visual_session_by_household ON visual_sessions(household_id,started_at DESC);
