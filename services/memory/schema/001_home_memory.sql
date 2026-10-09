-- M3A: tenant-scoped, evidence-backed home memory.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS memory_entities (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id uuid NOT NULL,
  entity_type text NOT NULL CHECK (entity_type IN
    ('HOME','FLOOR','ROOM','SPACE','ZONE','ASSET','STORAGE','ITEM','PERSON','STAFF','VENDOR','TASK','ISSUE','DOCUMENT','EVENT')),
  canonical_name text NOT NULL CHECK (length(trim(canonical_name)) > 0),
  attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','ARCHIVED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (household_id,id)
);
CREATE INDEX IF NOT EXISTS idx_memory_entities_name ON memory_entities (household_id,lower(canonical_name));
CREATE INDEX IF NOT EXISTS idx_memory_entities_type ON memory_entities (household_id,entity_type);
CREATE TABLE IF NOT EXISTS memory_aliases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id uuid NOT NULL,
  entity_id uuid NOT NULL,
  alias text NOT NULL CHECK (length(trim(alias)) > 0),
  FOREIGN KEY (household_id,entity_id) REFERENCES memory_entities(household_id,id) ON DELETE CASCADE,
  UNIQUE(household_id,entity_id,alias)
);
CREATE INDEX IF NOT EXISTS idx_memory_alias_lookup ON memory_aliases(household_id,lower(alias));
CREATE TABLE IF NOT EXISTS memory_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id uuid NOT NULL,
  source_type text NOT NULL CHECK (source_type IN ('OWNER','STAFF_MESSAGE','TASK','INSPECTION','PHOTO','VIDEO','DOCUMENT','SYSTEM')),
  source_ref text,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(household_id,id)
);
CREATE TABLE IF NOT EXISTS memory_assertions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id uuid NOT NULL,
  subject_id uuid NOT NULL,
  predicate text NOT NULL CHECK (predicate IN
    ('PART_OF','CONTAINS','LOCATED_IN','STORED_IN','ADJACENT_TO','ABOVE','CONNECTS_TO','HAS_ISSUE','ASSIGNED_TO','SERVICED_BY','RELATED_TO')),
  object_id uuid NOT NULL,
  evidence_id uuid NOT NULL,
  verification_status text NOT NULL DEFAULT 'PROPOSED'
     CHECK (verification_status IN ('PROPOSED','CONFIRMED','REJECTED','SUPERSEDED')),
  confidence numeric(4,3) CHECK(confidence BETWEEN 0 AND 1),
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_until timestamptz,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  supersedes_id uuid,
  CHECK(subject_id <> object_id),
  CHECK(valid_until IS NULL OR valid_until > valid_from),
  FOREIGN KEY (household_id,subject_id) REFERENCES memory_entities(household_id,id),
  FOREIGN KEY (household_id,object_id) REFERENCES memory_entities(household_id,id),
  FOREIGN KEY (household_id,evidence_id) REFERENCES memory_evidence(household_id,id),
  FOREIGN KEY (household_id,supersedes_id) REFERENCES memory_assertions(household_id,id),
  UNIQUE(household_id,id)
);
CREATE INDEX IF NOT EXISTS idx_assertion_subject ON memory_assertions(household_id,subject_id,predicate,verification_status);
CREATE INDEX IF NOT EXISTS idx_assertion_object ON memory_assertions(household_id,object_id,predicate,verification_status);
CREATE UNIQUE INDEX IF NOT EXISTS one_current_confirmed_location ON memory_assertions(household_id,subject_id)
 WHERE predicate='LOCATED_IN' AND verification_status='CONFIRMED' AND valid_until IS NULL;
CREATE TABLE IF NOT EXISTS memory_observations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id uuid NOT NULL,
  subject_id uuid,
  predicate text,
  candidate_object_id uuid,
  evidence_id uuid NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','ACCEPTED','REJECTED')),
  confidence numeric(4,3) CHECK(confidence BETWEEN 0 AND 1),
  observed_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (household_id,subject_id) REFERENCES memory_entities(household_id,id),
  FOREIGN KEY (household_id,candidate_object_id) REFERENCES memory_entities(household_id,id),
  FOREIGN KEY (household_id,evidence_id) REFERENCES memory_evidence(household_id,id),
  UNIQUE(household_id,id)
);
CREATE TABLE IF NOT EXISTS memory_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id uuid NOT NULL,
  event_type text NOT NULL,
  subject_id uuid,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  recorded_at timestamptz NOT NULL DEFAULT now(),
  idempotency_key text,
  FOREIGN KEY (household_id,subject_id) REFERENCES memory_entities(household_id,id),
  UNIQUE(household_id,idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_memory_events_subject ON memory_events(household_id,subject_id,occurred_at DESC);
