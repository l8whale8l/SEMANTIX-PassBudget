# SEMANTIX PassBudget P0 물리 데이터베이스 스키마 v0.1

## 규모와 최종 판정

| 단계               | 테이블 수 | 총 column 수 | 핵심 목적             |
| ---------------- | ----: | ---------: | ----------------- |
| Vertical Slice   | 22 | 253 | NETWORK_ONLY 실행  |
| QUEUE_AWARE 추가  | 28 | 330 | payload와 backlog  |
| Storage 추가       | 28 | 330 | occupancy와 reject |
| Compare/Trace 추가 | 30 | 357 | 비교와 재현            |
| P0 전체            | 30 | 357 | 전체 기능             |

최종 판정: **`READY_WITH_REQUIRED_DECISIONS`**

DDL은 실행 가능한 물리 기준선이다. 다만 v1.5가 release blocker로 둔 독립 궤도 fixture, `PB-C14N-JSON-V1` 교차 구현 vector, CI 결과와 실제 KMU 정책 소유자 승인은 스키마만으로 해결되지 않는다. 따라서 executable domain model 구현은 시작할 수 있지만 제품 release 판정은 아니다.

Storage 단계가 테이블/column을 늘리지 않는 이유는 storage 설정이 `scenario_revision`과 정확히 같은 1:1 생명주기이고, queue/storage의 시간순 결과가 같은 total order를 쓰는 `run_event` envelope에 들어가기 때문이다. 이 column들은 P1 선행 column이 아니라 P0의 명시적 `ENABLED/DISABLED` 선택에 사용된다.

## 1. 설계 결론

물리 경계는 다음 한 방향이다.

```text
수정 가능한 profile/scenario head
  → 불변 profile/scenario revision
  → 불변 typed 구성 + field evidence
  → 불변 InputSnapshot(PB-C14N-JSON-V1 bytes/hash)
  → append-only Run/Stage
  → run 전용 불변 Result subtype
```

- 공통 `profile`/`profile_revision`은 머리와 revision metadata를 합친다. P0 spacecraft는 이름/identity와 고정 단일 TX 계약뿐이라 공통 revision만 사용하고, 궤도·좌표·rate·payload 규칙·policy 값은 typed subtype에 남긴다.
- preset은 별도 만능 item graph가 아니라 `scenario.is_preset=true` 또는 `profile.is_preset=true`인 동일 revision 구조다. fixture도 같은 구조를 쓰되 test source로 식별한다.
- scenario당 spacecraft/orbit revision은 하나, station은 여러 개다. 최소 앙각과 link binding은 `scenario_station`이 소유한다.
- Storage 설정은 scenario revision에 두며 `storage_mode` CHECK가 ON/OFF 조합을 강제한다.
- `Geometric Access → Modeled Contact → Candidate Session → Scheduled Session → Transfer Allocation → Event → KPI`는 별도 subtype이다. 상태 column 하나로 합치지 않는다.
- 후보 capacity는 `candidate_session.capacity_bytes` 한 곳에만 저장한다. scheduled capacity는 선택된 candidate 합, planned byte는 allocation 합, backlog는 queue event/KPI다. P0에는 observed byte column이 없다.
- 비교는 별도 comparison metric을 저장하지 않는다. terminal 두 run의 `run_metric`을 `(metric_code, scope, unit, definition_revision, accounting_layer)`로 호환성 검사해 self-join한다. snapshot diff도 canonical payload에서 계산한다.
- 일반 trace graph는 만들지 않는다. typed FK와 `run_result.stable_key`, `run_annotation`으로 원인 경로를 재구성한다.

## 2. 6원칙 준수 평가

| 원칙 | 평가 | 물리 장치 |
|---|---|---|
| 중복 최소화 | 충족 | 좌표는 GS revision 한 곳, 최소 앙각은 scenario station 한 곳, capacity는 candidate 한 곳, 비교 delta는 비저장 |
| 무결성과 일관성 | 충족(교차 aggregate 일부 service invariant) | PK/FK/UNIQUE/CHECK, revision/result immutability trigger, run state machine, deferred allocation 합계 trigger |
| 책임과 생명주기 | 충족 | head/revision/scenario/snapshot/run/result 경계와 `ON DELETE RESTRICT` |
| 실제 조회 성능 | 충족 | load boundary별 복합/partial index; 주요 화면 0~6 JOIN |
| 확장성과 유지보수성 | 충족 | provider/revision 추가 방식; P1/P2 column 선추가 없음; canonical artifact 재작성 금지 |
| 보안·감사·복구 | 충족 | secret 비저장, HTTPS/URN/artifact locator 제한, archive/tombstone, immutable audit, terminal 보존, PUBLIC 권한 회수 |

DB가 직접 강제하는 것은 row-local 타입·범위·시간·상호배타 조합, FK, revision 번호/stable key/event order 유일성, 공개 revision 및 snapshot/result 불변성, run 상태 전이, allocation 합≤session capacity다. 전체 dependency cycle, snapshot의 모든 필수 evidence 완전성, result subtype 상태와 값의 의미 일치, payload byte-range 비중첩, 정책별 comparator 완전성, metric 재계산 일치처럼 여러 aggregate와 알고리즘 의미를 읽어야 하는 규칙은 publish/finalize transaction의 service validator가 강제한다. 이를 trigger에 넣으면 core engine 로직이 DB로 누출되고 독립 시험이 어려워지기 때문이다.

| 강제 경계 | 구체 규칙 | 실패 처리 |
|---|---|---|
| DB constraint/trigger | FK와 kind discriminator, 모든 `[start,end)`, nonnegative byte/duration, revision/stable key/event order UNIQUE, storage ON/OFF 조합, published/terminal 불변, session allocation 합 상한 | statement/transaction rollback |
| Profile publish service | revision은 DB상 DRAFT로만 insert; orbit provider 필수 group·TLE/SGP4, rate segment coverage/non-overlap, factor conflict, PROXY source/rationale, evidence fingerprint | revision을 DRAFT로 유지 |
| Scenario publish service | station/payload child 완전성, policy 전용 필드, dependency cycle, Storage ON footprint/initial manifest | revision을 DRAFT로 유지 |
| Snapshot promotion service | 모든 resolved presence/value/evidence 상태, source revision, canonical schema/bytes/hash, feature gate | INVALID snapshot 또는 승격 거부 |
| Run finalize service | linked result가 모두 같은 run/snapshot scenario인지, subtype status/value, allocation byte-range·chunk·payload 보존, event reducer, materialized KPI 재계산 | PARTIAL/FAILED/INVALID terminal 기록 |

## 3. 영역별 테이블 목록

| 영역 | 테이블 | 수 |
|---|---|---:|
| Provenance/Catalog | `evidence_source`, `evidence_source_revision`, `profile`, `profile_revision`, 5개 typed revision, `communication_timeline_segment`, `evidence_assertion` | 11 |
| Scenario authoring | `scenario`, `scenario_revision`, `scenario_station`, `scenario_payload`, `payload_dependency` | 5 |
| Execution | `engine_manifest`, `input_snapshot`, `scenario_run`, `run_stage` | 4 |
| Result/Trace/Audit | `run_result`, 7개 result subtype, `run_annotation`, `audit_event` | 10 |

## 4. 테이블 상세

표의 `N`은 NOT NULL, `Y`는 nullable이다. UUID 기본값은 DB 식별용이며 canonical hash에서 제외한다.

### 4.1 `evidence_source`

책임: 출처의 수정 가능한 이름·공개범위·archive/tombstone 상태. 총 **11 columns**. 예상 row: 프로젝트당 10²~10⁴. 주요 조회: 출처 검색/삭제대상 확인. 별도 이유: source revision과 다른 수정·삭제 생명주기 및 보안 정책. revision에 합치면 tombstone 시 과거 인용을 파괴한다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| id | uuid | N | `gen_random_uuid()` | DB PK | PK |
| stable_key | varchar(64) | N | — | 외부 안정 키 | UNIQUE, 형식 CHECK |
| name | varchar(160) | N | — | 표시명 | 길이 제한 |
| source_kind | source_kind | N | — | 출처 종류 | enum |
| sensitivity | sensitivity_class | N | `PUBLIC` | 공개 범위 | enum |
| status | source_status | N | `ACTIVE` | 생명주기 | 상태 CHECK |
| description | varchar(1000) | Y | — | 설명 | 길이 제한 |
| created_at | timestamptz | N | `clock_timestamp()` | 생성 시각 | — |
| archived_at | timestamptz | Y | — | archive 시각 | 상태 CHECK |
| tombstoned_at | timestamptz | Y | — | 민감 source 제거 시각 | 상태 CHECK |
| tombstone_reason | varchar(1000) | Y | — | 제거 근거 | TOMBSTONED 시 필수 |

삭제는 trigger가 거부한다. 민감 artifact는 외부 저장소에서 제거하고 이 head를 TOMBSTONED로 바꾸며 `audit_event`를 같은 transaction에 기록한다.

### 4.2 `evidence_source_revision`

책임: 인용한 정확한 source revision과 선택적 원본 import payload. 총 **12 columns**. 예상 row: source당 1~100. 주요 조회: source 이력/해시 확인. 별도 이유: 독립 cardinality와 영구 인용. source head와 합치면 최신 locator 변경이 과거 run 근거를 바꾼다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| id | uuid | N | `gen_random_uuid()` | PK | PK |
| source_id | uuid | N | — | source head | FK RESTRICT |
| revision_no | integer | N | — | revision 순번 | `>0`, source 내 UNIQUE |
| label | varchar(160) | N | — | revision명 | 길이 제한 |
| locator | varchar(2048) | Y | — | 안전한 opaque locator | HTTPS/URN/artifact CHECK |
| media_type | varchar(127) | Y | — | MIME type | 길이 제한 |
| retrieved_at | timestamptz | Y | — | 취득 시각 | — |
| observed_at | timestamptz | Y | — | 관측 기준 시각 | — |
| content_sha256 | bytea | Y | — | 원문 해시 | 32-byte CHECK |
| raw_import_payload | jsonb | Y | — | 원본 import 보존 | object/array CHECK |
| raw_payload_schema_version | varchar(64) | Y | — | import schema | payload와 동시 존재 CHECK |
| created_at | timestamptz | N | `clock_timestamp()` | 생성 시각 | — |

