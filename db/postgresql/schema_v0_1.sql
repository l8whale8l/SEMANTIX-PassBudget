-- SEMANTIX PassBudget P0 physical schema v0.1
-- PostgreSQL 16+
-- Migration order: extension -> schema -> types -> tables -> FKs -> indexes
--                  -> invariant functions/triggers -> grants.
-- Secrets, host addresses, personal paths, and fixture data are intentionally absent.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS passbudget;
SET search_path = passbudget, public;

CREATE TYPE source_kind AS ENUM
  ('DOCUMENT', 'PUBLIC_API', 'USER_ASSERTION', 'TEST_FIXTURE', 'SYSTEM_POLICY');
CREATE TYPE source_status AS ENUM ('ACTIVE', 'ARCHIVED', 'TOMBSTONED');
CREATE TYPE sensitivity_class AS ENUM ('PUBLIC', 'INTERNAL', 'RESTRICTED');
CREATE TYPE profile_kind AS ENUM
  ('SPACECRAFT', 'ORBIT', 'GROUND_STATION', 'COMMUNICATION', 'PAYLOAD_TYPE', 'POLICY');
CREATE TYPE revision_status AS ENUM ('DRAFT', 'PUBLISHED');
CREATE TYPE orbit_kind AS ENUM ('GP_TLE', 'VIRTUAL_CIRCULAR');
CREATE TYPE capacity_provider_kind AS ENUM ('FIXED_RATE', 'FIXED_CAPACITY_PER_CONTACT');
CREATE TYPE rate_semantics AS ENUM
  ('CODED_BITRATE', 'NET_PAYLOAD_BITRATE_PRE_LOSS', 'APPLICATION_GOODPUT');
CREATE TYPE rate_scope AS ENUM ('ACTIVE_DATA_WINDOW', 'WHOLE_MODELED_CONTACT');
CREATE TYPE communication_segment_kind AS ENUM ('RATE', 'TIME_RESERVE');
CREATE TYPE accounted_effect AS ENUM
  ('CODING', 'PROTOCOL_OVERHEAD', 'RESIDUAL_LOSS', 'RETRANSMISSION', 'FEC', 'PADDING');
CREATE TYPE reserve_kind AS ENUM ('NONE', 'BYTE', 'TIME');
CREATE TYPE compatibility_status AS ENUM ('ELIGIBLE', 'INELIGIBLE', 'UNKNOWN');
CREATE TYPE segmentation_kind AS ENUM ('ATOMIC_OBJECT', 'FIXED_CHUNK', 'BYTE_RANGE');
CREATE TYPE policy_kind AS ENUM ('FIFO', 'DEADLINE_SEVERITY', 'VALUE_PER_BYTE');
CREATE TYPE starvation_guard_mode AS ENUM ('NOT_APPLICABLE', 'MAX_WAIT_PROMOTION', 'ALLOW_STARVATION');
CREATE TYPE analysis_mode AS ENUM ('NETWORK_ONLY', 'QUEUE_AWARE');
CREATE TYPE storage_model_mode AS ENUM ('DISABLED', 'ENABLED');
CREATE TYPE storage_admission_policy AS ENUM ('REJECT_NEW');
CREATE TYPE reserve_enforcement AS ENUM ('HARD', 'SOFT');
CREATE TYPE reclaim_granularity AS ENUM ('OBJECT', 'CHUNK');
CREATE TYPE release_trigger AS ENUM ('NEVER', 'TX_END');
CREATE TYPE delivery_assumption AS ENUM ('NONE', 'TX_END_EQUALS_DELIVERED');
CREATE TYPE service_class AS ENUM ('MANDATORY', 'PRIORITY', 'BEST_EFFORT');
CREATE TYPE deadline_target AS ENUM
  ('FIRST_BYTE', 'INSTANCE_COMPLETE', 'BUNDLE_ACTIONABLE', 'BUNDLE_COMPLETE');
CREATE TYPE post_deadline_action AS ENUM
  ('CONTINUE_AND_REPORT', 'DEMOTE_AND_REPORT', 'STOP_SCHEDULING');
CREATE TYPE bundle_member_role AS ENUM ('REQUIRED_ACTIONABLE', 'REQUIRED_COMPLETE', 'OPTIONAL');
CREATE TYPE producer_kind AS ENUM ('MODEL_DERIVED', 'USER_SUPPLIED');
CREATE TYPE initial_storage_state AS ENUM ('GENERATED_AT_READY', 'ALREADY_STORED');
CREATE TYPE dependency_kind AS ENUM
  ('DERIVED_FROM', 'SEND_AFTER', 'REQUIRED_FOR_USE',
   'REQUIRED_FOR_BUNDLE_COMPLETE', 'RETENTION_GUARD');
CREATE TYPE presence_state AS ENUM ('PROVIDED', 'OMITTED', 'DEFAULTED');
CREATE TYPE value_state AS ENUM ('KNOWN', 'UNKNOWN', 'NOT_APPLICABLE');
CREATE TYPE evidence_state AS ENUM ('CONFIRMED', 'PROVISIONAL', 'PROXY', 'UNKNOWN');
CREATE TYPE evidence_kind AS ENUM
  ('MEASURED', 'MANUFACTURER_PROVIDED', 'PUBLIC_SOURCE', 'ANALOG_PROXY',
   'EXPERT_ESTIMATE', 'USER_ASSUMPTION', 'SYSTEM_POLICY', 'DERIVED');
CREATE TYPE origin_kind AS ENUM
  ('EXPLICIT', 'PARSED', 'NORMALIZED', 'DERIVED', 'SOURCE_IMPLIED', 'USER_PROXY', 'SYSTEM_DEFAULT');
CREATE TYPE snapshot_validation_status AS ENUM ('VALID', 'INVALID');
CREATE TYPE run_status AS ENUM ('QUEUED', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'INVALID');
CREATE TYPE stage_status AS ENUM ('PENDING', 'RUNNING', 'SUCCEEDED', 'BLOCKED', 'FAILED', 'INVALID', 'NOT_APPLICABLE');
CREATE TYPE result_kind AS ENUM
  ('GEOMETRIC_ACCESS', 'MODELED_CONTACT', 'CANDIDATE_SESSION', 'SCHEDULED_SESSION',
   'TRANSFER_ALLOCATION', 'RUN_EVENT', 'METRIC', 'ANNOTATION');
CREATE TYPE calculation_status AS ENUM ('COMPUTED', 'BLOCKED', 'INVALID', 'KNOWN_ZERO', 'NOT_APPLICABLE');
CREATE TYPE decision_grade AS ENUM ('VERIFIED', 'ENGINEERING_ESTIMATE', 'CONCEPT_ONLY', 'BLOCKED');
CREATE TYPE event_domain AS ENUM ('QUEUE', 'STORAGE');
CREATE TYPE annotation_kind AS ENUM ('WARNING', 'DECISION_REASON', 'VALIDATION');
CREATE TYPE annotation_severity AS ENUM ('INFO', 'WARNING', 'ERROR');
CREATE TYPE retention_class AS ENUM ('STANDARD', 'BASELINE');

