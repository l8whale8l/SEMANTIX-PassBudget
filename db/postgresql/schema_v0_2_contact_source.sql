-- SEMANTIX PassBudget schema delta v0.2: contact source provenance
-- PostgreSQL 16+. Applied by Alembic revision 0002_contact_source_provenance.
-- Additive only: db/postgresql/schema_v0_1.sql is the unchanged accepted baseline and is not rewritten.
-- Rationale and alternatives: docs/architecture/ADR-0002-synthetic-contact-provenance.md
-- Secrets, host addresses, personal paths, and fixture data are intentionally absent.

SET search_path = passbudget, public;

CREATE TYPE contact_source_kind AS ENUM ('ORBIT_DERIVED', 'SYNTHETIC_INJECTED');

-- A scenario revision now declares where its contact intervals come from.
-- ORBIT_DERIVED keeps the unweakened v0.1 contract: an orbit revision is mandatory.
-- SYNTHETIC_INJECTED forbids an orbit revision and requires a named provider revision instead,
-- so orbit_dependency = NOT_APPLICABLE is an explicit typed state rather than an unexplained null.
ALTER TABLE scenario_revision
  ADD COLUMN contact_source contact_source_kind NOT NULL DEFAULT 'ORBIT_DERIVED',
  ADD COLUMN synthetic_contact_provider_revision varchar(96);

ALTER TABLE scenario_revision
  ALTER COLUMN orbit_revision_id DROP NOT NULL;

ALTER TABLE scenario_revision
  ADD CONSTRAINT scenario_contact_source_ck CHECK (
    (contact_source = 'ORBIT_DERIVED'
      AND orbit_revision_id IS NOT NULL
      AND synthetic_contact_provider_revision IS NULL)
    OR
    (contact_source = 'SYNTHETIC_INJECTED'
      AND orbit_revision_id IS NULL
      AND synthetic_contact_provider_revision IS NOT NULL
      AND synthetic_contact_provider_revision ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$')
  );

ALTER TABLE scenario_revision
  ADD CONSTRAINT scenario_revision_contact_source_key UNIQUE (id, contact_source);

-- Station rows carry the discriminator so children can validate it through a real FK
-- instead of an application-only invariant.
ALTER TABLE scenario_station
  ADD COLUMN contact_source contact_source_kind NOT NULL DEFAULT 'ORBIT_DERIVED';

ALTER TABLE scenario_station
  ADD CONSTRAINT scenario_station_contact_source_fk
  FOREIGN KEY (scenario_revision_id, contact_source)
  REFERENCES scenario_revision(id, contact_source) ON DELETE RESTRICT;

ALTER TABLE scenario_station
  ADD CONSTRAINT scenario_station_contact_source_key UNIQUE (id, contact_source);

-- Geometric access keeps the full v0.1 elevation contract for orbit-derived rows and
-- requires the absence of invented elevation values for synthetic injected rows.
ALTER TABLE geometric_access
  ADD COLUMN contact_source contact_source_kind NOT NULL DEFAULT 'ORBIT_DERIVED';

ALTER TABLE geometric_access
  ADD CONSTRAINT geometric_access_contact_source_fk
  FOREIGN KEY (scenario_station_id, contact_source)
  REFERENCES scenario_station(id, contact_source) ON DELETE RESTRICT;

ALTER TABLE geometric_access
  ALTER COLUMN maximum_elevation_udeg DROP NOT NULL,
  ALTER COLUMN maximum_elevation_at DROP NOT NULL;

ALTER TABLE geometric_access
  DROP CONSTRAINT geometric_peak_time_ck;

ALTER TABLE geometric_access
  ADD CONSTRAINT geometric_elevation_source_ck CHECK (
    (contact_source = 'ORBIT_DERIVED'
      AND maximum_elevation_udeg IS NOT NULL
      AND maximum_elevation_udeg BETWEEN 0 AND 90000000
      AND maximum_elevation_at IS NOT NULL
      AND true_aos <= maximum_elevation_at
      AND maximum_elevation_at < true_los)
    OR
    (contact_source = 'SYNTHETIC_INJECTED'
      AND maximum_elevation_udeg IS NULL
      AND maximum_elevation_at IS NULL)
  );

CREATE INDEX scenario_revision_contact_source_idx
  ON scenario_revision(contact_source, created_at DESC);

COMMENT ON COLUMN scenario_revision.contact_source IS
  'Contact interval provenance. SYNTHETIC_INJECTED means orbit_dependency = NOT_APPLICABLE and forbids an orbit revision.';
COMMENT ON COLUMN scenario_revision.synthetic_contact_provider_revision IS
  'Immutable provider revision that injected the contact intervals; required exactly when contact_source = SYNTHETIC_INJECTED.';
COMMENT ON COLUMN geometric_access.contact_source IS
  'Mirrors the scenario revision through scenario_station; maximum elevation is mandatory for ORBIT_DERIVED and forbidden for SYNTHETIC_INJECTED.';

-- Trigger functions from the accepted v0.1 baseline refer to schema-local types and tables.
-- Pin their runtime lookup path so application connections do not depend on a session setting.
-- pg_catalog is first and public is deliberately excluded to prevent object shadowing.
ALTER FUNCTION passbudget.reject_update_delete() SET search_path = pg_catalog, passbudget;
ALTER FUNCTION passbudget.reject_hard_delete() SET search_path = pg_catalog, passbudget;
ALTER FUNCTION passbudget.guard_profile_head_update() SET search_path = pg_catalog, passbudget;
ALTER FUNCTION passbudget.guard_scenario_head_update() SET search_path = pg_catalog, passbudget;
ALTER FUNCTION passbudget.guard_source_head_update() SET search_path = pg_catalog, passbudget;
ALTER FUNCTION passbudget.require_initial_draft() SET search_path = pg_catalog, passbudget;
ALTER FUNCTION passbudget.guard_profile_revision_parent() SET search_path = pg_catalog, passbudget;
ALTER FUNCTION passbudget.guard_profile_revision_child() SET search_path = pg_catalog, passbudget;
ALTER FUNCTION passbudget.guard_scenario_revision_parent() SET search_path = pg_catalog, passbudget;
ALTER FUNCTION passbudget.guard_scenario_child() SET search_path = pg_catalog, passbudget;
ALTER FUNCTION passbudget.guard_evidence_assertion() SET search_path = pg_catalog, passbudget;
ALTER FUNCTION passbudget.require_initial_queued_run() SET search_path = pg_catalog, passbudget;
ALTER FUNCTION passbudget.guard_run_transition() SET search_path = pg_catalog, passbudget;
ALTER FUNCTION passbudget.guard_run_stage_mutation() SET search_path = pg_catalog, passbudget;
ALTER FUNCTION passbudget.guard_run_result_insert() SET search_path = pg_catalog, passbudget;
ALTER FUNCTION passbudget.guard_result_child_insert() SET search_path = pg_catalog, passbudget;
ALTER FUNCTION passbudget.check_session_allocation_capacity() SET search_path = pg_catalog, passbudget;