모든 UPDATE/DELETE를 거부한다.

### 4.3 `profile`

책임: 재사용 기준정보의 공통 mutable head. 총 **9 columns**. 예상 row: 10²~10⁵. 주요 조회: kind별 preset/active 목록. 별도 이유: 모든 profile kind가 같은 소유자·archive·current-pointer 접근 패턴을 가진다. kind별 head로 분리하면 5개 테이블이 순증하고 공통 무결성은 늘지 않는다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| id | uuid | N | `gen_random_uuid()` | PK | PK |
| stable_key | varchar(64) | N | — | 안정 키 | UNIQUE, 형식 CHECK |
| kind | profile_kind | N | — | subtype discriminator | enum, revision composite FK |
| name | varchar(160) | N | — | 표시명 | 길이 제한 |
| description | varchar(1000) | Y | — | 설명 | 길이 제한 |
| is_preset | boolean | N | `false` | preset 목록 포함 | — |
| current_revision_id | uuid | Y | — | UI 편의 포인터 | `(revision,id)` composite FK |
| created_at | timestamptz | N | `clock_timestamp()` | 생성 | — |
| archived_at | timestamptz | Y | — | archive | hard delete 금지 |

### 4.4 `profile_revision`

책임: 모든 profile revision의 공통 번호·발행·hash metadata. 총 **12 columns**. 예상 row: profile당 1~100. 주요 조회: revision history/current 상세. 별도 이유: 발행 불변성과 revision 유일성을 한 곳에서 강제한다. subtype에 반복하면 동일 사실을 여섯 곳에 중복한다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| id | uuid | N | `gen_random_uuid()` | PK | PK |
| profile_id | uuid | N | — | head | composite FK RESTRICT |
| profile_kind | profile_kind | N | — | subtype 일치 | head와 composite FK |
| revision_no | integer | N | — | revision | `>0`, head 내 UNIQUE |
| lifecycle_status | revision_status | N | `DRAFT` | draft/published | publish CHECK/trigger |
| schema_version | varchar(32) | N | — | typed schema | — |
| label | varchar(160) | N | — | revision명 | — |
| change_note | varchar(1000) | Y | — | 변경 이유 | — |
| based_on_revision_id | uuid | Y | — | 계보 | self FK RESTRICT |
| semantic_hash | bytea | Y | — | revision 의미 해시 | 32 bytes; publish 시 필수 |
| created_at | timestamptz | N | `clock_timestamp()` | 생성 | — |
| published_at | timestamptz | Y | — | 발행 | PUBLISHED 시 필수 |

발행 후 parent와 모든 subtype/evidence row의 UPDATE/DELETE를 거부한다.

### 4.5 `communication_timeline_segment`

책임: `FIXED_RATE`의 순서 있는 piecewise-fixed exact rate와 TIME reserve 구간. 총 **7 columns**. 예상 row: communication revision당 0(UNKNOWN)~수십. 주요 조회: capacity 적분과 pass 내부 completion/reserve 차감. 별도 이유: timeline 구간은 독립 반복 cardinality가 있고 3-bin golden 및 고율 reserve oracle을 표현해야 한다. 배열/JSONB나 단일 duration으로 합치면 구간 CHECK와 exact 산술을 잃는다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| revision_id | uuid | N | — | communication owner | composite PK, FK RESTRICT |
| segment_kind | communication_segment_kind | N | — | RATE/TIME_RESERVE | composite PK, tagged CHECK |
| ordinal | integer | N | — | 의미 순서 | composite PK, `>=0` |
| start_offset_us | bigint | N | — | active interval 상대 시작 | owner/kind 내 UNIQUE, `>=0` |
| end_offset_us | bigint | Y | — | 상대 exclusive end/RATE tail | tagged interval CHECK |
| rate_numerator_bits | numeric(39,0) | Y | — | RATE exact bit 분자 | RATE `>=0`; reserve NULL |
| rate_denominator_seconds | numeric(39,0) | Y | — | RATE exact second 분모 | RATE `>0`; reserve NULL |

RATE 비중첩·coverage, NULL tail 최종 1개, TIME_RESERVE union, parent `reserve_kind`, provider-kind 호환성은 profile publish validator가 검사한다. 상수 rate는 RATE `[0,NULL)` 한 row다.

### 4.6 `orbit_revision`

책임: `GP_TLE`/`VIRTUAL_CIRCULAR` tagged union. 총 **17 columns**. 예상 row: revision당 1. 주요 조회: snapshot resolver. 별도 이유: 궤도는 spacecraft와 독립적으로 교체·출처화된다. 두 provider를 별도 테이블로 나누면 nullable은 줄지만 테이블 1개와 union query가 증가하며 P0의 작은 고정 union에는 이득이 작다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| revision_id | uuid | N | — | PK | typed FK |
| profile_kind | profile_kind | N | `ORBIT` | discriminator | 상수 CHECK |
| orbit_kind | orbit_kind | N | — | provider | tagged-union CHECK |
| epoch_at | timestamptz | Y | — | epoch | 실행 완전성은 service |
| reference_frame | varchar(32) | Y | — | 좌표계 | service registry |
| time_scale | varchar(16) | Y | — | 시간척도 | service registry |
| propagator_revision | varchar(96) | Y | — | 전파기 계약 | GP_TLE는 SGP4 service 검사 |
| tle_line1 | char(69) | Y | — | TLE line 1 | pair/tag CHECK |
| tle_line2 | char(69) | Y | — | TLE line 2 | pair/tag CHECK |
| tle_provider | varchar(96) | Y | — | 제공자 | tag CHECK |
| tle_retrieved_at | timestamptz | Y | — | 취득 | tag CHECK |
| tle_content_sha256 | bytea | Y | — | 원문 해시 | 32-byte/tag CHECK |
| earth_radius_m | bigint | Y | — | 원궤도 기준 반경 | positive/tag CHECK |
| altitude_m | bigint | Y | — | 원궤도 고도 | positive/tag CHECK |
| inclination_udeg | bigint | Y | — | 경사각 | 0..180e6 |
| raan_udeg | bigint | Y | — | canonical RAAN | `[0,360e6)` |
| argument_of_latitude_udeg | bigint | Y | — | 초기 위상 | `[0,360e6)` |

UNKNOWN draft를 보존하기 위해 provider 필드 group 전체 NULL을 허용한다. executable snapshot 승격 시 provider별 필수 group, TLE checksum/object ID와 propagator 조합을 service가 검사한다.

### 4.7 `ground_station_revision`

책임: WGS-84 좌표와 RX resource. 총 **6 columns**. 예상 row: revision당 1. 주요 조회: preset 목록/시나리오 load. 별도 이유: 독립 revision과 반복 station cardinality. 최소 앙각은 의도적으로 없다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| revision_id | uuid | N | — | PK | typed FK |
| profile_kind | profile_kind | N | `GROUND_STATION` | discriminator | 상수 CHECK |
| latitude_udeg | bigint | Y | — | 위도 | `[-90e6,90e6]` |
| longitude_udeg | bigint | Y | — | east-positive 경도 | `[-180e6,180e6)` |
| ellipsoidal_height_mm | bigint | Y | — | 타원체고 | 안전범위 CHECK |
| rx_resource_key | varchar(64) | N | — | RX key | 형식 CHECK |

### 4.8 `communication_revision`

책임: 상호배타 capacity provider, rate semantics/exact efficiency/final bytes, guard/reserve. 총 **19 columns**. 예상 row: revision당 1. 주요 조회: scenario station link load. 별도 이유: 지상국/위성과 독립적으로 재사용·교체되는 계산 계약. station에 합치면 같은 profile의 다중 재사용이 깨진다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| revision_id | uuid | N | — | PK | typed FK |
| profile_kind | profile_kind | N | `COMMUNICATION` | discriminator | 상수 CHECK |
| provider_kind | capacity_provider_kind | N | — | 방식 | provider CHECK |
| fixed_capacity_bytes | numeric(20,0) | Y | — | 최종 logical B/contact | nonnegative/provider CHECK |
| rate_semantics | rate_semantics | Y | — | rate 계층 | FIXED_RATE group |
| measurement_point | varchar(96) | Y | — | 측정 지점 | FIXED_RATE group |
| rate_scope | rate_scope | Y | — | 적용 구간 | FIXED_RATE group |
| accounted_effects | accounted_effect[] | N | `{}` | 이미 반영된 효과 | enum array/validator |
| coding_efficiency_numerator | numeric(39,0) | Y | — | coding factor 분자 | rational pair, `0<=n<=d` |
| coding_efficiency_denominator | numeric(39,0) | Y | — | coding factor 분모 | rational pair, `d>0` |
| protocol_efficiency_numerator | numeric(39,0) | Y | — | protocol factor 분자 | rational pair, `0<=n<=d` |
| protocol_efficiency_denominator | numeric(39,0) | Y | — | protocol factor 분모 | rational pair, `d>0` |
| residual_efficiency_numerator | numeric(39,0) | Y | — | residual delivery 분자 | rational pair, `0<=n<=d` |
| residual_efficiency_denominator | numeric(39,0) | Y | — | residual delivery 분모 | rational pair, `d>0` |
| acquisition_guard_us | bigint | N | `0` | 시작 guard | `>=0` |
| release_guard_us | bigint | N | `0` | 종료 guard | `>=0` |
| reserve_kind | reserve_kind | N | `NONE` | reserve 방식 | tagged CHECK |
| reserve_bytes | numeric(20,0) | Y | — | byte reserve | FIXED_RATE만 |
| capacity_accounting_layer | varchar(32) | N | `LOGICAL_PAYLOAD` | 회계 계층 | 상수 CHECK |

