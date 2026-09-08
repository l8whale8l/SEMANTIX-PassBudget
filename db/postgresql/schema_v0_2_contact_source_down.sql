-- Reverse of db/postgresql/schema_v0_2_contact_source.sql. Restores the exact
-- db/postgresql/schema_v0_1.sql contract.
-- Applied by Alembic revision 0002_contact_source_provenance downgrade(), which refuses to run
-- while any SYNTHETIC_INJECTED row exists: schema v0.1 has no honest representation for those rows
-- and this migration never invents an orbit revision or a maximum elevation to satisfy NOT NULL.

SET search_path = passbudget, public;

ALTER FUNCTION passbudget.reject_update_delete() RESET search_path;
ALTER FUNCTION passbudget.reject_hard_delete() RESET search_path;
ALTER FUNCTION passbudget.guard_profile_head_update() RESET search_path;
ALTER FUNCTION passbudget.guard_scenario_head_update() RESET search_path;
ALTER FUNCTION passbudget.guard_source_head_update() RESET search_path;
ALTER FUNCTION passbudget.require_initial_draft() RESET search_path;
ALTER FUNCTION passbudget.guard_profile_revision_parent() RESET search_path;
ALTER FUNCTION passbudget.guard_profile_revision_child() RESET search_path;
ALTER FUNCTION passbudget.guard_scenario_revision_parent() RESET search_path;
ALTER FUNCTION passbudget.guard_scenario_child() RESET search_path;
ALTER FUNCTION passbudget.guard_evidence_assertion() RESET search_path;
ALTER FUNCTION passbudget.require_initial_queued_run() RESET search_path;
ALTER FUNCTION passbudget.guard_run_transition() RESET search_path;
ALTER FUNCTION passbudget.guard_run_stage_mutation() RESET search_path;
ALTER FUNCTION passbudget.guard_run_result_insert() RESET search_path;
ALTER FUNCTION passbudget.guard_result_child_insert() RESET search_path;
ALTER FUNCTION passbudget.check_session_allocation_capacity() RESET search_path;

DROP INDEX IF EXISTS scenario_revision_contact_source_idx;

ALTER TABLE geometric_access
  DROP CONSTRAINT geometric_elevation_source_ck;

ALTER TABLE geometric_access
  ADD CONSTRAINT geometric_peak_time_ck CHECK (
    true_aos <= maximum_elevation_at AND maximum_elevation_at < true_los
  );

ALTER TABLE geometric_access
  ALTER COLUMN maximum_elevation_udeg SET NOT NULL,
  ALTER COLUMN maximum_elevation_at SET NOT NULL;

ALTER TABLE geometric_access
  DROP CONSTRAINT geometric_access_contact_source_fk;

ALTER TABLE geometric_access
  DROP COLUMN contact_source;

ALTER TABLE scenario_station
  DROP CONSTRAINT scenario_station_contact_source_key;

ALTER TABLE scenario_station
  DROP CONSTRAINT scenario_station_contact_source_fk;

ALTER TABLE scenario_station
  DROP COLUMN contact_source;

ALTER TABLE scenario_revision
  DROP CONSTRAINT scenario_revision_contact_source_key;

ALTER TABLE scenario_revision
  DROP CONSTRAINT scenario_contact_source_ck;

ALTER TABLE scenario_revision
  ALTER COLUMN orbit_revision_id SET NOT NULL;

ALTER TABLE scenario_revision
  DROP COLUMN synthetic_contact_provider_revision,
  DROP COLUMN contact_source;

DROP TYPE contact_source_kind;
