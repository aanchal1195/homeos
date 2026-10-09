-- M3E: one durable, owner-reviewed resolution for each visual observation.
-- This table never grants automatic authority to AI detections.
CREATE TABLE IF NOT EXISTS memory_visual_resolutions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id uuid NOT NULL,
  observation_id uuid NOT NULL,
  reviewer_member_id text NOT NULL,
  decision text NOT NULL CHECK(decision IN ('REJECT','VERIFY_ONLY','REGISTER_ASSET','CONFIRM_LOCATION')),
  asset_legacy_id text,
  graph_entity_id uuid,
  location_entity_id uuid,
  corrected_name text,
  review_note text,
  resolved_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(household_id,observation_id) REFERENCES memory_observations(household_id,id),
  FOREIGN KEY(household_id,graph_entity_id) REFERENCES memory_entities(household_id,id),
  FOREIGN KEY(household_id,location_entity_id) REFERENCES memory_entities(household_id,id),
  UNIQUE(household_id,observation_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_visual_resolutions_recent
 ON memory_visual_resolutions(household_id,resolved_at DESC);