`APPLICATION_GOODPUT`은 factor를 DB CHECK로 금지한다. CODED/NET에서 이미 accounted된 효과와 active factor의 충돌, 필요한 factor UNKNOWN, TIME reserve child 존재는 publish validator가 검사한다. `FIXED_CAPACITY_PER_CONTACT`의 guard는 positive modeled/conflict interval에만 쓰고 bytes를 재축소하지 않는다.

### 4.9 `payload_type_revision`

책임: 제품 형식·serializer·분할/재개/완료 규칙. 총 **9 columns**. 예상 row: revision당 1. 주요 조회: payload cart type 선택. 별도 이유: instance size/ready/priority와 다른 재사용 생명주기. instance에 복사하면 규칙이 중복된다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| revision_id | uuid | N | — | PK | typed FK |
| profile_kind | profile_kind | N | `PAYLOAD_TYPE` | discriminator | 상수 CHECK |
| media_type | varchar(127) | N | — | 제품 MIME | — |
| serializer_revision | varchar(96) | N | — | 직렬화 규칙 | — |
| segmentation | segmentation_kind | N | — | atomic/chunk/range | enum |
| fixed_chunk_bytes | numeric(20,0) | Y | — | chunk 크기 | FIXED_CHUNK 때 `>0` |
| resume_allowed | boolean | N | `false` | session 간 재개 | atomic false CHECK |
| partial_product_usable | boolean | N | `false` | 부분 가치 | — |
| completion_rule_revision | varchar(96) | N | — | 완료 규칙 | — |

### 4.10 `policy_revision`

책임: versioned queue comparator/objective/tie-break/starvation 계약. 총 **9 columns**. 예상 row: revision당 1. 주요 조회: 정책 preset/실행 근거. 별도 이유: 여러 scenario가 공유하고 comparator가 독립 revision된다. scenario에 문자열로 복사하면 정책 identity가 사라진다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| revision_id | uuid | N | — | PK | typed FK |
| profile_kind | profile_kind | N | `POLICY` | discriminator | 상수 CHECK |
| policy_kind | policy_kind | N | — | FIFO/deadline/value | enum |
| comparator_revision | varchar(96) | N | — | 비교 규칙 | — |
| objective_revision | varchar(96) | N | — | horizon objective | — |
| tie_break_revision | varchar(96) | N | — | 결정적 동률 | — |
| starvation_guard | starvation_guard_mode | N | `NOT_APPLICABLE` | starvation | policy CHECK |
| max_wait_us | bigint | Y | — | 승격 임계 | mode 시 `>0` |
| value_model_revision | varchar(96) | Y | — | 점수 척도 | VALUE_PER_BYTE 필수 |

### 4.11 `evidence_assertion`

책임: typed field/child stable key와 source revision을 결합하고 presence/value/evidence/origin 축을 보존. 총 **17 columns**. 예상 row: revision당 5~100. 주요 조회: 근거 패널. 별도 이유: field별 cardinality와 source 재사용. typed 값을 EAV로 저장하지 않으며 value fingerprint만 결합 검증에 쓴다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| id | uuid | N | `gen_random_uuid()` | PK | PK |
| profile_revision_id | uuid | Y | — | profile owner | FK, owner XOR |
| scenario_revision_id | uuid | Y | — | scenario owner | FK, owner XOR |
| owner_stable_key | varchar(96) | N | — | `$` 또는 child key | 형식 CHECK |
| field_code | varchar(96) | N | — | typed field registry key | 대문자 형식 CHECK |
| presence_state | presence_state | N | — | PROVIDED/OMITTED/DEFAULTED | 조합 CHECK |
| value_state | value_state | Y | — | KNOWN/UNKNOWN/N/A | 조합 CHECK |
| evidence_state | evidence_state | Y | — | CONFIRMED 등 | 조합 CHECK |
| evidence_kind | evidence_kind | Y | — | 근거 종류 | known 시 필수 |
| source_revision_id | uuid | Y | — | 정확한 출처 revision | FK RESTRICT; PROXY 필수 |
| normalized_value_sha256 | bytea | Y | — | typed 값 결합 지문 | known 시 32 bytes |
| rationale | varchar(1000) | Y | — | 대체/채택 이유 | PROXY 필수 |
| captured_at | timestamptz | Y | — | 포착 시각 | — |
| valid_from | timestamptz | Y | — | 유효 시작 | interval CHECK |
| valid_to | timestamptz | Y | — | 유효 종료 | interval CHECK |
| origin_kind | origin_kind | N | — | EXPLICIT/PARSED/NORMALIZED/DERIVED 등 | enum |
| created_at | timestamptz | N | `clock_timestamp()` | 생성 | owner 발행 후 불변 |

동일 owner/field의 중복 주장 허용 여부와 선택 규칙은 evidence registry가 결정한다. executable snapshot은 각 typed field에 정확히 하나의 resolved assertion을 요구한다.

### 4.12 `scenario`

책임: 사용자 시나리오 또는 clone 가능한 preset의 mutable head. 총 **8 columns**. 예상 row: 10²~10⁶. 주요 조회: scenario home/preset 목록. 별도 이유: revision과 다른 archive/current-pointer 생명주기. `is_preset`으로 별도 preset head 1개를 제거한다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| id | uuid | N | `gen_random_uuid()` | PK | PK |
| stable_key | varchar(64) | N | — | 안정 키 | UNIQUE/형식 CHECK |
| name | varchar(160) | N | — | 표시명 | 길이 제한 |
| description | varchar(1000) | Y | — | 설명 | 길이 제한 |
| is_preset | boolean | N | `false` | fixture/preset UI | — |
| current_revision_id | uuid | Y | — | UI 포인터 | same-head composite FK |
| created_at | timestamptz | N | `clock_timestamp()` | 생성 | — |
| archived_at | timestamptz | Y | — | archive | hard delete 금지 |

### 4.13 `scenario_revision`

책임: 분석 범위, 하나의 spacecraft/orbit, mode, policy, 선택적 storage, 계산 계약 revision. 총 **32 columns**. 예상 row: scenario당 1~100. 주요 조회: 시나리오 구성 root/snapshot resolve. 별도 이유: immutable scenario aggregate root. storage를 별도 profile로 분리하지 않은 이유는 P0에서 정확히 0..1이고 동일 owner·revision·보존·조회 패턴이기 때문이다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| id | uuid | N | `gen_random_uuid()` | PK | PK |
| scenario_id | uuid | N | — | head | FK RESTRICT |
| revision_no | integer | N | — | revision | `>0`, scenario 내 UNIQUE |
| lifecycle_status | revision_status | N | `DRAFT` | 발행 상태 | publish trigger/CHECK |
| schema_version | varchar(32) | N | — | scenario schema | — |
| based_on_revision_id | uuid | Y | — | clone 계보 | self FK RESTRICT |
| decision_question | varchar(1000) | N | — | 분석 질문 | 길이 제한 |
| analysis_start | timestamptz | N | — | `[start,end)` | start<end CHECK |
| analysis_end | timestamptz | N | — | exclusive end | start<end CHECK |
| analysis_mode | analysis_mode | N | — | NETWORK/QUEUE | mode CHECK |
| spacecraft_revision_id | uuid | N | — | 위성 profile revision | kind와 composite FK RESTRICT |
| spacecraft_profile_kind | profile_kind | N | `SPACECRAFT` | FK discriminator | 상수 CHECK |
| orbit_revision_id | uuid | N | — | 궤도 revision | typed FK RESTRICT |
| policy_revision_id | uuid | Y | — | queue policy | QUEUE 필수/NETWORK NULL |
| storage_mode | storage_model_mode | N | `DISABLED` | ON/OFF | storage CHECK |
| physical_capacity_bytes | numeric(20,0) | Y | — | recorder 물리량 | ENABLED nonnegative |
| protected_reserve_bytes | numeric(20,0) | Y | — | 보호 여유 | `0..physical` |
| initial_nonqueue_bytes | numeric(20,0) | Y | — | 초기 비queue 점유 | `0..physical` |
| reserve_enforcement | reserve_enforcement | Y | — | HARD/SOFT | ENABLED 필수 |
| storage_admission_policy | storage_admission_policy | Y | — | 신규 반입 정책 | ENABLED=`REJECT_NEW` |
| reclaim_granularity | reclaim_granularity | Y | — | OBJECT/CHUNK | ENABLED 필수 |
| release_trigger | release_trigger | Y | — | NEVER/TX_END | assumption 조합 CHECK |
| delivery_assumption | delivery_assumption | Y | — | NONE/PROXY | release 조합 CHECK |
| overlap_objective_revision | varchar(96) | N | — | conflict 목적함수 | — |
| tie_break_profile_revision | varchar(96) | N | — | station tie-break | — |
| event_order_revision | varchar(96) | N | — | same-time total order | — |
| time_quantization_revision | varchar(96) | N | — | UTC µs 규칙 | — |
| display_format_revision | varchar(96) | N | — | MB/MiB 표시 | — |
| semantic_hash | bytea | Y | — | revision hash | publish 시 32 bytes |
| change_note | varchar(1000) | Y | — | 변경 이유 | — |
| created_at | timestamptz | N | `clock_timestamp()` | 생성 | — |
| published_at | timestamptz | Y | — | 발행 | PUBLISHED 시 필수 |

