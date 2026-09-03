# AC-P0-01 ~ AC-P0-25 수용 기준 매핑

> 기준 문서: `docs/specs/P0_FUNCTIONAL_SPEC.md` §14  
> 감사일: 2026-09-03 · 구현 기준선 v0.3 (persistence tiers)  
> 이 표는 `tests/test_acceptance_matrix.py`가 파싱해 검사한다. `PASS`로 적힌 모든 test node id는
> 실제 수집 가능한 테스트여야 하고, 25개 ID가 빠짐없이 있어야 한다. 즉 이 문서는 장식이 아니라
> 실행되는 계약이다.

상태 정의:

- `PASS` — 구현이 있고, 아래 자동 테스트가 Given/When/Then을 실제로 검증한다.
- `PARTIAL` — 일부만 검증됐다. 무엇이 빠졌는지 비고에 적는다.
- `BLOCKED` — 외부 evidence나 명세 결정이 없어 완료할 수 없다.
- `MISSING` — 구현이 없다.

| ID | 검증 내용 | 상태 | 검증 테스트 | 비고 |
|---|---|---|---|---|
| AC-P0-01 | synthetic contacts 실행: A/B/C=4/4/8, 총 16, orbit N/A, grade CONCEPT_ONLY | PASS | `tests/integration/test_vertical_slice.py::test_golden_counts_intervals_and_totals` | 첫 A1=00:10~00:20, 마지막 C8=22:40~22:46까지 함께 확인 |
| AC-P0-02 | rate가 UNKNOWN이면 contact는 계산되고 capacity branch만 BLOCKED/null | PASS | `tests/unit/test_time_capacity.py::test_unknown_rate_blocks_only_capacity`, `tests/integration/test_vertical_slice.py::test_unknown_rate_preserves_contacts_and_blocks_capacity` | 0 대체 없음. 무관한 station은 COMPUTED 유지 |
| AC-P0-03 | A1 exact rate 적분 60,000,000B, segment 분할/병합 permutation 불변 | PASS | `tests/unit/test_time_capacity.py::test_golden_a1_exact_rate`, `tests/property/test_rate_properties.py::test_equal_rate_segment_split_merge_invariance` | 분할 지점을 hypothesis가 무작위 생성 |
| AC-P0-04 | guard 합이 pass와 같거나 크면 KNOWN_ZERO + `GUARD_EXCEEDS_WINDOW` | PASS | `tests/unit/test_boundaries.py::test_guard_sum_triplet`, `tests/unit/test_time_capacity.py::test_guard_boundary` | `<`, `=`, `>` 세 경계 모두. grade는 CONCEPT_ONLY 유지 |
| AC-P0-05 | fixed capacity와 rate/reserve 동시 입력은 INVALID `INPUT_FACTOR_CONFLICT` | PASS | `tests/unit/test_time_capacity.py::test_fixed_provider_factor_conflict`, `tests/integration/test_api_lifecycle.py::test_snapshot_promotion_rejects_an_invalid_published_revision` | API 경로에서도 snapshot 승격이 거부됨 |
| AC-P0-06 | 기본 queue: A1 allocation과 85,000,000B backlog가 oracle과 일치 | PASS | `tests/integration/test_queue_storage_overlap.py::test_queue_first_session_and_completion_oracles` | 50,000 / 950,000 / 4,000,000 / 55,000,000B와 완료시각 00:11:00.8·00:11:16·00:12:20 |
| AC-P0-07 | fixed-per-contact queue: session-start ready만, completion은 session end | PASS | `tests/unit/test_queue.py::test_fixed_capacity_does_not_admit_payload_ready_mid_session`, `tests/unit/test_queue.py::test_fixed_capacity_commits_completion_at_session_end` | 패스 내부 완료시각을 만들지 않음 |
| AC-P0-08 | overlapping contacts: candidate 440MB, scheduled unique 400MB | PASS | `tests/integration/test_queue_storage_overlap.py::test_overlap_oracle_selects_a2_and_suppresses_d` | D1이 `SESSION_SUPPRESSED_TX_RESOURCE_CONFLICT`로 보존됨 |
| AC-P0-09 | endpoint-touch 비충돌, zero-duration tangent 미집계 | PASS | `tests/unit/test_boundaries.py::test_endpoint_touch_is_not_a_conflict_and_zero_duration_is_rejected`, `tests/unit/test_scheduler.py::test_endpoint_touch_is_not_conflict_and_tangent_is_invalid` | tangent는 `INVALID_INTERVAL`로 거부 |
| AC-P0-10 | DB 삽입·입력 배열 순서 permutation에도 선택 결과와 semantic hash 동일 | PASS | `tests/integration/test_repository_equivalence.py::test_input_order_permutation_reaches_the_same_stored_rows`, `tests/integration/test_queue_storage_overlap.py::test_queue_input_permutation_preserves_semantic_results`, `tests/unit/test_persistence_mapping.py::test_row_order_never_changes_the_persisted_view`, `tests/property/test_horizon_properties.py::test_candidate_input_order_never_changes_the_selection` | 실제 DB 삽입을 포함해 검증된다. SQLite tier가 서버 없이 항상 실행되고, PostgreSQL tier는 URL이 있을 때 같은 테스트에 합류한다 |
| AC-P0-11 | 완전 동률 station은 lexical station ID로 결정 | PASS | `tests/unit/test_horizon.py::test_full_tie_resolves_by_lexical_station_id` | 입력 순서를 뒤집어도 GS-X 선택 |
| AC-P0-12 | deadline과 future session: horizon-aware objective가 mandatory on-time 우선 | PASS | `tests/unit/test_horizon.py::test_mandatory_horizon_feasibility_precedes_capacity`, `tests/property/test_horizon_properties.py::test_component_search_matches_exhaustive_subset_search` | `PB-GOLDEN-HORIZON-01` fixture가 `verify-golden`에도 포함됨 |
| AC-P0-13 | atomic payload가 session에 안 들어가면 시작하지 않음 | PASS | `tests/unit/test_queue.py::test_atomic_object_never_starts_when_it_does_not_fit` | `NOT_STARTED_ATOMIC_NOT_COMPLETABLE` 기록 |
| AC-P0-14 | dependency cycle이면 해당 queue/schedule branch INVALID | PASS | `tests/integration/test_queue_storage_overlap.py::test_dependency_cycle_is_rejected_before_allocations` | allocation 생성 전에 거부 |
| AC-P0-15 | Storage OFF: queue 결과 계산, storage metric N/A | PASS | `tests/integration/test_queue_storage_overlap.py::test_queue_aware_with_storage_disabled_reports_not_applicable`, `tests/integration/test_vertical_slice.py::test_network_only_leaves_queue_and_storage_not_applicable` | 0이나 무한대로 표현하지 않음 |
| AC-P0-16 | HARD storage oracle: ORIGINAL whole-object reject, occupancy 55,000,000B | PASS | `tests/integration/test_queue_storage_overlap.py::test_storage_soft_and_hard_reserve_oracles` | 부분 삭제 없음, rejected 140,000,000B 기록 |
| AC-P0-17 | SOFT storage oracle: reserve breach 15,000,000B, hard overflow 0B | PASS | `tests/integration/test_queue_storage_overlap.py::test_storage_soft_and_hard_reserve_oracles`, `tests/unit/test_queue.py::test_soft_reserve_never_allows_physical_overflow` | SOFT여도 물리 용량 초과는 항상 reject |
| AC-P0-18 | omitted/UNKNOWN/N/A/known 0/defaulted 0이 서로 다른 canonical 상태 | PASS | `tests/unit/test_evidence.py::test_zero_unknown_omitted_na_and_defaulted_zero_are_distinct` | 5개 상태의 canonical bytes가 모두 다름 |
| AC-P0-19 | NFC/NFD, key/unit/set permutation, byte >2^53에서 독립 구현과 일치 | PASS | `tests/unit/test_canonical.py::test_independent_canonical_vectors_and_permutations`, `tests/unit/test_canonical.py::test_integers_beyond_double_precision_stay_exact`, `tests/unit/test_canonical.py::test_unit_normalisation_is_not_silently_applied`, `tests/unit/test_canonical.py::test_rational_is_reduced_and_permutation_stable` | `tests/reference_c14n.py`는 production module을 import하지 않는다 |
| AC-P0-20 | persistence round trip 후 input/result canonical bytes와 hash 불변 | PASS | `tests/integration/test_repository_equivalence.py::test_memory_and_sqlite_agree_on_every_stored_fact`, `tests/integration/test_api_persistence.py::test_a_run_survives_a_restart_with_identical_hashes_and_result`, `tests/unit/test_persistence_mapping.py::test_persisted_view_survives_a_json_round_trip`, `tests/integration/test_postgres_persistence.py::test_persistence_round_trip_preserves_rows_and_hashes` | 실제 DB write/read round trip이 SQLite tier에서 서버 없이 실행된다. 재시작 후에도 3개 hash와 result document가 동일하다. PostgreSQL tier는 URL이 있을 때 추가 검증된다 |
| AC-P0-21 | 같은 semantic input 재실행 시 input/result hash 동일, run ID/hash는 달라도 됨 | PASS | `tests/integration/test_vertical_slice.py::test_permutation_preserves_semantic_hash` | run_record_hash는 다름을 함께 확인 |
| AC-P0-22 | 비교 metric 정의 불일치: 두 값은 표시, delta/ratio는 null과 reason | PASS | `tests/unit/test_comparison.py::test_unit_mismatch_shows_both_values_without_a_delta`, `tests/unit/test_comparison.py::test_definition_and_accounting_layer_mismatches_are_named_separately`, `tests/unit/test_comparison.py::test_metric_present_in_only_one_run_is_reported_not_assumed_zero` | unit/definition/accounting layer/schema revision 4축 모두 |
| AC-P0-23 | baseline 0 비교: 절대 delta만 표시, 비율 null | PASS | `tests/unit/test_comparison.py::test_zero_baseline_keeps_the_absolute_delta_and_nulls_the_ratio` | `BASELINE_ZERO_RATIO_UNDEFINED` |
| AC-P0-24 | branch-local failure: run PARTIAL, 유효한 선행 결과 조회 가능 | PASS | `tests/integration/test_vertical_slice.py::test_partial_run_results_and_report_stay_retrievable`, `tests/integration/test_vertical_slice.py::test_unknown_rate_preserves_contacts_and_blocks_capacity` | stage별 상태와 16개 geometric access가 API로 조회됨 |
| AC-P0-25 | 공개 오류/로그에 secret, SSH, DB URL, host absolute path 미노출 | PASS | `tests/integration/test_vertical_slice.py::test_api_errors_do_not_leak_sensitive_internals`, `tests/integration/test_api_lifecycle.py::test_missing_resources_return_404_without_internal_detail`, `tests/unit/test_error_redaction.py::test_persistence_failure_message_carries_no_connection_detail`, `tests/unit/test_error_redaction.py::test_no_packaged_fixture_contains_a_credential_or_host_address` | `python scripts/secret_scan.py`가 저장소 전체를 함께 검사 |