-- 1. Mutable source head. Sensitive material is held outside the database; this row
-- retains an opaque identity and tombstone state.
CREATE TABLE evidence_source (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  stable_key varchar(64) NOT NULL UNIQUE,
  name varchar(160) NOT NULL,
  source_kind source_kind NOT NULL,
  sensitivity sensitivity_class NOT NULL DEFAULT 'PUBLIC',
  status source_status NOT NULL DEFAULT 'ACTIVE',
  description varchar(1000),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  archived_at timestamptz,
  tombstoned_at timestamptz,
  tombstone_reason varchar(1000),
  CONSTRAINT evidence_source_stable_key_ck CHECK (stable_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'),
  CONSTRAINT evidence_source_state_ck CHECK (
    (status = 'ACTIVE' AND archived_at IS NULL AND tombstoned_at IS NULL AND tombstone_reason IS NULL) OR
    (status = 'ARCHIVED' AND archived_at IS NOT NULL AND tombstoned_at IS NULL AND tombstone_reason IS NULL) OR
    (status = 'TOMBSTONED' AND tombstoned_at IS NOT NULL AND tombstone_reason IS NOT NULL)
  )
);

-- 2. Immutable source revision. locator accepts only repository-safe opaque or HTTPS identifiers.
CREATE TABLE evidence_source_revision (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id uuid NOT NULL REFERENCES evidence_source(id) ON DELETE RESTRICT,
  revision_no integer NOT NULL CHECK (revision_no > 0),
  label varchar(160) NOT NULL,
  locator varchar(2048),
  media_type varchar(127),
  retrieved_at timestamptz,
  observed_at timestamptz,
  content_sha256 bytea,
  raw_import_payload jsonb,
  raw_payload_schema_version varchar(64),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (source_id, revision_no),
  CONSTRAINT source_locator_ck CHECK (
    locator IS NULL OR locator ~ '^(https://|urn:|artifact:)[^[:cntrl:]]+$'
  ),
  CONSTRAINT source_hash_ck CHECK (content_sha256 IS NULL OR octet_length(content_sha256) = 32),
  CONSTRAINT source_raw_schema_ck CHECK (
    (raw_import_payload IS NULL AND raw_payload_schema_version IS NULL) OR
    (raw_import_payload IS NOT NULL AND raw_payload_schema_version IS NOT NULL AND jsonb_typeof(raw_import_payload) IN ('object','array'))
  )
);

-- 3. Common mutable profile head; kind is immutable after creation.
CREATE TABLE profile (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  stable_key varchar(64) NOT NULL UNIQUE,
  kind profile_kind NOT NULL,
  name varchar(160) NOT NULL,
  description varchar(1000),
  is_preset boolean NOT NULL DEFAULT false,
  current_revision_id uuid,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  archived_at timestamptz,
  UNIQUE (id, kind),
  CONSTRAINT profile_stable_key_ck CHECK (stable_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$')
);

-- 4. Shared immutable revision metadata. Kinds with P0 calculation fields use one subtype;
-- SPACECRAFT is identity-only in P0 and uses this revision directly.
CREATE TABLE profile_revision (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id uuid NOT NULL,
  profile_kind profile_kind NOT NULL,
  revision_no integer NOT NULL CHECK (revision_no > 0),
  lifecycle_status revision_status NOT NULL DEFAULT 'DRAFT',
  schema_version varchar(32) NOT NULL,
  label varchar(160) NOT NULL,
  change_note varchar(1000),
  based_on_revision_id uuid REFERENCES profile_revision(id) ON DELETE RESTRICT,
  semantic_hash bytea,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  published_at timestamptz,
  UNIQUE (profile_id, revision_no),
  UNIQUE (id, profile_kind),
  UNIQUE (id, profile_id),
  FOREIGN KEY (profile_id, profile_kind) REFERENCES profile(id, kind) ON DELETE RESTRICT,
  CONSTRAINT profile_revision_hash_ck CHECK (semantic_hash IS NULL OR octet_length(semantic_hash) = 32),
  CONSTRAINT profile_revision_publish_ck CHECK (
    (lifecycle_status = 'DRAFT' AND published_at IS NULL) OR
    (lifecycle_status = 'PUBLISHED' AND published_at IS NOT NULL AND semantic_hash IS NOT NULL)
  )
);

ALTER TABLE profile
  ADD CONSTRAINT profile_current_revision_fk
  FOREIGN KEY (current_revision_id, id)
  REFERENCES profile_revision(id, profile_id) ON DELETE RESTRICT
  DEFERRABLE INITIALLY DEFERRED;

-- 5. ORBIT tagged union. Null groups represent an explicitly UNKNOWN draft value;
-- executable-snapshot completeness is checked by the service gate.
CREATE TABLE orbit_revision (
  revision_id uuid PRIMARY KEY,
  profile_kind profile_kind NOT NULL DEFAULT 'ORBIT' CHECK (profile_kind = 'ORBIT'),
  orbit_kind orbit_kind NOT NULL,
  epoch_at timestamptz,
  reference_frame varchar(32),
  time_scale varchar(16),
  propagator_revision varchar(96),
  tle_line1 char(69),
  tle_line2 char(69),
  tle_provider varchar(96),
  tle_retrieved_at timestamptz,
  tle_content_sha256 bytea,
  earth_radius_m bigint,
  altitude_m bigint,
  inclination_udeg bigint,
  raan_udeg bigint,
  argument_of_latitude_udeg bigint,
  FOREIGN KEY (revision_id, profile_kind) REFERENCES profile_revision(id, profile_kind) ON DELETE RESTRICT,
  CONSTRAINT orbit_tle_hash_ck CHECK (tle_content_sha256 IS NULL OR octet_length(tle_content_sha256) = 32),
  CONSTRAINT orbit_tagged_union_ck CHECK (
    (orbit_kind = 'GP_TLE'
      AND earth_radius_m IS NULL AND altitude_m IS NULL AND inclination_udeg IS NULL
      AND raan_udeg IS NULL AND argument_of_latitude_udeg IS NULL
      AND ((tle_line1 IS NULL AND tle_line2 IS NULL) OR (tle_line1 IS NOT NULL AND tle_line2 IS NOT NULL)))
    OR
    (orbit_kind = 'VIRTUAL_CIRCULAR'
      AND tle_line1 IS NULL AND tle_line2 IS NULL AND tle_provider IS NULL
      AND tle_retrieved_at IS NULL AND tle_content_sha256 IS NULL
      AND ((earth_radius_m IS NULL AND altitude_m IS NULL AND inclination_udeg IS NULL
            AND raan_udeg IS NULL AND argument_of_latitude_udeg IS NULL)
        OR (earth_radius_m > 0 AND altitude_m > 0
            AND inclination_udeg BETWEEN 0 AND 180000000
            AND raan_udeg >= 0 AND raan_udeg < 360000000
            AND argument_of_latitude_udeg >= 0 AND argument_of_latitude_udeg < 360000000)))
  )
);

-- 6. GROUND_STATION subtype. Minimum elevation is deliberately absent here.
CREATE TABLE ground_station_revision (
  revision_id uuid PRIMARY KEY,
  profile_kind profile_kind NOT NULL DEFAULT 'GROUND_STATION' CHECK (profile_kind = 'GROUND_STATION'),
  latitude_udeg bigint,
  longitude_udeg bigint,
  ellipsoidal_height_mm bigint,
  rx_resource_key varchar(64) NOT NULL,
  FOREIGN KEY (revision_id, profile_kind) REFERENCES profile_revision(id, profile_kind) ON DELETE RESTRICT,
  CONSTRAINT gs_lat_ck CHECK (latitude_udeg IS NULL OR latitude_udeg BETWEEN -90000000 AND 90000000),
  CONSTRAINT gs_lon_ck CHECK (longitude_udeg IS NULL OR (longitude_udeg >= -180000000 AND longitude_udeg < 180000000)),
  CONSTRAINT gs_height_ck CHECK (ellipsoidal_height_mm IS NULL OR ellipsoidal_height_mm BETWEEN -500000 AND 100000000),
  CONSTRAINT gs_rx_key_ck CHECK (rx_resource_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$')
);

-- 7. COMMUNICATION subtype. Provider columns are mutually exclusive.
CREATE TABLE communication_revision (
  revision_id uuid PRIMARY KEY,
  profile_kind profile_kind NOT NULL DEFAULT 'COMMUNICATION' CHECK (profile_kind = 'COMMUNICATION'),
  provider_kind capacity_provider_kind NOT NULL,
  fixed_capacity_bytes numeric(20,0),
  rate_semantics rate_semantics,
  measurement_point varchar(96),
  rate_scope rate_scope,
  accounted_effects accounted_effect[] NOT NULL DEFAULT '{}',
  coding_efficiency_numerator numeric(39,0),
  coding_efficiency_denominator numeric(39,0),
  protocol_efficiency_numerator numeric(39,0),
  protocol_efficiency_denominator numeric(39,0),
  residual_efficiency_numerator numeric(39,0),
  residual_efficiency_denominator numeric(39,0),
  acquisition_guard_us bigint NOT NULL DEFAULT 0 CHECK (acquisition_guard_us >= 0),
  release_guard_us bigint NOT NULL DEFAULT 0 CHECK (release_guard_us >= 0),
  reserve_kind reserve_kind NOT NULL DEFAULT 'NONE',
  reserve_bytes numeric(20,0),
  capacity_accounting_layer varchar(32) NOT NULL DEFAULT 'LOGICAL_PAYLOAD' CHECK (capacity_accounting_layer = 'LOGICAL_PAYLOAD'),
  FOREIGN KEY (revision_id, profile_kind) REFERENCES profile_revision(id, profile_kind) ON DELETE RESTRICT,
  CONSTRAINT comm_provider_ck CHECK (
    (provider_kind = 'FIXED_RATE' AND fixed_capacity_bytes IS NULL
      AND ((rate_semantics IS NULL AND measurement_point IS NULL AND rate_scope IS NULL)
        OR (rate_semantics IS NOT NULL AND measurement_point IS NOT NULL AND rate_scope IS NOT NULL)))
    OR
    (provider_kind = 'FIXED_CAPACITY_PER_CONTACT' AND rate_semantics IS NULL
      AND measurement_point IS NULL AND rate_scope IS NULL
      AND coding_efficiency_numerator IS NULL AND coding_efficiency_denominator IS NULL
      AND protocol_efficiency_numerator IS NULL AND protocol_efficiency_denominator IS NULL
      AND residual_efficiency_numerator IS NULL AND residual_efficiency_denominator IS NULL
      AND (fixed_capacity_bytes IS NULL OR fixed_capacity_bytes >= 0))
  ),
  CONSTRAINT comm_factor_pair_ck CHECK (
    ((coding_efficiency_numerator IS NULL AND coding_efficiency_denominator IS NULL) OR
      (coding_efficiency_numerator >= 0 AND coding_efficiency_denominator > 0
       AND coding_efficiency_numerator <= coding_efficiency_denominator)) AND
    ((protocol_efficiency_numerator IS NULL AND protocol_efficiency_denominator IS NULL) OR
      (protocol_efficiency_numerator >= 0 AND protocol_efficiency_denominator > 0
       AND protocol_efficiency_numerator <= protocol_efficiency_denominator)) AND
    ((residual_efficiency_numerator IS NULL AND residual_efficiency_denominator IS NULL) OR
      (residual_efficiency_numerator >= 0 AND residual_efficiency_denominator > 0
       AND residual_efficiency_numerator <= residual_efficiency_denominator))
  ),
  CONSTRAINT comm_semantic_factor_ck CHECK (
    (rate_semantics IS NULL) OR
    (rate_semantics = 'APPLICATION_GOODPUT'
      AND coding_efficiency_numerator IS NULL AND protocol_efficiency_numerator IS NULL
      AND residual_efficiency_numerator IS NULL) OR
    (rate_semantics = 'NET_PAYLOAD_BITRATE_PRE_LOSS'
      AND coding_efficiency_numerator IS NULL AND protocol_efficiency_numerator IS NULL) OR
    (rate_semantics = 'CODED_BITRATE')
  ),
  CONSTRAINT comm_reserve_ck CHECK (
    (reserve_kind = 'NONE' AND reserve_bytes IS NULL) OR
    (reserve_kind = 'BYTE' AND reserve_bytes >= 0 AND provider_kind = 'FIXED_RATE') OR
    (reserve_kind = 'TIME' AND reserve_bytes IS NULL AND provider_kind = 'FIXED_RATE')
  ),
  CONSTRAINT comm_fixed_capacity_no_reduction_ck CHECK (
    provider_kind <> 'FIXED_CAPACITY_PER_CONTACT' OR
    (reserve_kind = 'NONE' AND acquisition_guard_us >= 0 AND release_guard_us >= 0)
  )
);

-- 8. Repeated exact rate and time-reserve segments on one communication timeline.
-- Offsets are relative to the modeled active-data interval; a RATE NULL end is an
-- open tail. Coverage/non-overlap/provider compatibility are publish invariants.
CREATE TABLE communication_timeline_segment (
  revision_id uuid NOT NULL REFERENCES communication_revision(revision_id) ON DELETE RESTRICT,
  segment_kind communication_segment_kind NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  start_offset_us bigint NOT NULL CHECK (start_offset_us >= 0),
  end_offset_us bigint,
  rate_numerator_bits numeric(39,0),
  rate_denominator_seconds numeric(39,0),
  PRIMARY KEY (revision_id, segment_kind, ordinal),
  UNIQUE (revision_id, segment_kind, start_offset_us),
  CONSTRAINT communication_segment_ck CHECK (
    (segment_kind = 'RATE'
      AND (end_offset_us IS NULL OR start_offset_us < end_offset_us)
      AND rate_numerator_bits >= 0 AND rate_denominator_seconds > 0)
    OR
    (segment_kind = 'TIME_RESERVE' AND end_offset_us IS NOT NULL
      AND start_offset_us < end_offset_us
      AND rate_numerator_bits IS NULL AND rate_denominator_seconds IS NULL)
  )
);

-- 9. PAYLOAD_TYPE subtype. Instance size and priority belong to scenario_payload.
CREATE TABLE payload_type_revision (
  revision_id uuid PRIMARY KEY,
  profile_kind profile_kind NOT NULL DEFAULT 'PAYLOAD_TYPE' CHECK (profile_kind = 'PAYLOAD_TYPE'),
  media_type varchar(127) NOT NULL,
  serializer_revision varchar(96) NOT NULL,
  segmentation segmentation_kind NOT NULL,
  fixed_chunk_bytes numeric(20,0),
  resume_allowed boolean NOT NULL DEFAULT false,
  partial_product_usable boolean NOT NULL DEFAULT false,
  completion_rule_revision varchar(96) NOT NULL,
  FOREIGN KEY (revision_id, profile_kind) REFERENCES profile_revision(id, profile_kind) ON DELETE RESTRICT,
  CONSTRAINT payload_type_chunk_ck CHECK (
    (segmentation = 'FIXED_CHUNK' AND fixed_chunk_bytes > 0) OR
    (segmentation <> 'FIXED_CHUNK' AND fixed_chunk_bytes IS NULL)
  ),
  CONSTRAINT payload_type_atomic_ck CHECK (segmentation <> 'ATOMIC_OBJECT' OR resume_allowed = false)
);

-- 10. POLICY subtype. Comparator/tie-break versions are immutable semantic input.
CREATE TABLE policy_revision (
  revision_id uuid PRIMARY KEY,
  profile_kind profile_kind NOT NULL DEFAULT 'POLICY' CHECK (profile_kind = 'POLICY'),
  policy_kind policy_kind NOT NULL,
  comparator_revision varchar(96) NOT NULL,
  objective_revision varchar(96) NOT NULL,
  tie_break_revision varchar(96) NOT NULL,
  starvation_guard starvation_guard_mode NOT NULL DEFAULT 'NOT_APPLICABLE',
  max_wait_us bigint,
  value_model_revision varchar(96),
  FOREIGN KEY (revision_id, profile_kind) REFERENCES profile_revision(id, profile_kind) ON DELETE RESTRICT,
  CONSTRAINT policy_mode_ck CHECK (
    (policy_kind <> 'VALUE_PER_BYTE' AND starvation_guard = 'NOT_APPLICABLE' AND max_wait_us IS NULL AND value_model_revision IS NULL) OR
    (policy_kind = 'VALUE_PER_BYTE' AND starvation_guard = 'ALLOW_STARVATION' AND max_wait_us IS NULL AND value_model_revision IS NOT NULL) OR
    (policy_kind = 'VALUE_PER_BYTE' AND starvation_guard = 'MAX_WAIT_PROMOTION' AND max_wait_us > 0 AND value_model_revision IS NOT NULL)
  )
);

-- 11. Field-level evidence for either a profile revision or a scenario revision.
-- owner_stable_key is '$' for the root or the typed child stable key.
CREATE TABLE evidence_assertion (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_revision_id uuid REFERENCES profile_revision(id) ON DELETE RESTRICT,
  scenario_revision_id uuid,
  owner_stable_key varchar(96) NOT NULL,
  field_code varchar(96) NOT NULL,
  presence_state presence_state NOT NULL,
  value_state value_state,
  evidence_state evidence_state,
  evidence_kind evidence_kind,
  source_revision_id uuid REFERENCES evidence_source_revision(id) ON DELETE RESTRICT,
  normalized_value_sha256 bytea,
  rationale varchar(1000),
  captured_at timestamptz,
  valid_from timestamptz,
  valid_to timestamptz,
  origin_kind origin_kind NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT evidence_one_owner_ck CHECK (num_nonnulls(profile_revision_id, scenario_revision_id) = 1),
  CONSTRAINT evidence_owner_key_ck CHECK (owner_stable_key = '$' OR owner_stable_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$'),
  CONSTRAINT evidence_field_code_ck CHECK (field_code ~ '^[A-Z][A-Z0-9_]{0,95}$'),
  CONSTRAINT evidence_hash_ck CHECK (normalized_value_sha256 IS NULL OR octet_length(normalized_value_sha256) = 32),
  CONSTRAINT evidence_validity_ck CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from < valid_to),
  CONSTRAINT evidence_state_combo_ck CHECK (
    (presence_state = 'OMITTED' AND value_state IS NULL AND evidence_state IS NULL
      AND evidence_kind IS NULL AND normalized_value_sha256 IS NULL)
    OR
    (presence_state IN ('PROVIDED','DEFAULTED') AND value_state = 'KNOWN'
      AND evidence_state IN ('CONFIRMED','PROVISIONAL','PROXY')
      AND evidence_kind IS NOT NULL AND normalized_value_sha256 IS NOT NULL)
    OR
    (presence_state = 'PROVIDED' AND value_state = 'UNKNOWN'
      AND evidence_state = 'UNKNOWN' AND normalized_value_sha256 IS NULL)
    OR
    (presence_state = 'PROVIDED' AND value_state = 'NOT_APPLICABLE'
      AND normalized_value_sha256 IS NULL)
  ),
  CONSTRAINT evidence_proxy_ck CHECK (
    evidence_state <> 'PROXY' OR (source_revision_id IS NOT NULL AND rationale IS NOT NULL)
  )
);

-- 12. Mutable scenario head. is_preset reuses the same cloneable revision mechanism.
CREATE TABLE scenario (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  stable_key varchar(64) NOT NULL UNIQUE,
  name varchar(160) NOT NULL,
  description varchar(1000),
  is_preset boolean NOT NULL DEFAULT false,
  current_revision_id uuid,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  archived_at timestamptz,
  CONSTRAINT scenario_stable_key_ck CHECK (stable_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$')
);

-- 13. Immutable scenario revision. Optional storage is colocated because it has one-to-one
-- lifecycle and access pattern with the scenario revision, not a separate catalog lifecycle.
CREATE TABLE scenario_revision (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scenario_id uuid NOT NULL REFERENCES scenario(id) ON DELETE RESTRICT,
  revision_no integer NOT NULL CHECK (revision_no > 0),
  lifecycle_status revision_status NOT NULL DEFAULT 'DRAFT',
  schema_version varchar(32) NOT NULL,
  based_on_revision_id uuid REFERENCES scenario_revision(id) ON DELETE RESTRICT,
  decision_question varchar(1000) NOT NULL,
  analysis_start timestamptz NOT NULL,
  analysis_end timestamptz NOT NULL,
  analysis_mode analysis_mode NOT NULL,
  spacecraft_revision_id uuid NOT NULL,
  spacecraft_profile_kind profile_kind NOT NULL DEFAULT 'SPACECRAFT' CHECK (spacecraft_profile_kind = 'SPACECRAFT'),
  orbit_revision_id uuid NOT NULL REFERENCES orbit_revision(revision_id) ON DELETE RESTRICT,
  policy_revision_id uuid REFERENCES policy_revision(revision_id) ON DELETE RESTRICT,
  storage_mode storage_model_mode NOT NULL DEFAULT 'DISABLED',
  physical_capacity_bytes numeric(20,0),
  protected_reserve_bytes numeric(20,0),
  initial_nonqueue_bytes numeric(20,0),
  reserve_enforcement reserve_enforcement,
  storage_admission_policy storage_admission_policy,
  reclaim_granularity reclaim_granularity,
  release_trigger release_trigger,
  delivery_assumption delivery_assumption,
  overlap_objective_revision varchar(96) NOT NULL,
  tie_break_profile_revision varchar(96) NOT NULL,
  event_order_revision varchar(96) NOT NULL,
  time_quantization_revision varchar(96) NOT NULL,
  display_format_revision varchar(96) NOT NULL,
  semantic_hash bytea,
  change_note varchar(1000),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  published_at timestamptz,
  UNIQUE (scenario_id, revision_no),
  UNIQUE (id, scenario_id),
  FOREIGN KEY (spacecraft_revision_id, spacecraft_profile_kind)
    REFERENCES profile_revision(id, profile_kind) ON DELETE RESTRICT,
  CONSTRAINT scenario_interval_ck CHECK (analysis_start < analysis_end),
  CONSTRAINT scenario_revision_hash_ck CHECK (semantic_hash IS NULL OR octet_length(semantic_hash) = 32),
  CONSTRAINT scenario_publish_ck CHECK (
    (lifecycle_status = 'DRAFT' AND published_at IS NULL) OR
    (lifecycle_status = 'PUBLISHED' AND published_at IS NOT NULL AND semantic_hash IS NOT NULL)
  ),
  CONSTRAINT scenario_mode_ck CHECK (
    (analysis_mode = 'NETWORK_ONLY' AND policy_revision_id IS NULL AND storage_mode = 'DISABLED') OR
    (analysis_mode = 'QUEUE_AWARE' AND policy_revision_id IS NOT NULL)
  ),
  CONSTRAINT scenario_storage_ck CHECK (
    (storage_mode = 'DISABLED' AND physical_capacity_bytes IS NULL AND protected_reserve_bytes IS NULL
      AND initial_nonqueue_bytes IS NULL AND reserve_enforcement IS NULL
      AND storage_admission_policy IS NULL AND reclaim_granularity IS NULL
      AND release_trigger IS NULL AND delivery_assumption IS NULL)
    OR
    (storage_mode = 'ENABLED' AND analysis_mode = 'QUEUE_AWARE'
      AND physical_capacity_bytes >= 0 AND protected_reserve_bytes >= 0
      AND protected_reserve_bytes <= physical_capacity_bytes
      AND initial_nonqueue_bytes >= 0 AND initial_nonqueue_bytes <= physical_capacity_bytes
      AND reserve_enforcement IS NOT NULL AND storage_admission_policy = 'REJECT_NEW'
      AND reclaim_granularity IS NOT NULL
      AND release_trigger IS NOT NULL AND delivery_assumption IS NOT NULL
      AND ((release_trigger = 'NEVER' AND delivery_assumption = 'NONE')
        OR (release_trigger = 'TX_END' AND delivery_assumption = 'TX_END_EQUALS_DELIVERED')))
  )
);

ALTER TABLE scenario
  ADD CONSTRAINT scenario_current_revision_fk
  FOREIGN KEY (current_revision_id, id)
  REFERENCES scenario_revision(id, scenario_id) ON DELETE RESTRICT
  DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE evidence_assertion
  ADD CONSTRAINT evidence_scenario_revision_fk
  FOREIGN KEY (scenario_revision_id) REFERENCES scenario_revision(id) ON DELETE RESTRICT;

-- 14. Scenario-specific station policy and link binding.
CREATE TABLE scenario_station (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scenario_revision_id uuid NOT NULL REFERENCES scenario_revision(id) ON DELETE RESTRICT,
  stable_key varchar(64) NOT NULL,
  ground_station_revision_id uuid NOT NULL REFERENCES ground_station_revision(revision_id) ON DELETE RESTRICT,
  communication_revision_id uuid REFERENCES communication_revision(revision_id) ON DELETE RESTRICT,
  minimum_elevation_udeg bigint,
  link_compatibility compatibility_status NOT NULL DEFAULT 'UNKNOWN',
  eligibility_valid_from timestamptz,
  eligibility_valid_to timestamptz,
  station_preference_rank integer CHECK (station_preference_rank IS NULL OR station_preference_rank >= 0),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (scenario_revision_id, stable_key),
  UNIQUE (scenario_revision_id, ground_station_revision_id),
  UNIQUE (scenario_revision_id, id),
  CONSTRAINT scenario_station_key_ck CHECK (stable_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'),
  CONSTRAINT scenario_station_elevation_ck CHECK (minimum_elevation_udeg IS NULL OR (minimum_elevation_udeg >= 0 AND minimum_elevation_udeg < 90000000)),
  CONSTRAINT scenario_station_validity_ck CHECK (
    (eligibility_valid_from IS NULL AND eligibility_valid_to IS NULL) OR
    (eligibility_valid_from IS NOT NULL AND eligibility_valid_to IS NOT NULL AND eligibility_valid_from < eligibility_valid_to)
  )
);

-- 15. Explicit payload instance for QUEUE_AWARE scenarios.
CREATE TABLE scenario_payload (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scenario_revision_id uuid NOT NULL REFERENCES scenario_revision(id) ON DELETE RESTRICT,
  stable_key varchar(64) NOT NULL,
  payload_type_revision_id uuid NOT NULL REFERENCES payload_type_revision(revision_id) ON DELETE RESTRICT,
  display_name varchar(160) NOT NULL,
  producer_kind producer_kind NOT NULL,
  producer_ref varchar(160),
  ready_at timestamptz NOT NULL,
  logical_size_bytes numeric(20,0),
  storage_footprint_bytes numeric(20,0),
  service_class service_class NOT NULL,
  mission_priority smallint NOT NULL CHECK (mission_priority BETWEEN 0 AND 100),
  queue_sequence bigint NOT NULL CHECK (queue_sequence >= 0),
  deadline_at timestamptz,
  deadline_target deadline_target,
  post_deadline_action post_deadline_action,
  expiry_at timestamptz,
  severity_rank smallint CHECK (severity_rank IS NULL OR severity_rank BETWEEN 0 AND 100),
  value_score_numerator numeric(39,0),
  value_score_denominator numeric(39,0),
  bundle_key varchar(64),
  bundle_member_role bundle_member_role,
  initial_storage_state initial_storage_state NOT NULL DEFAULT 'GENERATED_AT_READY',
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (scenario_revision_id, stable_key),
  UNIQUE (scenario_revision_id, queue_sequence),
  UNIQUE (scenario_revision_id, id),
  CONSTRAINT scenario_payload_key_ck CHECK (stable_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'),
  CONSTRAINT scenario_payload_size_ck CHECK (logical_size_bytes IS NULL OR logical_size_bytes >= 0),
  CONSTRAINT scenario_payload_storage_ck CHECK (storage_footprint_bytes IS NULL OR storage_footprint_bytes >= 0),
  CONSTRAINT scenario_payload_deadline_ck CHECK (
    (deadline_at IS NULL AND deadline_target IS NULL AND post_deadline_action IS NULL) OR
    (deadline_at IS NOT NULL AND deadline_target IS NOT NULL AND post_deadline_action IS NOT NULL)
  ),
  CONSTRAINT scenario_payload_expiry_ck CHECK (expiry_at IS NULL OR ready_at < expiry_at),
  CONSTRAINT scenario_payload_value_ck CHECK (
    (value_score_numerator IS NULL AND value_score_denominator IS NULL) OR
    (value_score_numerator >= 0 AND value_score_denominator > 0)
  ),
  CONSTRAINT scenario_payload_bundle_ck CHECK (
    (bundle_key IS NULL AND bundle_member_role IS NULL) OR
    (bundle_key IS NOT NULL AND bundle_member_role IS NOT NULL)
  )
);

-- 16. Repeated dependency edges; cycle detection is a publish/snapshot service invariant.
CREATE TABLE payload_dependency (
  scenario_revision_id uuid NOT NULL,
  predecessor_payload_id uuid NOT NULL,
  successor_payload_id uuid NOT NULL,
  dependency_kind dependency_kind NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (scenario_revision_id, predecessor_payload_id, successor_payload_id, dependency_kind),
  FOREIGN KEY (scenario_revision_id, predecessor_payload_id)
    REFERENCES scenario_payload(scenario_revision_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (scenario_revision_id, successor_payload_id)
    REFERENCES scenario_payload(scenario_revision_id, id) ON DELETE RESTRICT,
  CONSTRAINT payload_dependency_self_ck CHECK (predecessor_payload_id <> successor_payload_id)
);

-- 17. Immutable calculator/environment contract.
CREATE TABLE engine_manifest (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  stable_key varchar(96) NOT NULL UNIQUE,
  engine_version varchar(96) NOT NULL,
  code_revision varchar(96) NOT NULL,
  orbit_provider_revision varchar(96) NOT NULL,
  capacity_engine_revision varchar(96) NOT NULL,
  scheduler_revision varchar(96) NOT NULL,
  storage_reducer_revision varchar(96) NOT NULL,
  constants_revision varchar(96) NOT NULL,
  time_reference_revision varchar(96) NOT NULL,
  frame_transform_revision varchar(96) NOT NULL,
  event_solver_revision varchar(96) NOT NULL,
  canonicalization_revision varchar(96) NOT NULL,
  manifest_sha256 bytea NOT NULL CHECK (octet_length(manifest_sha256) = 32),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- 18. Immutable, self-contained input artifact. canonical_bytes is authoritative for hashing;
-- canonical_payload is a schema-validated inspection copy and never replaces typed rows.
CREATE TABLE input_snapshot (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scenario_revision_id uuid NOT NULL REFERENCES scenario_revision(id) ON DELETE RESTRICT,
  schema_version varchar(32) NOT NULL,
  json_schema_id varchar(128) NOT NULL,
  canonicalization_revision varchar(96) NOT NULL,
  canonical_payload jsonb NOT NULL CHECK (jsonb_typeof(canonical_payload) = 'object'),
  canonical_bytes bytea NOT NULL,
  content_sha256 bytea NOT NULL CHECK (octet_length(content_sha256) = 32),
  validation_status snapshot_validation_status NOT NULL,
  validation_code varchar(96),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (content_sha256, canonicalization_revision),
  CONSTRAINT input_snapshot_validation_ck CHECK (
    (validation_status = 'VALID' AND validation_code IS NULL) OR
    (validation_status = 'INVALID' AND validation_code IS NOT NULL)
  )
);

-- 19. Run identity/state. Terminal runs are immutable and retained.
CREATE TABLE scenario_run (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  input_snapshot_id uuid NOT NULL REFERENCES input_snapshot(id) ON DELETE RESTRICT,
  engine_manifest_id uuid NOT NULL REFERENCES engine_manifest(id) ON DELETE RESTRICT,
  replay_of_run_id uuid REFERENCES scenario_run(id) ON DELETE RESTRICT,
  status run_status NOT NULL DEFAULT 'QUEUED',
  retention_class retention_class NOT NULL DEFAULT 'STANDARD',
  requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  started_at timestamptz,
  finished_at timestamptz,
  terminal_stage_code varchar(64),
  error_code varchar(96),
  result_content_hash bytea,
  run_record_hash bytea,
  CONSTRAINT scenario_run_time_ck CHECK (
    (started_at IS NULL OR requested_at <= started_at) AND
    (finished_at IS NULL OR (started_at IS NOT NULL AND started_at <= finished_at))
  ),
  CONSTRAINT scenario_run_hash_ck CHECK (
    (result_content_hash IS NULL OR octet_length(result_content_hash) = 32) AND
    (run_record_hash IS NULL OR octet_length(run_record_hash) = 32)
  ),
  CONSTRAINT scenario_run_terminal_ck CHECK (
    (status IN ('QUEUED','RUNNING') AND finished_at IS NULL AND run_record_hash IS NULL) OR
    (status IN ('SUCCEEDED','PARTIAL') AND finished_at IS NOT NULL
      AND terminal_stage_code IS NOT NULL AND result_content_hash IS NOT NULL AND run_record_hash IS NOT NULL) OR
    (status IN ('FAILED','INVALID') AND finished_at IS NOT NULL
      AND terminal_stage_code IS NOT NULL AND error_code IS NOT NULL AND run_record_hash IS NOT NULL)
  )
);

-- 20. Per-stage state preserves partial successes.
CREATE TABLE run_stage (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES scenario_run(id) ON DELETE RESTRICT,
  stage_code varchar(64) NOT NULL,
  stage_ordinal smallint NOT NULL CHECK (stage_ordinal >= 0),
  status stage_status NOT NULL DEFAULT 'PENDING',
  started_at timestamptz,
  finished_at timestamptz,
  produced_row_count bigint CHECK (produced_row_count IS NULL OR produced_row_count >= 0),
  error_code varchar(96),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (run_id, stage_code),
  UNIQUE (run_id, stage_ordinal),
  CONSTRAINT run_stage_time_ck CHECK (finished_at IS NULL OR (started_at IS NOT NULL AND started_at <= finished_at)),
  CONSTRAINT run_stage_state_ck CHECK (
    (status = 'PENDING' AND started_at IS NULL AND finished_at IS NULL) OR
    (status = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL) OR
    (status IN ('SUCCEEDED','BLOCKED','FAILED','INVALID','NOT_APPLICABLE') AND finished_at IS NOT NULL)
  )
);

-- 21. Common result identity/status root. Stable keys, not UUIDs, enter canonical result hashes.
CREATE TABLE run_result (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES scenario_run(id) ON DELETE RESTRICT,
  stable_key varchar(128) NOT NULL,
  result_kind result_kind NOT NULL,
  calculation_status calculation_status NOT NULL,
  decision_grade decision_grade,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (run_id, stable_key),
  UNIQUE (id, result_kind),
  UNIQUE (id, run_id),
  CONSTRAINT run_result_key_ck CHECK (stable_key ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'),
  CONSTRAINT run_result_status_grade_ck CHECK (
    (calculation_status IN ('COMPUTED','KNOWN_ZERO') AND decision_grade IN ('VERIFIED','ENGINEERING_ESTIMATE','CONCEPT_ONLY')) OR
    (calculation_status = 'BLOCKED' AND decision_grade = 'BLOCKED') OR
    (calculation_status IN ('INVALID','NOT_APPLICABLE') AND decision_grade IS NULL)
  )
);

-- 22. Pure geometric access. [true_aos,true_los) and clipped interval are explicit.
CREATE TABLE geometric_access (
  result_id uuid PRIMARY KEY,
  result_kind result_kind NOT NULL DEFAULT 'GEOMETRIC_ACCESS' CHECK (result_kind = 'GEOMETRIC_ACCESS'),
  scenario_station_id uuid NOT NULL REFERENCES scenario_station(id) ON DELETE RESTRICT,
  true_aos timestamptz NOT NULL,
  true_los timestamptz NOT NULL,
  clipped_start timestamptz NOT NULL,
  clipped_end timestamptz NOT NULL,
  maximum_elevation_udeg bigint NOT NULL CHECK (maximum_elevation_udeg BETWEEN 0 AND 90000000),
  maximum_elevation_at timestamptz NOT NULL,
  FOREIGN KEY (result_id, result_kind) REFERENCES run_result(id, result_kind) ON DELETE RESTRICT,
  CONSTRAINT geometric_true_interval_ck CHECK (true_aos < true_los),
  CONSTRAINT geometric_clipped_interval_ck CHECK (
    clipped_start < clipped_end AND true_aos <= clipped_start AND clipped_end <= true_los
  ),
  CONSTRAINT geometric_peak_time_ck CHECK (true_aos <= maximum_elevation_at AND maximum_elevation_at < true_los)
);

-- 23. Guard/eligibility-applied contact. Null interval is permitted only for non-computed roots,
-- checked again by the service's result validator.
CREATE TABLE modeled_contact (
  result_id uuid PRIMARY KEY,
  result_kind result_kind NOT NULL DEFAULT 'MODELED_CONTACT' CHECK (result_kind = 'MODELED_CONTACT'),
  geometric_result_id uuid NOT NULL UNIQUE REFERENCES geometric_access(result_id) ON DELETE RESTRICT,
  link_compatibility compatibility_status NOT NULL,
  usable_start timestamptz,
  usable_end timestamptz,
  primary_reason_code varchar(96),
  FOREIGN KEY (result_id, result_kind) REFERENCES run_result(id, result_kind) ON DELETE RESTRICT,
  CONSTRAINT modeled_interval_ck CHECK (
    (usable_start IS NULL AND usable_end IS NULL) OR
    (usable_start IS NOT NULL AND usable_end IS NOT NULL AND usable_start < usable_end)
  )
);

-- 24. Conflict-before capacity. The only authoritative per-contact logical capacity value.
CREATE TABLE candidate_session (
  result_id uuid PRIMARY KEY,
  result_kind result_kind NOT NULL DEFAULT 'CANDIDATE_SESSION' CHECK (result_kind = 'CANDIDATE_SESSION'),
  modeled_contact_result_id uuid NOT NULL UNIQUE REFERENCES modeled_contact(result_id) ON DELETE RESTRICT,
  capacity_bytes numeric(20,0),
  conflict_component_key varchar(96),
  FOREIGN KEY (result_id, result_kind) REFERENCES run_result(id, result_kind) ON DELETE RESTRICT,
  CONSTRAINT candidate_capacity_ck CHECK (capacity_bytes IS NULL OR capacity_bytes >= 0),
  CONSTRAINT candidate_conflict_key_ck CHECK (
    conflict_component_key IS NULL OR conflict_component_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$'
  )
);

-- 25. A selected whole opportunity. Capacity is intentionally not copied from candidate_session.
CREATE TABLE scheduled_session (
  result_id uuid PRIMARY KEY,
  result_kind result_kind NOT NULL DEFAULT 'SCHEDULED_SESSION' CHECK (result_kind = 'SCHEDULED_SESSION'),
  candidate_result_id uuid NOT NULL UNIQUE REFERENCES candidate_session(result_id) ON DELETE RESTRICT,
  selection_ordinal integer NOT NULL CHECK (selection_ordinal >= 0),
  primary_reason_code varchar(96) NOT NULL,
  FOREIGN KEY (result_id, result_kind) REFERENCES run_result(id, result_kind) ON DELETE RESTRICT
);

-- 26. Planned logical-byte allocation; no observed/received byte exists in P0.
CREATE TABLE transfer_allocation (
  result_id uuid PRIMARY KEY,
  result_kind result_kind NOT NULL DEFAULT 'TRANSFER_ALLOCATION' CHECK (result_kind = 'TRANSFER_ALLOCATION'),
  scheduled_session_result_id uuid NOT NULL REFERENCES scheduled_session(result_id) ON DELETE RESTRICT,
  scenario_payload_id uuid NOT NULL REFERENCES scenario_payload(id) ON DELETE RESTRICT,
  allocation_ordinal integer NOT NULL CHECK (allocation_ordinal >= 0),
  logical_offset_start numeric(20,0) NOT NULL CHECK (logical_offset_start >= 0),
  logical_bytes numeric(20,0) NOT NULL CHECK (logical_bytes > 0),
  started_at timestamptz NOT NULL,
  ended_at timestamptz NOT NULL,
  modeled_progress_after_bytes numeric(20,0) NOT NULL CHECK (modeled_progress_after_bytes >= 0),
  modeled_tx_complete_at timestamptz,
  deadline_status varchar(32),
  remaining_after_bytes numeric(20,0) NOT NULL CHECK (remaining_after_bytes >= 0),
  primary_reason_code varchar(96) NOT NULL,
  FOREIGN KEY (result_id, result_kind) REFERENCES run_result(id, result_kind) ON DELETE RESTRICT,
  UNIQUE (scheduled_session_result_id, allocation_ordinal),
  CONSTRAINT allocation_interval_ck CHECK (started_at < ended_at),
  CONSTRAINT allocation_complete_time_ck CHECK (
    modeled_tx_complete_at IS NULL OR (started_at < modeled_tx_complete_at AND modeled_tx_complete_at <= ended_at)
  )
);

-- 27. Shared queue/storage envelope with typed byte ledgers. Event order is total per run/time.
CREATE TABLE run_event (
  result_id uuid PRIMARY KEY,
  result_kind result_kind NOT NULL DEFAULT 'RUN_EVENT' CHECK (result_kind = 'RUN_EVENT'),
  run_id uuid NOT NULL,
  event_at timestamptz NOT NULL,
  event_order integer NOT NULL CHECK (event_order >= 0),
  event_domain event_domain NOT NULL,
  event_kind varchar(64) NOT NULL,
  scenario_payload_id uuid REFERENCES scenario_payload(id) ON DELETE RESTRICT,
  allocation_result_id uuid REFERENCES transfer_allocation(result_id) ON DELETE RESTRICT,
  delta_logical_bytes numeric(20,0),
  remaining_logical_bytes numeric(20,0),
  delta_storage_bytes numeric(20,0),
  occupancy_bytes numeric(20,0),
  reserve_breach_bytes numeric(20,0),
  rejected_bytes numeric(20,0),
  reason_code varchar(96) NOT NULL,
  FOREIGN KEY (result_id, result_kind) REFERENCES run_result(id, result_kind) ON DELETE RESTRICT,
  FOREIGN KEY (result_id, run_id) REFERENCES run_result(id, run_id) ON DELETE RESTRICT,
  UNIQUE (run_id, event_at, event_order),
  CONSTRAINT event_nonnegative_state_ck CHECK (
    (remaining_logical_bytes IS NULL OR remaining_logical_bytes >= 0) AND
    (occupancy_bytes IS NULL OR occupancy_bytes >= 0) AND
    (reserve_breach_bytes IS NULL OR reserve_breach_bytes >= 0) AND
    (rejected_bytes IS NULL OR rejected_bytes >= 0)
  ),
  CONSTRAINT event_domain_fields_ck CHECK (
    (event_domain = 'QUEUE' AND delta_storage_bytes IS NULL AND occupancy_bytes IS NULL
      AND reserve_breach_bytes IS NULL AND rejected_bytes IS NULL)
    OR
    (event_domain = 'STORAGE' AND delta_logical_bytes IS NULL AND remaining_logical_bytes IS NULL)
  )
);

-- 28. Versioned materialized KPI for fast UI/comparison. Numeric values are exact integers.
CREATE TABLE run_metric (
  result_id uuid PRIMARY KEY,
  result_kind result_kind NOT NULL DEFAULT 'METRIC' CHECK (result_kind = 'METRIC'),
  metric_code varchar(96) NOT NULL,
  scope_code varchar(64) NOT NULL,
  scenario_station_id uuid REFERENCES scenario_station(id) ON DELETE RESTRICT,
  scenario_payload_id uuid REFERENCES scenario_payload(id) ON DELETE RESTRICT,
  unit_code varchar(32) NOT NULL,
  definition_revision varchar(96) NOT NULL,
  accounting_layer varchar(32),
  value_integer numeric(39,0),
  FOREIGN KEY (result_id, result_kind) REFERENCES run_result(id, result_kind) ON DELETE RESTRICT,
  CONSTRAINT metric_code_ck CHECK (metric_code ~ '^[A-Z][A-Z0-9_]{0,95}$'),
  CONSTRAINT metric_scope_ck CHECK (scope_code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
  CONSTRAINT metric_one_dimension_ck CHECK (num_nonnulls(scenario_station_id, scenario_payload_id) <= 1)
);

-- 29. Warning and decision-reason rows share an envelope; compared_result_id is a real FK.
-- Repeated criteria/reason codes are repeated rows, not a JSON array.
CREATE TABLE run_annotation (
  result_id uuid PRIMARY KEY,
  result_kind result_kind NOT NULL DEFAULT 'ANNOTATION' CHECK (result_kind = 'ANNOTATION'),
  subject_result_id uuid REFERENCES run_result(id) ON DELETE RESTRICT,
  annotation_kind annotation_kind NOT NULL,
  code varchar(96) NOT NULL,
  severity annotation_severity NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  rule_revision varchar(96) NOT NULL,
  compared_result_id uuid REFERENCES run_result(id) ON DELETE RESTRICT,
  criterion_code varchar(96),
  criterion_value_integer numeric(39,0),
  criterion_value_text varchar(256),
  unit_code varchar(32),
  message varchar(1000),
  FOREIGN KEY (result_id, result_kind) REFERENCES run_result(id, result_kind) ON DELETE RESTRICT,
  CONSTRAINT annotation_criterion_ck CHECK (
    num_nonnulls(criterion_value_integer, criterion_value_text) <= 1
  )
);

-- 30. Cross-aggregate security/audit record with validated nullable FKs (not a polymorphic string FK).
CREATE TABLE audit_event (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  action_code varchar(64) NOT NULL,
  evidence_source_id uuid REFERENCES evidence_source(id) ON DELETE RESTRICT,
  profile_id uuid REFERENCES profile(id) ON DELETE RESTRICT,
  scenario_id uuid REFERENCES scenario(id) ON DELETE RESTRICT,
  run_id uuid REFERENCES scenario_run(id) ON DELETE RESTRICT,
  actor_ref varchar(128) NOT NULL,
  reason varchar(1000) NOT NULL,
  request_id uuid,
  previous_state varchar(64),
  new_state varchar(64),
  event_sha256 bytea NOT NULL CHECK (octet_length(event_sha256) = 32),
  CONSTRAINT audit_one_subject_ck CHECK (num_nonnulls(evidence_source_id, profile_id, scenario_id, run_id) = 1),
  CONSTRAINT audit_action_ck CHECK (action_code ~ '^[A-Z][A-Z0-9_]{0,63}$')
);

-- Lookup/history indexes.
CREATE INDEX profile_kind_active_idx ON profile(kind, is_preset, name) WHERE archived_at IS NULL;
CREATE INDEX profile_revision_history_idx ON profile_revision(profile_id, revision_no DESC);
CREATE INDEX source_revision_history_idx ON evidence_source_revision(source_id, revision_no DESC);
CREATE INDEX evidence_profile_lookup_idx ON evidence_assertion(profile_revision_id, owner_stable_key, field_code)
  WHERE profile_revision_id IS NOT NULL;
CREATE INDEX evidence_scenario_lookup_idx ON evidence_assertion(scenario_revision_id, owner_stable_key, field_code)
  WHERE scenario_revision_id IS NOT NULL;
CREATE INDEX scenario_active_idx ON scenario(is_preset, name) WHERE archived_at IS NULL;
CREATE INDEX scenario_revision_history_idx ON scenario_revision(scenario_id, revision_no DESC);
CREATE INDEX scenario_station_load_idx ON scenario_station(scenario_revision_id, stable_key);
CREATE INDEX scenario_payload_ready_idx ON scenario_payload(scenario_revision_id, ready_at, queue_sequence);
CREATE INDEX payload_dependency_successor_idx ON payload_dependency(scenario_revision_id, successor_payload_id);
CREATE INDEX snapshot_scenario_idx ON input_snapshot(scenario_revision_id, created_at DESC);
CREATE INDEX run_snapshot_idx ON scenario_run(input_snapshot_id, requested_at DESC);
CREATE INDEX run_status_idx ON scenario_run(status, requested_at DESC);
CREATE INDEX run_stage_run_idx ON run_stage(run_id, stage_ordinal);
CREATE INDEX result_run_kind_idx ON run_result(run_id, result_kind, stable_key);
CREATE INDEX geometric_station_time_idx ON geometric_access(scenario_station_id, true_aos);
CREATE INDEX modeled_geometric_idx ON modeled_contact(geometric_result_id);
CREATE INDEX candidate_modeled_idx ON candidate_session(modeled_contact_result_id);
CREATE INDEX candidate_conflict_idx ON candidate_session(conflict_component_key) WHERE conflict_component_key IS NOT NULL;
CREATE INDEX scheduled_candidate_idx ON scheduled_session(candidate_result_id);
CREATE INDEX allocation_session_idx ON transfer_allocation(scheduled_session_result_id, allocation_ordinal);
CREATE INDEX allocation_payload_idx ON transfer_allocation(scenario_payload_id, started_at);
CREATE INDEX event_run_timeline_idx ON run_event(run_id, event_at, event_order);
CREATE INDEX event_payload_idx ON run_event(scenario_payload_id, event_at) WHERE scenario_payload_id IS NOT NULL;
CREATE INDEX metric_compare_idx ON run_metric(metric_code, definition_revision, unit_code, scope_code);
CREATE INDEX metric_station_idx ON run_metric(scenario_station_id, metric_code) WHERE scenario_station_id IS NOT NULL;
CREATE INDEX metric_payload_idx ON run_metric(scenario_payload_id, metric_code) WHERE scenario_payload_id IS NOT NULL;
CREATE INDEX annotation_subject_idx ON run_annotation(subject_result_id, ordinal) WHERE subject_result_id IS NOT NULL;
CREATE INDEX audit_subject_time_idx ON audit_event(occurred_at DESC);

-- Generic immutability helpers.
CREATE FUNCTION reject_update_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION reject_hard_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% must be archived/tombstoned, not deleted', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER evidence_source_no_delete BEFORE DELETE ON evidence_source
  FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
CREATE TRIGGER profile_no_delete BEFORE DELETE ON profile
  FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
CREATE TRIGGER scenario_no_delete BEFORE DELETE ON scenario
  FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();

CREATE FUNCTION guard_profile_head_update() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_status revision_status;
BEGIN
  IF NEW.id <> OLD.id OR NEW.stable_key <> OLD.stable_key OR NEW.kind <> OLD.kind THEN
    RAISE EXCEPTION 'profile identity and kind are immutable' USING ERRCODE = '55000';
  END IF;
  IF NEW.current_revision_id IS NOT NULL AND NEW.current_revision_id IS DISTINCT FROM OLD.current_revision_id THEN
    SELECT lifecycle_status INTO v_status FROM profile_revision
    WHERE id = NEW.current_revision_id AND profile_id = NEW.id;
    IF v_status IS DISTINCT FROM 'PUBLISHED' THEN
      RAISE EXCEPTION 'current profile revision must be a published revision of the same head' USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER profile_head_update_guard BEFORE UPDATE ON profile
  FOR EACH ROW EXECUTE FUNCTION guard_profile_head_update();

CREATE FUNCTION guard_scenario_head_update() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_status revision_status;
BEGIN
  IF NEW.id <> OLD.id OR NEW.stable_key <> OLD.stable_key OR NEW.is_preset <> OLD.is_preset THEN
    RAISE EXCEPTION 'scenario identity and preset class are immutable' USING ERRCODE = '55000';
  END IF;
  IF NEW.current_revision_id IS NOT NULL AND NEW.current_revision_id IS DISTINCT FROM OLD.current_revision_id THEN
    SELECT lifecycle_status INTO v_status FROM scenario_revision
    WHERE id = NEW.current_revision_id AND scenario_id = NEW.id;
    IF v_status IS DISTINCT FROM 'PUBLISHED' THEN
      RAISE EXCEPTION 'current scenario revision must be a published revision of the same head' USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER scenario_head_update_guard BEFORE UPDATE ON scenario
  FOR EACH ROW EXECUTE FUNCTION guard_scenario_head_update();

CREATE FUNCTION guard_source_head_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.id <> OLD.id OR NEW.stable_key <> OLD.stable_key OR NEW.source_kind <> OLD.source_kind THEN
    RAISE EXCEPTION 'source identity and kind are immutable' USING ERRCODE = '55000';
  END IF;
  IF OLD.status = 'TOMBSTONED' AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'tombstoned source is immutable' USING ERRCODE = '55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER source_head_update_guard BEFORE UPDATE ON evidence_source
  FOR EACH ROW EXECUTE FUNCTION guard_source_head_update();

CREATE TRIGGER source_revision_immutable BEFORE UPDATE OR DELETE ON evidence_source_revision
  FOR EACH ROW EXECUTE FUNCTION reject_update_delete();
CREATE TRIGGER engine_manifest_immutable BEFORE UPDATE OR DELETE ON engine_manifest
  FOR EACH ROW EXECUTE FUNCTION reject_update_delete();
CREATE TRIGGER input_snapshot_immutable BEFORE UPDATE OR DELETE ON input_snapshot
  FOR EACH ROW EXECUTE FUNCTION reject_update_delete();
CREATE TRIGGER audit_event_immutable BEFORE UPDATE OR DELETE ON audit_event
  FOR EACH ROW EXECUTE FUNCTION reject_update_delete();

CREATE FUNCTION require_initial_draft() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.lifecycle_status <> 'DRAFT' THEN
    RAISE EXCEPTION '% must be inserted as DRAFT and then published', TG_TABLE_NAME USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER profile_revision_initial_draft BEFORE INSERT ON profile_revision
  FOR EACH ROW EXECUTE FUNCTION require_initial_draft();
CREATE TRIGGER scenario_revision_initial_draft BEFORE INSERT ON scenario_revision
  FOR EACH ROW EXECUTE FUNCTION require_initial_draft();

-- A published revision and all of its typed/evidence/child rows are immutable.
CREATE FUNCTION guard_profile_revision_parent() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.lifecycle_status = 'PUBLISHED' THEN
    RAISE EXCEPTION 'published profile revision % is immutable', OLD.id USING ERRCODE = '55000';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE FUNCTION guard_profile_revision_child() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_revision_id uuid; v_status revision_status;
BEGIN
  v_revision_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.revision_id ELSE NEW.revision_id END;
  SELECT lifecycle_status INTO v_status FROM profile_revision WHERE id = v_revision_id;
  IF v_status = 'PUBLISHED' THEN
    RAISE EXCEPTION 'child of published profile revision % is immutable', v_revision_id USING ERRCODE = '55000';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE TRIGGER profile_revision_published_guard BEFORE UPDATE OR DELETE ON profile_revision
  FOR EACH ROW EXECUTE FUNCTION guard_profile_revision_parent();
CREATE TRIGGER orbit_revision_guard BEFORE INSERT OR UPDATE OR DELETE ON orbit_revision
  FOR EACH ROW EXECUTE FUNCTION guard_profile_revision_child();
CREATE TRIGGER ground_station_revision_guard BEFORE INSERT OR UPDATE OR DELETE ON ground_station_revision
  FOR EACH ROW EXECUTE FUNCTION guard_profile_revision_child();
CREATE TRIGGER communication_revision_guard BEFORE INSERT OR UPDATE OR DELETE ON communication_revision
  FOR EACH ROW EXECUTE FUNCTION guard_profile_revision_child();
CREATE TRIGGER communication_timeline_segment_guard BEFORE INSERT OR UPDATE OR DELETE ON communication_timeline_segment
  FOR EACH ROW EXECUTE FUNCTION guard_profile_revision_child();
CREATE TRIGGER payload_type_revision_guard BEFORE INSERT OR UPDATE OR DELETE ON payload_type_revision
  FOR EACH ROW EXECUTE FUNCTION guard_profile_revision_child();
CREATE TRIGGER policy_revision_guard BEFORE INSERT OR UPDATE OR DELETE ON policy_revision
  FOR EACH ROW EXECUTE FUNCTION guard_profile_revision_child();

CREATE FUNCTION guard_scenario_revision_parent() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.lifecycle_status = 'PUBLISHED' THEN
    RAISE EXCEPTION 'published scenario revision % is immutable', OLD.id USING ERRCODE = '55000';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE FUNCTION guard_scenario_child() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_revision_id uuid; v_status revision_status;
BEGIN
  v_revision_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.scenario_revision_id ELSE NEW.scenario_revision_id END;
  SELECT lifecycle_status INTO v_status FROM scenario_revision WHERE id = v_revision_id;
  IF v_status = 'PUBLISHED' THEN
    RAISE EXCEPTION 'child of published scenario revision % is immutable', v_revision_id USING ERRCODE = '55000';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE TRIGGER scenario_revision_published_guard BEFORE UPDATE OR DELETE ON scenario_revision
  FOR EACH ROW EXECUTE FUNCTION guard_scenario_revision_parent();
CREATE TRIGGER scenario_station_guard BEFORE INSERT OR UPDATE OR DELETE ON scenario_station
  FOR EACH ROW EXECUTE FUNCTION guard_scenario_child();
CREATE TRIGGER scenario_payload_guard BEFORE INSERT OR UPDATE OR DELETE ON scenario_payload
  FOR EACH ROW EXECUTE FUNCTION guard_scenario_child();
CREATE TRIGGER payload_dependency_guard BEFORE INSERT OR UPDATE OR DELETE ON payload_dependency
  FOR EACH ROW EXECUTE FUNCTION guard_scenario_child();

-- Evidence assertions inherit their owner's revision immutability.
CREATE FUNCTION guard_evidence_assertion() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_profile uuid; v_scenario uuid; v_p_status revision_status; v_s_status revision_status;
BEGIN
  v_profile := CASE WHEN TG_OP = 'DELETE' THEN OLD.profile_revision_id ELSE NEW.profile_revision_id END;
  v_scenario := CASE WHEN TG_OP = 'DELETE' THEN OLD.scenario_revision_id ELSE NEW.scenario_revision_id END;
  IF v_profile IS NOT NULL THEN
    SELECT lifecycle_status INTO v_p_status FROM profile_revision WHERE id = v_profile;
    IF v_p_status = 'PUBLISHED' THEN
      RAISE EXCEPTION 'evidence of published profile revision is immutable' USING ERRCODE = '55000';
    END IF;
  ELSE
    SELECT lifecycle_status INTO v_s_status FROM scenario_revision WHERE id = v_scenario;
    IF v_s_status = 'PUBLISHED' THEN
      RAISE EXCEPTION 'evidence of published scenario revision is immutable' USING ERRCODE = '55000';
    END IF;
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;
CREATE TRIGGER evidence_assertion_guard BEFORE INSERT OR UPDATE OR DELETE ON evidence_assertion
  FOR EACH ROW EXECUTE FUNCTION guard_evidence_assertion();

-- Run state machine and terminal immutability.
CREATE FUNCTION require_initial_queued_run() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status <> 'QUEUED' OR NEW.started_at IS NOT NULL OR NEW.finished_at IS NOT NULL THEN
    RAISE EXCEPTION 'run must be inserted in QUEUED state' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER scenario_run_initial_queued BEFORE INSERT ON scenario_run
  FOR EACH ROW EXECUTE FUNCTION require_initial_queued_run();

CREATE FUNCTION guard_run_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status IN ('SUCCEEDED','PARTIAL','FAILED','INVALID') THEN
    IF OLD.retention_class = 'STANDARD' AND NEW.retention_class = 'BASELINE'
       AND (to_jsonb(NEW) - 'retention_class') = (to_jsonb(OLD) - 'retention_class') THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'terminal run % is immutable', OLD.id USING ERRCODE = '55000';
  END IF;
  IF NOT (
    (OLD.status = 'QUEUED' AND NEW.status IN ('QUEUED','RUNNING','FAILED','INVALID')) OR
    (OLD.status = 'RUNNING' AND NEW.status IN ('RUNNING','SUCCEEDED','PARTIAL','FAILED','INVALID'))
  ) THEN
    RAISE EXCEPTION 'invalid run transition % -> %', OLD.status, NEW.status USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER scenario_run_transition_guard BEFORE UPDATE ON scenario_run
  FOR EACH ROW EXECUTE FUNCTION guard_run_transition();
CREATE TRIGGER scenario_run_no_delete BEFORE DELETE ON scenario_run
  FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();

CREATE FUNCTION guard_run_stage_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_run_id uuid; v_status run_status;
BEGIN
  v_run_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.run_id ELSE NEW.run_id END;
  SELECT status INTO v_status FROM scenario_run WHERE id = v_run_id;
  IF v_status IN ('SUCCEEDED','PARTIAL','FAILED','INVALID') THEN
    RAISE EXCEPTION 'stage of terminal run % is immutable', v_run_id USING ERRCODE = '55000';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;
CREATE TRIGGER run_stage_terminal_guard BEFORE INSERT OR UPDATE OR DELETE ON run_stage
  FOR EACH ROW EXECUTE FUNCTION guard_run_stage_mutation();

CREATE FUNCTION guard_run_result_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_status run_status;
BEGIN
  SELECT status INTO v_status FROM scenario_run WHERE id = NEW.run_id;
  IF v_status <> 'RUNNING' THEN
    RAISE EXCEPTION 'results may be appended only to RUNNING run %', NEW.run_id USING ERRCODE = '55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER run_result_insert_guard BEFORE INSERT ON run_result
  FOR EACH ROW EXECUTE FUNCTION guard_run_result_insert();
CREATE TRIGGER run_result_immutable BEFORE UPDATE OR DELETE ON run_result
  FOR EACH ROW EXECUTE FUNCTION reject_update_delete();

CREATE FUNCTION guard_result_child_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_result_id uuid; v_status run_status;
BEGIN
  v_result_id := NEW.result_id;
  SELECT sr.status INTO v_status
  FROM run_result rr JOIN scenario_run sr ON sr.id = rr.run_id
  WHERE rr.id = v_result_id;
  IF v_status <> 'RUNNING' THEN
    RAISE EXCEPTION 'result children may be appended only to a RUNNING run' USING ERRCODE = '55000';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER geometric_access_insert_guard BEFORE INSERT ON geometric_access FOR EACH ROW EXECUTE FUNCTION guard_result_child_insert();
CREATE TRIGGER modeled_contact_insert_guard BEFORE INSERT ON modeled_contact FOR EACH ROW EXECUTE FUNCTION guard_result_child_insert();
CREATE TRIGGER candidate_session_insert_guard BEFORE INSERT ON candidate_session FOR EACH ROW EXECUTE FUNCTION guard_result_child_insert();
CREATE TRIGGER scheduled_session_insert_guard BEFORE INSERT ON scheduled_session FOR EACH ROW EXECUTE FUNCTION guard_result_child_insert();
CREATE TRIGGER transfer_allocation_insert_guard BEFORE INSERT ON transfer_allocation FOR EACH ROW EXECUTE FUNCTION guard_result_child_insert();
CREATE TRIGGER run_event_insert_guard BEFORE INSERT ON run_event FOR EACH ROW EXECUTE FUNCTION guard_result_child_insert();
CREATE TRIGGER run_metric_insert_guard BEFORE INSERT ON run_metric FOR EACH ROW EXECUTE FUNCTION guard_result_child_insert();
CREATE TRIGGER run_annotation_insert_guard BEFORE INSERT ON run_annotation FOR EACH ROW EXECUTE FUNCTION guard_result_child_insert();

CREATE TRIGGER geometric_access_immutable BEFORE UPDATE OR DELETE ON geometric_access FOR EACH ROW EXECUTE FUNCTION reject_update_delete();
CREATE TRIGGER modeled_contact_immutable BEFORE UPDATE OR DELETE ON modeled_contact FOR EACH ROW EXECUTE FUNCTION reject_update_delete();
CREATE TRIGGER candidate_session_immutable BEFORE UPDATE OR DELETE ON candidate_session FOR EACH ROW EXECUTE FUNCTION reject_update_delete();
CREATE TRIGGER scheduled_session_immutable BEFORE UPDATE OR DELETE ON scheduled_session FOR EACH ROW EXECUTE FUNCTION reject_update_delete();
CREATE TRIGGER transfer_allocation_immutable BEFORE UPDATE OR DELETE ON transfer_allocation FOR EACH ROW EXECUTE FUNCTION reject_update_delete();
CREATE TRIGGER run_event_immutable BEFORE UPDATE OR DELETE ON run_event FOR EACH ROW EXECUTE FUNCTION reject_update_delete();
CREATE TRIGGER run_metric_immutable BEFORE UPDATE OR DELETE ON run_metric FOR EACH ROW EXECUTE FUNCTION reject_update_delete();
CREATE TRIGGER run_annotation_immutable BEFORE UPDATE OR DELETE ON run_annotation FOR EACH ROW EXECUTE FUNCTION reject_update_delete();

-- Cross-row capacity conservation, checked at transaction commit.
CREATE FUNCTION check_session_allocation_capacity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_session uuid; v_capacity numeric(20,0); v_allocated numeric(39,0);
BEGIN
  v_session := CASE WHEN TG_OP = 'DELETE' THEN OLD.scheduled_session_result_id ELSE NEW.scheduled_session_result_id END;
  SELECT cs.capacity_bytes INTO v_capacity
  FROM scheduled_session ss
  JOIN candidate_session cs ON cs.result_id = ss.candidate_result_id
  WHERE ss.result_id = v_session;

  SELECT COALESCE(sum(logical_bytes), 0) INTO v_allocated
  FROM transfer_allocation WHERE scheduled_session_result_id = v_session;

  IF v_capacity IS NULL OR v_allocated > v_capacity THEN
    RAISE EXCEPTION 'allocation total % exceeds or lacks session capacity % for %', v_allocated, v_capacity, v_session
      USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER allocation_capacity_guard
  AFTER INSERT OR UPDATE OR DELETE ON transfer_allocation
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
  EXECUTE FUNCTION check_session_allocation_capacity();

-- Application role is append/read oriented. Role creation and login binding belong to
-- deployment automation (environment variables / secret manager), never this repository.
REVOKE ALL ON SCHEMA passbudget FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA passbudget FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA passbudget FROM PUBLIC;

COMMENT ON SCHEMA passbudget IS 'SEMANTIX PassBudget P0 v0.1; migration owner grants least privilege to deployment-created roles.';
COMMENT ON TABLE input_snapshot IS 'Immutable PB-C14N-JSON-V1 input artifact; canonical bytes and hash are never rewritten by migration.';
COMMENT ON TABLE candidate_session IS 'Conflict-before candidate capacity; distinct from scheduled selection and payload allocation.';
COMMENT ON TABLE scheduled_session IS 'Conflict-resolved whole opportunity; capacity is derived through candidate_result_id, not duplicated.';
COMMENT ON TABLE transfer_allocation IS 'Planned logical-byte placement only; P0 has no received/verified/ACK byte.';
COMMENT ON TABLE run_metric IS 'Versioned materialized KPI; comparison uses compatible rows from two runs and is not persisted as duplicate metrics.';

COMMIT;

-- Deployment-only grants (run by migration owner after externally creating NOLOGIN group roles):
-- GRANT USAGE ON SCHEMA passbudget TO pb_application;
-- GRANT SELECT, INSERT, UPDATE ON passbudget.profile, passbudget.scenario,
--   passbudget.evidence_source, passbudget.scenario_run, passbudget.run_stage TO pb_application;
-- GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA passbudget TO pb_application;
-- Do not grant DELETE. Do not grant UPDATE on immutable revision/snapshot/result/audit tables.