ENABLED일 때 payload footprint 필수, initial queue 합+nonqueue admission 가능성, TX_END proxy의 evidence grade 강등은 aggregate service validator가 검사한다.

### 4.14 `scenario_station`

책임: scenario별 복수 station 선택, 최소 앙각, 정확한 communication revision binding. 총 **11 columns**. 예상 row: revision당 1~100. 주요 조회: scenario 네트워크 load. 별도 이유: 독립 반복 cardinality와 `(scenario,station)` 유일성. 별도 link-binding 테이블은 P0의 1 station=1 RX/1 comm 관계에서 같은 생명주기를 쪼개므로 합쳤다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| id | uuid | N | `gen_random_uuid()` | PK | PK |
| scenario_revision_id | uuid | N | — | owner | FK RESTRICT |
| stable_key | varchar(64) | N | — | snapshot/result station key | owner 내 UNIQUE |
| ground_station_revision_id | uuid | N | — | 좌표 revision | typed FK, owner 내 UNIQUE |
| communication_revision_id | uuid | Y | — | capacity revision | typed FK; NULL=UNKNOWN/blocked |
| minimum_elevation_udeg | bigint | Y | — | scenario mask | `[0,90e6)` 또는 UNKNOWN |
| link_compatibility | compatibility_status | N | `UNKNOWN` | eligibility | enum |
| eligibility_valid_from | timestamptz | Y | — | binding 유효 시작 | pair interval CHECK |
| eligibility_valid_to | timestamptz | Y | — | binding 유효 종료 | pair interval CHECK |
| station_preference_rank | integer | Y | — | tie-break rank | `>=0` |
| created_at | timestamptz | N | `clock_timestamp()` | 생성 | parent 발행 후 불변 |

### 4.15 `scenario_payload`

책임: 정확한 P0 payload instance와 queue comparator 입력. 총 **24 columns**. 예상 row: QUEUE revision당 1~10⁵. 주요 조회: cart/ready queue/payload 결과. 별도 이유: 독립 반복 cardinality. payload type에 합치면 reusable 규격과 발생 instance가 섞인다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| id | uuid | N | `gen_random_uuid()` | PK | PK |
| scenario_revision_id | uuid | N | — | owner | FK RESTRICT |
| stable_key | varchar(64) | N | — | deterministic payload key | owner 내 UNIQUE |
| payload_type_revision_id | uuid | N | — | 전송 규칙 | typed FK |
| display_name | varchar(160) | N | — | 사용자 이름 | 이름은 priority 아님 |
| producer_kind | producer_kind | N | — | model/user | enum |
| producer_ref | varchar(160) | Y | — | model/observation opaque ref | 길이 제한 |
| ready_at | timestamptz | N | — | queue eligibility | canonical UTC service 검사 |
| logical_size_bytes | numeric(20,0) | Y | — | 정본 logical size | `>=0`; NULL=UNKNOWN |
| storage_footprint_bytes | numeric(20,0) | Y | — | recorder footprint | `>=0`; Storage ON service 필수 |
| service_class | service_class | N | — | MANDATORY 등 | enum |
| mission_priority | smallint | N | — | 0..100 | CHECK |
| queue_sequence | bigint | N | — | FIFO literal | owner 내 UNIQUE, `>=0` |
| deadline_at | timestamptz | Y | — | deadline | 3-field group CHECK |
| deadline_target | deadline_target | Y | — | 목표 사건 | deadline과 동시 |
| post_deadline_action | post_deadline_action | Y | — | miss 행동 | deadline과 동시 |
| expiry_at | timestamptz | Y | — | 신규 시작 exclusive | `ready_at < expiry` |
| severity_rank | smallint | Y | — | deadline severity | 0..100 |
| value_score_numerator | numeric(39,0) | Y | — | exact value 분자 | rational pair |
| value_score_denominator | numeric(39,0) | Y | — | exact value 분모 | `>0` pair |
| bundle_key | varchar(64) | Y | — | bundle grouping | role과 동시 |
| bundle_member_role | bundle_member_role | Y | — | required/optional | key와 동시 |
| initial_storage_state | initial_storage_state | N | `GENERATED_AT_READY` | 초기 manifest | enum |
| created_at | timestamptz | N | `clock_timestamp()` | 생성 | parent 발행 후 불변 |

선택 policy가 요구하는 severity/value 필드, analysis mode, ready/window 관계는 publish validator가 검사한다.

### 4.16 `payload_dependency`

책임: payload 사이 반복 typed dependency edge. 총 **5 columns**. 예상 row: payload당 0~10. 주요 조회: successor prerequisites/cycle validation. 별도 이유: 독립 many-to-many cardinality와 DB FK. 배열/CSV면 참조 무결성을 잃는다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| scenario_revision_id | uuid | N | — | owner | composite PK/FK |
| predecessor_payload_id | uuid | N | — | 선행 payload | same-scenario composite FK |
| successor_payload_id | uuid | N | — | 후행 payload | same-scenario composite FK |
| dependency_kind | dependency_kind | N | — | 사건 의미 | composite PK |
| created_at | timestamptz | N | `clock_timestamp()` | 생성 | parent 발행 후 불변 |

self-edge는 CHECK, cycle은 publish 전에 service가 검출한다.

### 4.17 `engine_manifest`

책임: 실행 환경/알고리즘의 immutable semantic contract. 총 **15 columns**. 예상 row: 배포·설정 조합당 1. 주요 조회: run 재현 근거. 별도 이유: 여러 run이 공유하며 scenario 입력과 별도 release cadence다. snapshot에 문자열 복사하면 같은 manifest를 중복한다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| id | uuid | N | `gen_random_uuid()` | PK | PK |
| stable_key | varchar(96) | N | — | manifest key | UNIQUE |
| engine_version | varchar(96) | N | — | 제품 엔진 | — |
| code_revision | varchar(96) | N | — | 코드 revision | secret/path 금지 |
| orbit_provider_revision | varchar(96) | N | — | orbit provider | — |
| capacity_engine_revision | varchar(96) | N | — | capacity engine | — |
| scheduler_revision | varchar(96) | N | — | scheduler | — |
| storage_reducer_revision | varchar(96) | N | — | storage reducer | — |
| constants_revision | varchar(96) | N | — | 상수 profile | — |
| time_reference_revision | varchar(96) | N | — | leap/time data | — |
| frame_transform_revision | varchar(96) | N | — | frame transform | — |
| event_solver_revision | varchar(96) | N | — | AOS/LOS solver | — |
| canonicalization_revision | varchar(96) | N | — | C14N | — |
| manifest_sha256 | bytea | N | — | manifest hash | 32-byte CHECK |
| created_at | timestamptz | N | `clock_timestamp()` | 생성 | UPDATE/DELETE 금지 |

### 4.18 `input_snapshot`

책임: 실행 당시 자기완결 canonical input artifact. 총 **11 columns**. 예상 row: 실행 준비마다 1. 주요 조회: 과거 입력/해시. 별도 이유: scenario revision과 engine-ready resolved/defaulted 입력의 생명주기가 다르고 과거 재현의 보존정책이 독립적이다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| id | uuid | N | `gen_random_uuid()` | PK | PK |
| scenario_revision_id | uuid | N | — | authored origin | FK RESTRICT |
| schema_version | varchar(32) | N | — | semantic schema | — |
| json_schema_id | varchar(128) | N | — | 고정 JSON Schema | — |
| canonicalization_revision | varchar(96) | N | — | `PB-C14N-JSON-V1` | — |
| canonical_payload | jsonb | N | — | 검토용 구조 | object CHECK |
| canonical_bytes | bytea | N | — | hash 입력 정본 | immutable |
| content_sha256 | bytea | N | — | input snapshot hash | 32-byte, C14N과 UNIQUE |
| validation_status | snapshot_validation_status | N | — | VALID/INVALID | code 조합 CHECK |
| validation_code | varchar(96) | Y | — | 실패 code | INVALID 시 필수 |
| created_at | timestamptz | N | `clock_timestamp()` | 생성 | UPDATE/DELETE 금지 |

### 4.19 `scenario_run`

책임: snapshot+engine 실행 identity, 상태, terminal hash/보존. 총 **13 columns**. 예상 row: snapshot당 1~다수. 주요 조회: scenario 실행 이력/baseline. 별도 이유: 반복 실행과 partial/failed 보존 생명주기. snapshot과 합치면 replay를 덮어쓴다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| id | uuid | N | `gen_random_uuid()` | PK | PK |
| input_snapshot_id | uuid | N | — | 정확한 입력 | FK RESTRICT |
| engine_manifest_id | uuid | N | — | 정확한 엔진 | FK RESTRICT |
| replay_of_run_id | uuid | Y | — | replay 계보 | self FK RESTRICT |
| status | run_status | N | `QUEUED` | root 상태 | state trigger/CHECK |
| retention_class | retention_class | N | `STANDARD` | baseline 보존 | enum |
| requested_at | timestamptz | N | `clock_timestamp()` | 요청 | 시간 CHECK |
| started_at | timestamptz | Y | — | 시작 | 시간 CHECK |
| finished_at | timestamptz | Y | — | 종료 | terminal 필수 |
| terminal_stage_code | varchar(64) | Y | — | 마지막 stage | terminal 필수 |
| error_code | varchar(96) | Y | — | root 실패 | failed/invalid 필수 |
| result_content_hash | bytea | Y | — | semantic 결과 hash | success/partial 32-byte |
| run_record_hash | bytea | Y | — | 실행 record hash | terminal 32-byte |