## 요약

| 상태 | 개수 |
|---|---|
| PASS | 25 |
| PARTIAL | 0 |
| BLOCKED | 0 |
| MISSING | 0 |

AC-P0-10과 AC-P0-20은 2026-09-03의 persistence tier 결정(ADR-0003)으로 `PARTIAL`에서 `PASS`가
됐다. 두 항목이 필요로 하던 것은 "실제 DB write/read"였고, 이제 SQLite tier가 PostgreSQL도
Docker도 없이 그 검증을 항상 수행한다. PostgreSQL tier의 동일 검증은
`tests/integration/test_postgres_persistence.py`와
`tests/integration/test_repository_equivalence.py`에 남아 있으며
`PASSBUDGET_TEST_DATABASE_URL`이 주어질 때 실행된다.

## PostgreSQL tier 검증 (2026-09-03)

이 감사 환경에는 여전히 PostgreSQL이 없다. 대신 GitHub Actions의 `postgresql` workflow가
커밋 `b4056c1`에서 통과했다: 깨끗한 upgrade/delta/downgrade, `pytest -m postgres`, 3-tier
동등성 suite. 이제 두 수용 기준의 PostgreSQL 절반도 skip이 아니라 실행된 근거를 갖는다.

그 전까지 세 번의 실행이 실패했고, 세 결함 모두 PostgreSQL 없이 도는 기본 suite로는
원리적으로 잡히지 않는 것이었다. 기록해 둔다:

| 결함 | 왜 기본 suite로 잡히지 않았나 | 수정 |
|---|---|---|
| `jsonb`에 `Fraction`·`UtcInstant` 바인딩 | SQLite adapter가 `default=str`로 삼켜 Python repr을 저장하고 있었다 | `canonical_object()` (`d64836e`) |
| `PB-GOLDEN-ACK-01`을 PostgreSQL에 저장 시도 | `CONFLICT-STORE-01`의 제약을 equivalence suite에만 반영하고 persistence 테스트에는 빠뜨렸다 | `postgres_capable_fixtures()` + 명시적 거부 테스트 (`a033118`) |
| label 없는 `ENUM` 참조 | `sqlalchemy.Enum`은 label이 없을 때 쓰기는 통과시키고 읽기만 `LookupError`를 낸다. 쓰기 전용 검사로는 잡을 수 없다 | `_ExistingEnum` + DDL label 기반 round-trip 회귀 테스트 (`b4056c1`) |

세 번째 결함의 회귀 테스트는 DB 없이 돈다
(`tests/unit/test_postgres_schema_alignment.py::test_every_enum_column_reads_its_stored_label_back_unchanged`).
승인된 DDL에 선언된 모든 label이 `result_processor`를 통과해도 그대로여야 한다.

## Docker 이미지 검증 (2026-09-03)

