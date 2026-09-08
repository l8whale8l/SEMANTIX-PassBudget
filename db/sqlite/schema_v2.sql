-- SEMANTIX PassBudget local SQLite schema v2 — catalog persistence.
--
-- The v1 tables (scenario, scenario_revision, scenario_station, ...) are the *run-path* record:
-- the run repository decomposes a computed run's snapshot into them, keyed by fixture id, with a
-- NOT NULL semantic_hash and every engine-revision column filled. They cannot hold the *catalog's*
-- lifecycle records, which are opaque-content, DRAFT-able revisions created through the API before
-- any run exists. Reusing them would also collide with the run repository's own scenario rows.
--
-- So the catalog gets its own tables here (prefixed `catalog_`), storing exactly the opaque JSON
-- the CatalogRepository port is defined around — a faithful, on-disk mirror of the in-memory
-- adapter. This makes scenarios, revisions and snapshots survive a backend restart on the SQLite
-- tier. Migration is forward-only (see schema.py); recovering an older file is a file
-- copy, and backing up the catalog is backing up the same single database file as the run rows.
--
-- Representation contract matches v1: UUIDs from the application, digests as 64-char hex TEXT,
-- opaque bodies as JSON TEXT, canonical bytes as BLOB. No secrets or host paths are stored.

CREATE TABLE catalog_profile (
  profile_id           TEXT PRIMARY KEY,
  stable_key           TEXT NOT NULL UNIQUE,
  kind                 TEXT NOT NULL,
  name                 TEXT NOT NULL,
  description          TEXT,
  is_preset            INTEGER NOT NULL CHECK (is_preset IN (0, 1)),
  current_revision_id  TEXT,
  archived             INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1))
);

CREATE TABLE catalog_profile_revision (
  revision_id           TEXT PRIMARY KEY,
  profile_id            TEXT NOT NULL REFERENCES catalog_profile(profile_id) ON DELETE CASCADE,
  profile_kind          TEXT NOT NULL,
  revision_no           INTEGER NOT NULL CHECK (revision_no > 0),
  lifecycle_status      TEXT NOT NULL CHECK (lifecycle_status IN ('DRAFT', 'PUBLISHED')),
  schema_version        TEXT NOT NULL,
  label                 TEXT NOT NULL,
  change_note           TEXT,
  based_on_revision_id  TEXT,
  payload_json          TEXT NOT NULL,
  semantic_hash         TEXT CHECK (semantic_hash IS NULL OR length(semantic_hash) = 64),
  published_at          TEXT,
  UNIQUE (profile_id, revision_no)
);
CREATE INDEX catalog_profile_revision_by_profile ON catalog_profile_revision (profile_id);

CREATE TABLE catalog_scenario (
  scenario_id          TEXT PRIMARY KEY,
  stable_key           TEXT NOT NULL UNIQUE,
  name                 TEXT NOT NULL,
  description          TEXT,
  is_preset            INTEGER NOT NULL CHECK (is_preset IN (0, 1)),
  current_revision_id  TEXT,
  archived             INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1))
);

CREATE TABLE catalog_scenario_revision (
  revision_id           TEXT PRIMARY KEY,
  scenario_id           TEXT NOT NULL REFERENCES catalog_scenario(scenario_id) ON DELETE CASCADE,
  revision_no           INTEGER NOT NULL CHECK (revision_no > 0),
  lifecycle_status      TEXT NOT NULL CHECK (lifecycle_status IN ('DRAFT', 'PUBLISHED')),
  schema_version        TEXT NOT NULL,
  based_on_revision_id  TEXT,
  content_json          TEXT NOT NULL,
  semantic_hash         TEXT CHECK (semantic_hash IS NULL OR length(semantic_hash) = 64),
  published_at          TEXT,
  UNIQUE (scenario_id, revision_no)
);
CREATE INDEX catalog_scenario_revision_by_scenario ON catalog_scenario_revision (scenario_id);

CREATE TABLE catalog_snapshot (
  snapshot_id                TEXT PRIMARY KEY,
  scenario_revision_id       TEXT NOT NULL
                               REFERENCES catalog_scenario_revision(revision_id) ON DELETE CASCADE,
  schema_version             TEXT NOT NULL,
  canonicalization_revision  TEXT NOT NULL,
  canonical_bytes            BLOB NOT NULL,
  content_sha256             TEXT NOT NULL CHECK (length(content_sha256) = 64),
  validation_status          TEXT NOT NULL CHECK (validation_status IN ('VALID', 'INVALID')),
  validation_code            TEXT,
  content_json               TEXT NOT NULL
);

CREATE TABLE catalog_scenario_run (
  seq          INTEGER PRIMARY KEY AUTOINCREMENT,
  scenario_id  TEXT NOT NULL REFERENCES catalog_scenario(scenario_id) ON DELETE CASCADE,
  run_id       TEXT NOT NULL
);
CREATE INDEX catalog_scenario_run_by_scenario ON catalog_scenario_run (scenario_id, seq);