run은 DB상 QUEUED로만 insert하고 허용된 전이로 terminalize한다. terminal 상태의 계산/해시/입력은 UPDATE/DELETE 불가하고 보존 metadata만 `STANDARD→BASELINE`으로 한 번 승격할 수 있다. 재실행은 새 row다.

### 4.20 `run_stage`

책임: stage별 상태/row count/error로 partial result 보존. 총 **10 columns**. 예상 row: run당 6~10. 주요 조회: 진행·partial 원인. 별도 이유: run당 반복 cardinality와 각 stage 독립 실패. run에 JSON으로 넣으면 상태 전이·유일성을 잃는다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| id | uuid | N | `gen_random_uuid()` | PK | PK |
| run_id | uuid | N | — | owner | FK RESTRICT |
| stage_code | varchar(64) | N | — | 단계 code | run 내 UNIQUE |
| stage_ordinal | smallint | N | — | 순서 | run 내 UNIQUE, `>=0` |
| status | stage_status | N | `PENDING` | stage 상태 | 시간 조합 CHECK |
| started_at | timestamptz | Y | — | 시작 | state CHECK |
| finished_at | timestamptz | Y | — | 종료 | state/time CHECK |
| produced_row_count | bigint | Y | — | 결과 수 | `>=0` |
| error_code | varchar(96) | Y | — | 오류 | service completion rule |
| created_at | timestamptz | N | `clock_timestamp()` | 생성 | terminal run 뒤 불변 |

### 4.21 `run_result`

책임: 모든 result의 run 소유권, stable key, 종류, 계산상태와 근거등급. 총 **7 columns**. 예상 row: run당 10²~10⁷. 주요 조회: run result tree/stable lookup. 별도 이유: 공통 FK root가 annotation과 subtype/run 일치를 강제하고 반복 status column을 제거한다. 하나의 거대 result table로 만들지 않아 core 값의 subtype CHECK는 유지한다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| id | uuid | N | `gen_random_uuid()` | DB PK | PK |
| run_id | uuid | N | — | 단일 run owner | FK RESTRICT |
| stable_key | varchar(128) | N | — | canonical identity | run 내 UNIQUE/형식 CHECK |
| result_kind | result_kind | N | — | subtype | composite subtype FK |
| calculation_status | calculation_status | N | — | COMPUTED/BLOCKED 등 | grade 조합 CHECK |
| decision_grade | decision_grade | Y | — | 근거 등급 | status와 직교 조합 CHECK |
| created_at | timestamptz | N | `clock_timestamp()` | append 시각 | RUNNING에만 insert, 불변 |

### 4.22 `geometric_access`

책임: 순수 기하학의 true/clipped 접촉과 최대 고도각. 총 **9 columns**. 예상 row: run/station/day당 0~20. 주요 조회: run 접촉 목록. 별도 이유: modeled/contact/capacity와 의미 및 cardinality가 다르며 순수 orbit 결과를 partial run에서도 보존한다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| result_id | uuid | N | — | PK/result root | typed composite FK |
| result_kind | result_kind | N | `GEOMETRIC_ACCESS` | subtype | 상수 CHECK |
| scenario_station_id | uuid | N | — | station revision binding | FK RESTRICT |
| true_aos | timestamptz | N | — | true AOS | start<end |
| true_los | timestamptz | N | — | true LOS exclusive | start<end |
| clipped_start | timestamptz | N | — | analysis 교차 시작 | containment CHECK |
| clipped_end | timestamptz | N | — | analysis 교차 종료 | containment CHECK |
| maximum_elevation_udeg | bigint | N | — | max elevation | 0..90e6 |
| maximum_elevation_at | timestamptz | N | — | max 시각 | true interval 내부 |

### 4.23 `modeled_contact`

책임: guard/link eligibility 적용 후 단일 modeled interval 또는 blocked/known-zero reason. 총 **7 columns**. 예상 row: geometric row당 1. 주요 조회: candidate waterfall. 별도 이유: geometric truth와 모델 가정 결과를 분리. P0 일정 availability와 fixed rate에서는 최대 한 interval이므로 별도 interval child는 만들지 않는다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| result_id | uuid | N | — | PK/root | typed FK |
| result_kind | result_kind | N | `MODELED_CONTACT` | subtype | 상수 CHECK |
| geometric_result_id | uuid | N | — | upstream | FK, UNIQUE |
| link_compatibility | compatibility_status | N | — | eligibility | enum |
| usable_start | timestamptz | Y | — | usable start | pair interval CHECK |
| usable_end | timestamptz | Y | — | usable end | pair interval CHECK |
| primary_reason_code | varchar(96) | Y | — | zero/block reason | registry service 검사 |

### 4.24 `candidate_session`

책임: 충돌 전 whole opportunity와 유일한 per-contact logical capacity 정본. 총 **5 columns**. 예상 row: modeled row당 0~1. 주요 조회: station capacity/conflict candidates. 별도 이유: scheduled 선택과 반드시 구분해야 하는 독립 의미. capacity ledger를 별도 table로 두지 않아 1:1 JOIN을 제거한다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| result_id | uuid | N | — | PK/root | typed FK |
| result_kind | result_kind | N | `CANDIDATE_SESSION` | subtype | 상수 CHECK |
| modeled_contact_result_id | uuid | N | — | upstream | FK, UNIQUE |
| capacity_bytes | numeric(20,0) | Y | — | 충돌 전 logical bytes | `>=0`; NULL=blocked |
| conflict_component_key | varchar(96) | Y | — | graph 계산 grouping | 형식 CHECK |

### 4.25 `scheduled_session`

책임: conflict 해소 뒤 선택된 candidate. 총 **5 columns**. 예상 row: candidate 이하. 주요 조회: selected timeline/unique capacity. 별도 이유: 실제 예약이 아닌 선택 결과로 독립 cardinality를 가진다. candidate와 status로 합치면 suppressed 후보와 선택 생명 의미가 섞인다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| result_id | uuid | N | — | PK/root | typed FK |
| result_kind | result_kind | N | `SCHEDULED_SESSION` | subtype | 상수 CHECK |
| candidate_result_id | uuid | N | — | 선택 candidate | FK, UNIQUE |
| selection_ordinal | integer | N | — | timeline 순서 | `>=0` |
| primary_reason_code | varchar(96) | N | — | 선택 이유 | versioned registry |

capacity column은 없다. `candidate_result_id`를 따라 읽고 scheduled unique total은 선택 candidate 합이다.

### 4.26 `transfer_allocation`

책임: payload logical byte range의 계획상 session 배치와 modeled progress. 총 **14 columns**. 예상 row: session당 0~10⁵. 주요 조회: payload 배치량/backlog. 별도 이유: session↔payload many-to-many bridge이며 반복 row가 많다. P0 observed/received byte는 없다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| result_id | uuid | N | — | PK/root | typed FK |
| result_kind | result_kind | N | `TRANSFER_ALLOCATION` | subtype | 상수 CHECK |
| scheduled_session_result_id | uuid | N | — | session | FK RESTRICT |
| scenario_payload_id | uuid | N | — | payload | FK RESTRICT |
| allocation_ordinal | integer | N | — | session 내 순서 | session 내 UNIQUE, `>=0` |
| logical_offset_start | numeric(20,0) | N | — | byte range 시작 | `>=0` |
| logical_bytes | numeric(20,0) | N | — | 계획량 | `>0`; deferred 합계 trigger |
| started_at | timestamptz | N | — | 계획 시작 | start<end |
| ended_at | timestamptz | N | — | 계획 종료/TX_END | start<end |
| modeled_progress_after_bytes | numeric(20,0) | N | — | payload 누적 progress | `>=0` |
| modeled_tx_complete_at | timestamptz | Y | — | 계획상 완료 | allocation interval 내부 |
| deadline_status | varchar(32) | Y | — | ON_TIME/LATE 등 | registry service 검사 |
| remaining_after_bytes | numeric(20,0) | N | — | 이후 backlog | `>=0` |
| primary_reason_code | varchar(96) | N | — | 배치/분할 이유 | registry service 검사 |

deferred constraint trigger가 session별 allocation 합≤선택 candidate capacity를 commit 시 검사한다. 동일 run/payload byte-range 비중첩, payload size 보존, FIXED_CHUNK 경계, time/capacity provider semantics는 core engine 결과 validator가 같은 transaction에서 검사한다.

### 4.27 `run_event`

책임: queue/storage가 공유하는 canonical timestamp/order envelope와 각 ledger의 typed byte 상태. 총 **16 columns**. 예상 row: run당 payload/allocation의 수배. 주요 조회: 시간순 queue/storage timeline. 별도 이유: 많은 반복 event와 total-order UNIQUE. 두 테이블로 분리하면 동일 시각 전역 순서를 DB에서 강제할 수 없다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| result_id | uuid | N | — | PK/root | typed FK |
| result_kind | result_kind | N | `RUN_EVENT` | subtype | 상수 CHECK |
| run_id | uuid | N | — | total-order partition | root와 composite FK |
| event_at | timestamptz | N | — | canonical UTC µs | run/time/order UNIQUE |
| event_order | integer | N | — | 같은 시각 순서 | `>=0`, UNIQUE tuple |
| event_domain | event_domain | N | — | QUEUE/STORAGE | field-group CHECK |
| event_kind | varchar(64) | N | — | versioned event code | registry |
| scenario_payload_id | uuid | Y | — | 대상 payload | FK |
| allocation_result_id | uuid | Y | — | 원인 allocation | FK |
| delta_logical_bytes | numeric(20,0) | Y | — | queue 변화 | QUEUE 전용, signed |
| remaining_logical_bytes | numeric(20,0) | Y | — | queue remainder | `>=0` |
| delta_storage_bytes | numeric(20,0) | Y | — | storage 변화 | STORAGE 전용, signed |
| occupancy_bytes | numeric(20,0) | Y | — | 점유량 | `>=0` |
| reserve_breach_bytes | numeric(20,0) | Y | — | reserve breach | `>=0` |
| rejected_bytes | numeric(20,0) | Y | — | admission reject | `>=0` |
| reason_code | varchar(96) | N | — | 사건 이유 | registry |