`Dockerfile`은 그때까지 한 번도 빌드된 적이 없었고, 실제로 빌드되지 않는 상태였다. builder
stage가 `db/`를 복사하지 않는데 `pyproject.toml`의 `force-include`가 `db/sqlite`를 요구해
`FileNotFoundError: Forced include not found: /build/db/sqlite`로 실패한다. 로컬에서 동일한
build context를 재현해 확인했고, `COPY db ./db`를 추가해 고쳤다.

재발을 막기 위해 `backend.yml`에 `docker` job을 두었다: 이미지를 빌드하고, 그 안에서
`verify-golden`과 `where`를 돌리고, API로 run을 하나 계산한 뒤 **컨테이너를 재시작하고 같은
run을 다시 읽는다**. 마지막 단계가 packaged SQLite tier와 "컨테이너가 사는 동안만 영속처럼
보이는" in-memory repository를 구분한다.

이 job은 커밋 `edcad89`에서 실제로 통과했다. 즉 이미지가 빌드되고, 그 안에서 CLI가 돌고,
API가 계산한 run이 컨테이너 재시작 뒤에도 조회된다는 것은 실행된 근거다. Docker가 없는 이
감사 환경에서는 그 assertion들을 uvicorn으로 먼저 재현해 endpoint 모양과 값을 확인했고
(`payload_allocated_bytes = 145,000,000`, 프로세스 재시작 후에도 동일), Docker 자체는 CI가
확인했다.

같은 실행에서 `audit` job(`pip-audit`)도 통과했다. DoD #8의 나머지 절반이 채워진 시점이다.

## 별도 release gate

`P0_FUNCTIONAL_SPEC.md` §14 말미의 실제 궤도 gate는 이 25개와 독립이며 여전히
`P0_RELEASE_BLOCKED_NEEDS_EVIDENCE`다. 근거는 `docs/specs/ORBIT_RELEASE_GATE.md`.