Storage OFF이면 STORAGE domain row가 없어야 하며 metric은 NOT_APPLICABLE이다. 이 cross-table 조건은 finalize validator가 검사한다.

### 4.28 `run_metric`

책임: versioned, exact integer KPI materialization과 비교 join key. 총 **10 columns**. 예상 row: run당 10²~10⁴. 주요 조회: KPI 화면/두 run 비교. 별도 이유: 독립 조회되는 핵심 aggregate이며 대규모 event 재집계를 피한다. finalize에서 base results와 일치 검증한다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| result_id | uuid | N | — | PK/root | typed FK |
| result_kind | result_kind | N | `METRIC` | subtype | 상수 CHECK |
| metric_code | varchar(96) | N | — | 의미 | 대문자 형식 CHECK |
| scope_code | varchar(64) | N | — | INTERNAL 등 | 대문자 형식 CHECK |
| scenario_station_id | uuid | Y | — | station 차원 | payload와 최대 하나 |
| scenario_payload_id | uuid | Y | — | payload 차원 | station과 최대 하나 |
| unit_code | varchar(32) | N | — | BYTE/US/COUNT | comparison key |
| definition_revision | varchar(96) | N | — | metric 공식 | comparison key |
| accounting_layer | varchar(32) | Y | — | LOGICAL_PAYLOAD 등 | comparison key |
| value_integer | numeric(39,0) | Y | — | exact 값 | NULL=blocked/N/A |

candidate/scheduled totals는 조회 성능과 공식 KPI 보존 때문에 materialize한다. terminal finalize 전 engine이 base row에서 재계산해 불일치면 run을 INVALID로 만든다.

### 4.29 `run_annotation`

책임: warning/validation/decision reason의 공통 envelope와 typed comparison criterion row. 총 **14 columns**. 예상 row: run당 10²~10⁵. 주요 조회: 특정 결과의 경고·선택/억제 이유. 별도 이유: 결과당 반복 cardinality와 별도 조회. warning/decision을 분리하면 공통 code/severity/subject 구조가 중복된다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| result_id | uuid | N | — | annotation root/PK | typed FK |
| result_kind | result_kind | N | `ANNOTATION` | subtype | 상수 CHECK |
| subject_result_id | uuid | Y | — | 설명 대상 | 실제 result FK |
| annotation_kind | annotation_kind | N | — | warning/decision/validation | enum |
| code | varchar(96) | N | — | machine code | registry |
| severity | annotation_severity | N | — | INFO/WARNING/ERROR | enum |
| ordinal | integer | N | — | subject 내 표시순 | `>=0` |
| rule_revision | varchar(96) | N | — | 해석 rule | — |
| compared_result_id | uuid | Y | — | 비교 후보 | 실제 result FK |
| criterion_code | varchar(96) | Y | — | objective/tie-break 항목 | registry |
| criterion_value_integer | numeric(39,0) | Y | — | exact 비교값 | text와 XOR/none |
| criterion_value_text | varchar(256) | Y | — | enum/key 비교값 | integer와 XOR/none |
| unit_code | varchar(32) | Y | — | criterion 단위 | service 조합 검사 |
| message | varchar(1000) | Y | — | 사람이 읽는 설명 | code를 대체하지 않음 |

여러 reason code/compared candidate는 배열 JSON이 아니라 ordinal별 반복 row로 보존한다. subject/compared result가 같은 run인지는 finalize validator가 검사한다.

### 4.30 `audit_event`

책임: archive/tombstone/baseline/finalize 같은 보안·보존 행위의 append-only 감사. 총 **13 columns**. 예상 row: 행위당 1. 주요 조회: subject/time audit. 별도 이유: 독립 보존·접근 권한. 범용 문자열 polymorphic FK 대신 nullable 실제 FK 4개와 exactly-one CHECK를 사용한다.

| Column | PostgreSQL Type | Null | Default | 역할 | 무결성 |
| ------ | --------------- | ---: | ------- | -- | --- |
| id | uuid | N | `gen_random_uuid()` | PK | PK |
| occurred_at | timestamptz | N | `clock_timestamp()` | 사건 시각 | — |
| action_code | varchar(64) | N | — | 행위 code | 형식 CHECK |
| evidence_source_id | uuid | Y | — | source subject | FK/XOR |
| profile_id | uuid | Y | — | profile subject | FK/XOR |
| scenario_id | uuid | Y | — | scenario subject | FK/XOR |
| run_id | uuid | Y | — | run subject | FK/XOR |
| actor_ref | varchar(128) | N | — | 외부 IAM opaque ID | 개인정보/메일 비저장 |
| reason | varchar(1000) | N | — | 감사 이유 | 필수 |
| request_id | uuid | Y | — | 요청 상관 ID | — |
| previous_state | varchar(64) | Y | — | 이전 상태 | — |
| new_state | varchar(64) | Y | — | 이후 상태 | — |
| event_sha256 | bytea | N | — | 감사 record hash | 32-byte, 불변 |

## 5. 삭제·archive·불변성 정책

| 대상 | 정책 |
|---|---|
| source/profile/scenario head | DELETE trigger 거부. `archived_at` 또는 source `TOMBSTONED` 사용 |
| source revision | insert 즉시 immutable; 민감 artifact 제거 시 revision을 수정하지 않고 external object 삭제+tombstone+audit |
| draft revision | 발행 전 typed child와 evidence 편집 가능 |
| published revision/children | UPDATE/DELETE trigger 거부; 수정은 새 revision |
| input snapshot/engine manifest | insert 즉시 UPDATE/DELETE 금지 |
| running run | 허용된 상태 전이와 append-only result만 허용 |
| terminal run/result | result와 run semantic/hash는 UPDATE/DELETE 금지. 보존 metadata만 `STANDARD→BASELINE` 1회 승격 가능; 모든 terminal run 기본 보존 |
| migration | 과거 `canonical_bytes`, input/result/run hash를 rewrite하지 않음. 새 decoder/upcaster와 새 run 사용 |

head의 ID/stable key/kind는 trigger로 고정하고 current pointer는 같은 head의 PUBLISHED revision만 허용한다. source tombstone은 terminal이다. head archive, current pointer 변경, source tombstone, baseline 승격, terminal finalize는 application transaction에서 `audit_event`와 함께 commit한다. DB role은 DELETE 권한을 받지 않는다.

## 6. 주요 조회, index와 예상 JOIN 수

JOIN 수는 API가 한 SQL/CTE로 aggregate를 읽을 때의 대표값이다. UUID PK와 모든 UNIQUE는 PostgreSQL이 자동 index를 만든다.

| # | 조회 | 핵심 index | 예상 JOIN |
|---:|---|---|---:|
| 1 | 사용 가능한 위성·지상국 preset | `profile_kind_active_idx` → current revision/subtype | 2 |
| 2 | profile revision 이력 | `profile_revision_history_idx` | 0(공통 metadata), subtype 포함 1 |
| 3 | 시나리오 구성 전체 | scenario revision PK, `scenario_station_load_idx`, `scenario_payload_ready_idx`, dependency PK | root별 2~4; 3개 batch query 권장 |
| 4 | 실행 당시 input snapshot | run PK→snapshot PK; `snapshot_scenario_idx` | 1, authored 근거까지 3~5 |
| 5 | 특정 run 접촉창 | `result_run_kind_idx`, geometric PK, `geometric_station_time_idx` | 1; station명 포함 4 |
| 6 | run의 지상국별 candidate/scheduled 용량 | result kind index, modeled/geometric/station path indexes | 5~6; station dimension metric 사용 시 2 |
| 7 | payload별 배치량/backlog | `allocation_payload_idx`, `event_payload_idx`, payload PK | allocation 2, final event 2; materialized metric 2 |
| 8 | 시간순 queue/storage event | `event_run_timeline_idx` | 0 (`run_event`에 run_id 보유), payload명 포함 1 |
| 9 | 두 run metric 비교 | 두 run의 `result_run_kind_idx` + `metric_compare_idx` self-join | 2(각 root), metric끼리 self-join 1 |
| 10 | 결과의 입력·출처·결정 근거 | annotation subject index → run/root → snapshot/scenario → evidence/source | 보통 5~7, progressive load 권장 |

`run_metric` 비교 SQL의 호환 key는 다음과 같다.

```sql
metric_code, scope_code, station/payload stable dimension,
unit_code, definition_revision, accounting_layer
```

baseline 0의 ratio와 불일치 metric delta는 저장하지 않는다. API read model이 `INCOMPATIBLE_UNIT`, `INCOMPATIBLE_DEFINITION`, `BASELINE_ZERO`, `COMPARABLE_WITH_EVIDENCE_DIFFERENCE`를 반환한다. 이름 검색이 실제 병목으로 확인되기 전에는 trigram extension/index를 추가하지 않는다. `canonical_payload`에도 GIN index를 만들지 않는다. 정본 조회는 typed FK/hash이며 snapshot JSON ad-hoc 검색은 P0 핵심 경로가 아니다.

## 7. JSONB 사용 위치

JSONB는 정확히 두 목적 중 현재 하나만 쓴다.

1. `input_snapshot.canonical_payload`: 고정 JSON Schema의 immutable inspection copy.
2. `evidence_source_revision.raw_import_payload`: 원본 import payload 보존.

핵심 계산은 두 JSONB를 직접 조회해 수행하지 않는다. resolver가 typed revision/child row를 검증해 snapshot을 만들고 engine은 전달받은 versioned contract를 사용한다. `canonical_bytes`가 hash 정본이며 PostgreSQL JSONB의 내부 key order는 정본이 아니다.

### JSON Schema와 canonical 규칙

- schema ID: 예시 `urn:semantix:passbudget:input-snapshot:0.1`; row의 `json_schema_id`에 저장.
- root는 `additionalProperties=false`; 각 array item에도 명시적 schema version과 stable key가 있다.
- `PB-C14N-JSON-V1`: UTF-8/NFC/LF, lexical object key, exact integer는 base-10 string, rational은 기약 `{n,d}`, timestamp는 UTC 6자리 µs, enum은 대문자 ASCII.
- 의미상 set 배열은 registry stable key로 정렬하고 rate/allocation처럼 순서가 의미 있는 배열은 ordinal을 보존한다.
- `OMITTED`, `UNKNOWN`, `NOT_APPLICABLE`, known `0`, defaulted `0`는 서로 다른 explicit object로 직렬화한다.
- SHA-256 framing은 v1.5의 `SEMANTIX_PASSBUDGET\0<INPUT|RESULT|RUN>\0PB-C14N-JSON-V1\0` 계약을 따른다.
- index: `(content_sha256, canonicalization_revision)` UNIQUE만 둔다. raw import는 기본 index 없음. 운영상 특정 provider metadata 탐색이 입증될 때 expression index를 migration으로 추가한다.

renderer 설정은 P0 DB에 저장하지 않는다. provider 비핵심 metadata가 실제로 필요해질 때 고정 schema/version을 가진 별도 revision subtype에서만 JSONB를 검토한다.

## 8. 통합 후보 10개 검토

| 후보 | 합치면 감소 | 잃는 FK/CHECK | JOIN/조회 변화 | nullable 증가 | P1·P2 영향 | 최종 선택 |
|---|---:|---|---|---:|---|---|
| 위성·궤도·지상국 공통 head | 5 tables | kind별 head 자체에는 손실 없음; composite kind FK 필요 | preset 목록 단순, subtype 상세 +1 JOIN | head 0 | 새 profile kind 추가 쉬움 | **head 통합**, typed revision 분리 |
| profile별 revision metadata | 5 tables | subtype-kind 일치가 약해질 수 있음 | history 단순, 상세 +1 JOIN | metadata 0 | provider subtype 추가 용이 | **metadata 통합**, composite FK/CHECK로 kind 강제 |
| evidence source/source revision | 1 table | revision `(source,revision_no)`와 immutable 인용 경계 상실 | 현재 +1 JOIN | 합치면 source마다 최신/과거 column 혼합 | redaction/tombstone 어려움 | **분리** |
| geometric/modeled/candidate/scheduled 공통 result root | subtype까지 전부 합치면 4 tables | 단계별 NOT NULL/FK/1:1 및 capacity 의미 상실 | timeline 한 table이나 조건식 복잡 | 매우 큼 | 새 결과가 만능 row를 악화 | **root만 통합**, 4 subtype 분리 |
| queue/storage event envelope | 1 table | 분리하면 cross-domain same-time UNIQUE 불가; 통합 시 domain CHECK 필요 | 시간순 조회 0 JOIN | 4+4 domain column nullable | P2 actual event는 별도 context/table로 추가 | **통합** |
| warning/decision reason | 1 table | 통합 시 criterion 조합 CHECK 필요 | 근거 패널 단순 | decision 전용 5 nullable | reason 종류 확장 쉬움 | **통합** `run_annotation` 반복 row |
| metric/comparison metric | 1 table | 저장 비교는 source metric 변경/호환성 중복 위험 | self-join +1, write/invalidations 제거 | 0 | 새 metric revision도 자동 비교 | **comparison metric 비저장**, `run_metric` self-join |
| preset item subtype | 최대 3 tables | 범용 item FK는 kind/role 무결성 약화 | 별도 preset graph는 JOIN 증가 | override nullable 다수 | 새 subtype마다 validator 분기 | **별도 preset item 제거**, 동일 profile/scenario revision을 preset으로 표시·clone |
| run state/run stage | 1 table | stage cardinality/partial 결과/순서 UNIQUE 상실 | 분리 시 stage 화면 +1 JOIN | 합치면 반복 stage JSON/columns | pipeline stage 추가 어려움 | **분리** |
| trace node/edge vs 명시 FK | trace 2 tables 제거 | 범용 graph 제거로 임의 edge는 못 저장하지만 핵심 lineage FK 강화 | 핵심 trace JOIN이 예측 가능 | 0 | 새로운 계산 단계는 result subtype/FK migration | **trace graph 제거**, root stable key+typed FK+annotation |

## 9. P1·P2 확장 경계

| 확장 | P0 의미를 바꾸지 않는 추가 방식 |
|---|---|
| 새 orbit provider | 새 enum/value와 새 typed subtype 또는 provider-detail child; 기존 `orbit_revision`/snapshot decoder 유지 |
| Physical RF link | 새 communication provider revision + rate-segment/result subtype. 기존 FIXED provider row 불변 |
| Wire Estimator | `transfer_profile_revision`, `wire_estimate` 별도 context/result. `logical_bytes` 의미 불변 |
| availability/horizon mask | station-policy child revision과 modeled interval child 추가. P0 constant mask 의미 불변 |
| manual lock/eviction | 별도 scenario constraint/policy subtype; P0 nullable 선추가 없음 |
| actual received/verified/ACK | P2 observed-event aggregate와 allocation correlation FK. `run_event`의 modeled P0 event에 실제 byte를 추가하지 않음 |
| calibration | observed run을 입력으로 받는 별도 calibration profile/revision |
| fleet scheduler | fleet scenario aggregate와 resource graph 신규. P0 `tx_capacity_units=1` 변경 금지 |

enum에 새 값을 추가하는 migration은 가능하지만 기존 row 의미를 바꾸지 않는다. 의미가 달라지는 경우 새 enum code와 schema/provider revision을 만든다. 과거 snapshot canonical bytes/hash는 backfill하거나 최신 형태로 재직렬화하지 않는다.

## 10. 보안·공개 저장소·복구

- migration owner `pb_migrator`와 runtime group role `pb_application`을 배포 환경에서 분리한다. migration role만 DDL, application은 필요한 SELECT/INSERT와 mutable head/run-state UPDATE만 받으며 DELETE와 immutable table UPDATE는 받지 않는다.
- login role과 실제 credential은 secret manager/환경변수로 주입한다. 저장소의 `.env.example`에는 `DATABASE_URL=postgresql://passbudget_app:CHANGE_ME@localhost:5432/passbudget` 같은 가짜 로컬 값만 둔다.
- 실제 DB password, IP, SSH 사용자/key, 개인 경로, 비공개 KMU 문서, token, 이메일/이름을 seed·migration·문서에 넣지 않는다.
- `actor_ref`는 외부 IAM opaque ID이며 개인정보를 복제하지 않는다. source locator는 `https://`, `urn:`, `artifact:`만 허용하고 제어문자·`file://`·개인 절대경로를 거부한다.
- upload는 API에서 MIME allowlist, 크기 제한, malware scan, content hash, safe object key를 검증한다. DB에는 파일 body/로컬 경로 대신 hash와 opaque locator만 둔다. 원본 JSON import만 크기 제한 후 보존 가능하다.
- tombstone은 인용 identity/hash를 남기고 민감 artifact locator 접근을 차단한다. 같은 transaction의 `audit_event`가 사유·요청 ID·상태 전이를 기록한다.
- dump는 encrypted, 접근통제, point-in-time recovery 대상으로 운영한다. `*.dump`, `*.sql.gz`, `pgdata/`, 사용자 export와 실행 artifact directory를 `.gitignore`한다. 공개 fixture만 별도 seed에 둔다.
- 복구 시험은 snapshot/hash 보존, terminal result row 수, audit chain hash를 확인한다. baseline/terminal run은 보존정책 만료 자동삭제 대상이 아니다.

## 11. 기존 43개 예상안 제거·통합

v1.5에는 확정된 “43개 물리 table manifest”가 없고 논리 aggregate/child 후보만 제시되어 있다. 아래는 문서에 이름이 나온 논리 후보를 **43개 물리 후보로 재구성한 비교표**다. 존재하지 않는 기존 DDL을 사실처럼 인용하지 않는다.

| 기존 논리 후보(개수) | v0.1 처리 | 감소 | 이유 |
|---|---|---:|---|
| Spacecraft/Orbit/GroundStation/Communication/PayloadType/Policy head (6) | 공통 `profile` 1 | 5 | 동일 head lifecycle/권한/조회 |
| 위 6종 revision metadata (6) | 공통 `profile_revision` 1 + 계산 field가 있는 5 typed subtype; spacecraft는 공통 revision | metadata 5 | revision 번호/발행/hash 중복 제거, P0 spacecraft는 별도 field 없음 |
| StorageProfile + StorageProfileRevision (2) | `scenario_revision`의 P0 storage group | 2 | P0 0..1, 동일 lifecycle/owner |
| Preset + PresetRevision + PresetItem (3) | `profile/scenario.is_preset` + 기존 revision clone | 3 | 검증 약한 polymorphic item 제거 |
| EvidenceSource + SourceRevision + EvidenceAssertion (3) | 3개 유지 | 0 | 서로 다른 lifecycle/cardinality/redaction |
| Scenario + ScenarioRevision (2) | 2개 유지 | 0 | mutable head/immutable revision |
| ScenarioStation + ScenarioLinkBinding (2) | `scenario_station` 1 | 1 | P0 station당 단일 RX/comm binding |
| ScenarioPayload + PayloadDependency (2) | 2개 유지 | 0 | instance와 M:N edge |
| EngineManifest + InputSnapshot + ScenarioRun + RunStage (4) | 4개 유지 | 0 | 독립 lifecycle/보존/cardinality |
| ResultNode (1) | `run_result` 유지 | 0 | common identity/status/FK root |
| GeometricAccess + ModeledContact + ModeledContactInterval (3) | geometric + modeled 2 | 1 | P0는 modeled interval 최대 1개 |
| CandidateSession + CapacityLedgerItem + ConflictSet + ConflictEdge + ScheduledSession (5) | candidate + scheduled 2, component key | 3 | 1:1 ledger/범용 graph 제거, 후보/선택은 분리 |
| TransferAllocation (1) | 유지 | 0 | session↔payload cardinality |
| QueueEvent + StorageEvent (2) | `run_event` 1 | 1 | 동일 timestamp total order |
| RunMetric + ComparisonMetric (2) | `run_metric` 1, comparison read model | 1 | delta 중복/불일치 방지 |
| **합계 43** | 위 core는 25 tables | **18 감소** | 이후 `run_annotation`, `audit_event`와 보강 subtype을 포함한 최종 30 |

최종 30에는 위 재구성에 별도 후보로 잡지 않았던 warning/decision 통합 envelope와 보안 audit가 포함된다. 30을 초과하지 않으므로 초과-table 정당화 표는 필요 없다.

## 12. record 단위 사용 사례 검증

### 사례 A — 새 위성 도구 사용

1. `profile(SPACECRAFT)` head와 draft `profile_revision`을 만든다. P0의 단일 TX resource key는 spacecraft stable key에서 canonical하게 만들고 `capacity_units=1`은 schema/engine 계약으로 고정한 뒤 발행한다.
2. 별도 `profile(ORBIT)`에 `orbit_revision(VIRTUAL_CIRCULAR)`를 만들고 epoch/반경/고도/경사/RAAN/위상을 evidence와 함께 발행한다.
3. 두 `profile(GROUND_STATION)`과 각 typed revision을 만든다.
4. `profile(COMMUNICATION)` revision을 `FIXED_RATE` 또는 `FIXED_CAPACITY_PER_CONTACT`로 발행한다.
5. `scenario`+`scenario_revision(NETWORK_ONLY)`와 `scenario_station` 두 row를 만든다. policy와 storage group은 DB CHECK상 NULL/DISABLED다.
6. publish validator가 evidence/provider 조합을 검사하고 `input_snapshot` canonical bytes/hash를 insert한다.
7. `scenario_run`을 QUEUED→RUNNING으로 전이하고 stage를 연다.
8. 각 pass마다 `run_result+geometric_access→modeled_contact→candidate_session`; 선택 후보만 `scheduled_session`; KPI는 `run_metric`에 저장한 뒤 terminal hash와 함께 SUCCEEDED로 전이한다. NETWORK_ONLY에는 allocation/queue/storage event가 없다.

### 사례 B — 스펙 수정

1. 기존 published subtype UPDATE는 trigger가 거부한다.
2. 같은 head에 `revision_no+1`, `based_on_revision_id`로 새 revision을 발행한다.
3. 과거 run은 옛 `input_snapshot`/typed revision을 계속 참조하므로 current pointer 변경과 무관하다.
4. 새 scenario revision이 새 profile revision ID를 선택하고 새 snapshot/run을 만든다.
5. 두 terminal run의 canonical input diff를 먼저 표시하고 compatible `run_metric` self-join으로 delta를 계산한다. 기존 metric은 수정하지 않는다.

### 사례 C — 데이터 장바구니

1. 네 `scenario_payload` row가 각각 exact logical size/ready/priority를 갖고, 필요하면 네 payload type revision을 재사용한다.
2. scenario revision은 QUEUE_AWARE와 정확한 policy revision을 참조한다.
3. 여러 session의 `transfer_allocation`이 Original byte range를 나눠 담고 deferred trigger가 각 session capacity 합을 검사한다.
4. `run_event(QUEUE)`와 payload dimension `run_metric`이 progress/backlog/deadline miss를 보존한다.
5. Storage OFF면 storage column group은 NULL이고 STORAGE event가 없으며 storage metric root는 NOT_APPLICABLE/value NULL이다.
6. Storage ON 새 revision/run에서는 footprint와 initial manifest를 검증하고 `run_event(STORAGE)`가 occupancy/reserve breach/rejected bytes를 기록한다. P0 기본에는 eviction이 없다.

### 사례 D — 다른 사용 목적

1. `is_preset=false`인 새 spacecraft/orbit profile을 만든다.
2. 새 station/communication revision을 선택한다.
3. 어떤 FK도 `PB-GOLDEN-CORE-01`을 요구하지 않는다. fixture는 `TEST_FIXTURE` source와 preset flag일 뿐이다.
4. scenario revision/snapshot/run UUID 및 run-scoped stable-key namespace가 달라 결과가 섞이지 않고, `(run_id,stable_key)` UNIQUE가 교차 run 공유를 막는다.

## 13. 남은 위험과 필수 결정

| 항목 | 상태/위험 | 결정 또는 완료조건 |
|---|---|---|
| VIRTUAL_CIRCULAR provider/constants | 미확정 | provider/상수 revision과 독립 fixture 확정 |
| GP_TLE 독립 oracle | release blocker | frozen input, static expected pass table, cross-tool tolerance |
| canonical vectors | release blocker | production/reference 구현의 bytes/hash 일치 |
| evidence registry | 구현 결정 | field code별 cardinality, 필수 source, normalized fingerprint 규칙 동결 |
| result finalize validator | 구현 결정 | subtype↔root 상태, same-run FK path, metric 재계산, payload byte conservation 원자적 검사 |
| source redaction storage | 운영 ADR | object store tombstone/retention/restore와 audit 연결 |
| KMU 정책값 | fixture만 가능 | Mission Product Owner가 MANDATORY/severity/value/bundle 승인 |
| OBDH storage semantics | PROXY | footprint/reclaim/chunk 근거 확보 전 CONCEPT_ONLY |
| PostgreSQL version | v0.1 기준 16+ | CI에서 clean DB migration 및 downgrade/restore rehearsal |

이 스키마의 다음 구현 gate는 clean PostgreSQL 16에 DDL 적용, 사례 A~D seed transaction, trigger 음성시험, persistence round-trip 뒤 canonical/hash 불변 시험이다.

---

## 14. v0.2 delta — contact source provenance

v0.1 DDL(`db/postgresql/schema_v0_1.sql`)은 변경하지 않는다. 아래 delta는
`db/postgresql/schema_v0_2_contact_source.sql`이 담고 Alembic `0002_contact_source_provenance`가 적용한다.
근거는 `docs/architecture/ADR-0002-synthetic-contact-provenance.md`와
`schema_decisions.md` ADR-020이다.

새 enum: `contact_source_kind AS ENUM ('ORBIT_DERIVED', 'SYNTHETIC_INJECTED')`

| 테이블 | 변경 | 이유 |
|---|---|---|
| `scenario_revision` | `contact_source` 추가(NOT NULL, 기본 `ORBIT_DERIVED`), `synthetic_contact_provider_revision varchar(96)` 추가, `orbit_revision_id`의 NOT NULL 해제, `scenario_contact_source_ck` 추가, `UNIQUE (id, contact_source)` 추가 | 합성 주입 접촉에 가짜 궤도 revision을 만들지 않으면서 실제 궤도 시나리오의 필수 orbit revision 계약은 유지 |
| `scenario_station` | `contact_source` 추가, `scenario_revision(id, contact_source)`로의 composite FK, `UNIQUE (id, contact_source)` | 자식 행이 시나리오의 접촉 출처와 어긋날 수 없게 함 |
| `geometric_access` | `contact_source` 추가, `scenario_station(id, contact_source)`로의 composite FK, `maximum_elevation_udeg/at`의 NOT NULL 해제, `geometric_peak_time_ck` → `geometric_elevation_source_ck` 교체 | `ORBIT_DERIVED`는 최대고도각과 그 시각을 계속 필수로 요구하고(범위·순서 CHECK 포함), `SYNTHETIC_INJECTED`는 두 값이 NULL이어야 함 |

테이블 수는 30개 그대로다. 인덱스 `scenario_revision_contact_source_idx`가 추가된다.

`downgrade`는 v0.1 계약을 정확히 복원하되, `SYNTHETIC_INJECTED` 행이 하나라도 있으면
행 수를 세어 명시적으로 실패한다. v0.1에는 그 행을 표현할 방법이 없으므로 값을 지어내거나
데이터를 지우지 않는다. 이 downgrade는 폐기 가능한 개발 DB 용도다.

---

## 15. persistence tier에서의 위치 (2026-09-03 추가)

이 문서는 **선택적 PostgreSQL 서버 tier**의 물리 스키마를 기술한다. 2026-09-03 PM 결정으로
PassBudget의 기본 실행은 DB 없는 계산 CLI이고 로컬 영속 기본값은 SQLite다. PostgreSQL은
폐기되지 않았고 공유·다중 사용자 배포용으로 계속 유지된다.

- 로컬 tier의 물리 스키마: `db/sqlite/schema_v1.sql`
- tier 결정과 두 스키마의 차이(정확 정수 표현, enum, downgrade 정책): `docs/architecture/ADR-0003-persistence-tiers.md`
- 이 문서의 DDL 경로는 `db/postgresql/` 아래로 이동했다.

두 스키마가 어긋나면 `tests/integration/test_repository_equivalence.py`가 실패한다.
