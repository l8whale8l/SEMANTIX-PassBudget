# SEMANTIX PassBudget P0 Schema Decisions

상태: `ACCEPTED_FOR_V0.1`  
기준 문서: `골든시나리오설계도.md` v1.5  
권위: 27 → 26 → 25 → 24 → 23 → 22장

## ADR-001 — 공통 profile head와 revision metadata

- 결정: `profile`과 `profile_revision`을 모든 P0 기준정보가 공유하고, 계산 필드는 kind별 typed revision subtype에 둔다. 별도 P0 물리 field가 없는 SPACECRAFT만 공통 revision 자체가 typed identity다.
- 대안: 종류마다 head/revision 두 테이블; 모든 값을 단일 JSONB revision에 저장.
- 선택 이유: head와 revision metadata는 lifecycle·소유자·archive·history query가 같지만 궤도·좌표·rate 규칙은 서로 다른 CHECK가 필요하다.
- 장점: head/revision table 10개 감소, 공통 immutability 한 곳, preset 목록 단순화, typed FK 유지.
- 단점: subtype 상세에 1 JOIN, `profile_kind` composite FK와 publish validator 필요.
- 영향을 받는 요구사항: 중복 최소화, revision 유일성, preset 목록, 새 provider 확장.
- 향후 변경 조건: subtype별 보안/보존정책이 실제로 달라지거나 단일 subtype의 write volume이 병목이면 해당 kind만 별도 aggregate로 분리한다.

## ADR-002 — Orbit은 spacecraft identity revision과 독립

- 결정: spacecraft identity와 orbit provider 입력을 별도 profile revision으로 유지한다. P0 spacecraft TX key는 spacecraft stable key에서 canonical 생성하고 동시 송신 수 1은 engine/schema 계약이다.
- 대안: spacecraft revision에 orbit column 포함; scenario에 orbit literal 직접 포함.
- 선택 이유: 궤도는 spacecraft identity/hardware보다 자주 바뀌고 source/validity/provider가 독립적이다.
- 장점: TLE 갱신이 spacecraft revision을 복제하지 않음, 가상/실제 궤도 비교와 source history 명확.
- 단점: spacecraft에 P1 hardware field가 생기면 그때 typed subtype이 필요하다.
- 영향을 받는 요구사항: 사례 B, GP_TLE/VIRTUAL_CIRCULAR, 과거 run 불변.
- 향후 변경 조건: 없다. P1 provider는 새 orbit subtype/context로 추가한다.

## ADR-003 — P0 orbit provider는 하나의 typed tagged union

- 결정: `orbit_revision`에 `GP_TLE`와 `VIRTUAL_CIRCULAR` 상호배타 column group을 둔다.
- 대안: provider별 table; orbit JSONB.
- 선택 이유: P0 variant가 정확히 2개이고 공통 epoch/frame/time/propagator가 많다. CHECK로 상호배타성을 충분히 강제할 수 있다.
- 장점: union query/테이블 감소, typed 값과 범위 검사 유지.
- 단점: provider별 nullable column이 생긴다. UNKNOWN draft도 허용하므로 publish validation이 필요하다.
- 영향을 받는 요구사항: JSONB 제한, UNKNOWN 보존, P0 feature gate.
- 향후 변경 조건: OMM/OEM/Cartesian처럼 반복 segment/large artifact/provider별 보안이 생기면 별도 child subtype을 추가하고 기존 두 variant는 변경하지 않는다.

## ADR-004 — 최소 앙각과 communication binding은 scenario station 소유

- 결정: GS revision은 좌표/RX resource만 소유하고 `scenario_station`이 minimum elevation, eligibility, exact communication revision을 소유한다.
- 대안: 최소 앙각을 GS master에 저장; 별도 `scenario_link_binding` table.
- 선택 이유: 최소 앙각은 scenario 정책이며 P0는 station 선택마다 정확히 한 RX/communication binding을 사용한다.
- 장점: 같은 좌표 사실의 단일 정본, P0 1:1 JOIN 제거, 사례 B clone diff가 명확.
- 단점: P1 다중 antenna/RF binding에는 새 child가 필요하다.
- 영향을 받는 요구사항: UX-015, DATA-007, 새 지상국/네트워크 비교.
- 향후 변경 조건: 한 station에 동시 다중 receiver/profile 또는 band별 eligibility가 필요하면 `scenario_link_binding`을 추가한다.

## ADR-005 — Storage profile table을 만들지 않음

- 결정: P0 storage mode와 설정은 `scenario_revision`의 상호의존 CHECK column group에 둔다.
- 대안: storage head/revision; storage JSONB.
- 선택 이유: P0 storage는 scenario당 0..1이고 소유자·revision·보존·조회가 scenario와 완전히 같다.
- 장점: 2 tables/조회 감소, ON/OFF 입력 계약을 DB CHECK로 강제, DISABLED와 0B 구분.
- 단점: scenario revision에 P0 optional nullable column 8개가 생기며 reusable storage preset을 독립 선택할 수 없다.
- 영향을 받는 요구사항: AC-48/53, Storage ON 입력 요구, table 제한.
- 향후 변경 조건: storage 설정이 여러 scenario에서 독립 revision/승인/보안 정책으로 재사용될 때 profile subtype으로 승격한다.

## ADR-006 — Preset은 별도 polymorphic item graph가 아님

- 결정: `profile.is_preset`과 `scenario.is_preset`을 사용하고 기존 immutable revision을 clone한다.
- 대안: preset/preset_revision/preset_item 및 type+target string; subtype별 preset item table.
- 선택 이유: P0 preset은 결국 실행 가능한 scenario/profile revision이며 별도 graph는 검증되지 않는 polymorphic 관계를 만든다.
- 장점: 3 tables 제거, fixture 하드코딩 없음, 직접 입력과 preset이 동일 validation 경로 사용.
- 단점: 여러 scenario에 임의 부품 조합을 overlay하는 범용 preset 언어는 없다.
- 영향을 받는 요구사항: KMU fixture/preset, 사례 D, preset item 통합 후보.
- 향후 변경 조건: 조합형 preset marketplace가 실제 P1 요구가 되면 role별 실제 FK가 있는 typed composition aggregate를 만든다.

## ADR-007 — Evidence는 typed 값의 정본이 아니라 결합 envelope

- 결정: 값은 domain column에 저장하고 `evidence_assertion`은 owner stable key+field code, 상태 축, source revision, normalized value fingerprint만 저장한다.
- 대안: 범용 EAV; 각 numeric column마다 source/status column 반복; snapshot JSON에만 evidence 저장.
- 선택 이유: field-level trace와 UNKNOWN/OMITTED/N/A/0 구분을 유지하면서 계산값의 type CHECK를 잃지 않아야 한다.
- 장점: typed 계산/인덱스, source 재사용, 다른 값에 assertion 재사용 탐지.
- 단점: field-code registry와 publish resolver가 필요하고 owner child는 stable key로 지정된다.
- 영향을 받는 요구사항: DATA-006/011/013/047, PROXY gate, 근거 패널.
- 향후 변경 조건: 특정 field가 독립 승인 workflow/반복 측정 aggregate가 되면 전용 evidence child table로 승격한다.

## ADR-008 — 자기완결 canonical snapshot과 engine manifest 분리

- 결정: run은 정확히 하나의 immutable `input_snapshot`과 하나의 immutable `engine_manifest`를 참조한다. snapshot은 typed resolution 결과의 canonical bytes/hash와 inspection JSON을 함께 보존한다.
- 대안: run 시 최신 profile 조회; scenario revision hash만 저장; JSONB만 정본으로 사용.
- 선택 이유: current pointer가 바뀌어도 과거 실행과 hash가 절대 달라지면 안 된다.
- 장점: 재현성, replay 비교, canonical vector 시험, source/default 포함 hash.
- 단점: typed row와 inspection JSON이 물리적으로 함께 존재하지만 authoritative 역할이 다르며 resolver가 필요하다.
- 영향을 받는 요구사항: AC-19/41/43, immutable snapshot, migration no-rewrite.
- 향후 변경 조건: canonicalization/schema 변경 시 기존 bytes를 수정하지 않고 새 version/decoder를 추가한다.

## ADR-009 — Result root는 통합하고 단계별 subtype은 분리

- 결정: `run_result`가 run/stable-key/status/grade를 공통 소유하고 geometric, modeled, candidate, scheduled, allocation, event, metric, annotation을 typed subtype으로 분리한다.
- 대안: 모든 결과를 JSONB; 모든 단계를 한 table+status; 공통 root 없이 각 table에 run/status 반복.
- 선택 이유: 공통 run-local uniqueness와 annotation FK를 강제하면서 단계별 의미·NOT NULL·FK를 보존해야 한다.
- 장점: `(run_id,stable_key)` 단일 UNIQUE, 상태/등급 조합 한 곳, 단계 혼동 방지.
- 단점: subtype 조회마다 root 1 JOIN, subtype-kind publish/finalize validation 필요.
- 영향을 받는 요구사항: 8단계 의미 구분, branch-local status, trace, terminal 불변.
- 향후 변경 조건: 새 result kind는 새 subtype과 enum/schema revision으로 추가한다.

## ADR-010 — Candidate capacity만 저장하고 scheduled capacity는 파생

- 결정: per-contact logical capacity는 `candidate_session.capacity_bytes` 한 곳에 저장한다. scheduled session은 selected candidate FK만 갖고, scheduled unique capacity는 그 합이다.
- 대안: candidate/scheduled/planned capacity를 각 table에 복사; 공통 capacity ledger.
- 선택 이유: 같은 사실을 여러 상태에서 수정 가능하게 만들면 충돌 전/후/할당량이 쉽게 불일치한다.
- 장점: 단일 정본, 억제 후보 보존, allocation 합 constraint의 명확한 상한.
- 단점: scheduled list에서 capacity를 위해 1 JOIN, official aggregate metric과 base 합 일치 finalize 검사 필요.
- 영향을 받는 요구사항: candidate vs scheduled vs allocation, PBT-02/06.
- 향후 변경 조건: provider가 session 선택 자체에 따라 capacity를 변화시키면 새 scheduled-capacity result subtype을 만들고 의미/definition revision을 별도 부여한다.

## ADR-011 — Queue와 Storage event envelope 통합

- 결정: `run_event` 한 table이 `(run_id,event_at,event_order)` total order와 domain discriminator를 공유하고 queue/storage byte fields는 CHECK로 분리한다.
- 대안: queue_event/storage_event 두 table; 범용 JSON event.
- 선택 이유: 같은 시각의 release→admit→allocate 순서를 DB UNIQUE로 보존하려면 공통 envelope가 필요하다.
- 장점: 시간순 조회 0 JOIN, AC-40 결정성, table 1개 감소.
- 단점: domain 전용 nullable column과 event registry validator가 필요하다.
- 영향을 받는 요구사항: storage event total order, Storage OFF N/A, queue/storage 구분.
- 향후 변경 조건: P2 observed event는 실제 출처/clock/calibration 보존정책이 달라 별도 aggregate로 추가한다.

## ADR-012 — Warning과 decision reason 통합, 범용 trace graph 제거

- 결정: `run_annotation`에 warning/validation/decision criterion을 반복 row로 저장하고 subject/compared result는 실제 FK를 사용한다. trace node/edge table은 두지 않는다.
- 대안: warning/reason 별도 table; JSON reason array; 범용 trace graph.
- 선택 이유: 공통 code/severity/subject lifecycle은 같고 핵심 lineage는 이미 typed FK chain이다.
- 장점: 3개 이상 table 감소, 검증된 FK, 근거 조회 경로 예측 가능, JSON core trace 회피.
- 단점: 임의 그래프 질의와 다중-hop edge 종류를 자유롭게 추가할 수 없다.
- 영향을 받는 요구사항: decision trace, reason code, 특정 결과 근거 조회.
- 향후 변경 조건: P1 계산이 DAG fan-in/out을 가져 typed FK로 표현 불가능해질 때 versioned trace edge를 추가한다.

## ADR-013 — Comparison metric 비저장

- 결정: terminal 두 run의 compatible `run_metric`을 self-join하고 delta/ratio/comparability reason을 read model로 계산한다.
- 대안: `run_comparison`+`comparison_metric` 영속화; metric row에 baseline/delta column 추가.
- 선택 이유: 비교값은 두 immutable metric의 순수 파생값이며 별도 수정·보존 생명주기가 없다.
- 장점: 중복/invalidated delta 없음, 모든 run 조합 즉시 비교, table 2개 절약.
- 단점: 반복 비교 시 계산 비용과 사용자 저장 비교 identity가 없다.
- 영향을 받는 요구사항: AC-45/55/56, 두 run metric 비교, table 제한.
- 향후 변경 조건: 서명된 검토 package나 사용자 annotation이 붙은 비교가 독립 aggregate가 되면 `run_comparison`만 추가하고 numeric delta는 계속 파생한다.

## ADR-014 — Run root와 stage 분리

- 결정: `scenario_run`은 root 상태/hash, `run_stage`는 반복 단계 상태/row count/error를 소유한다.
- 대안: run에 stage JSON/columns; stage event만 저장.
- 선택 이유: partial/failed 실행에서 성공한 선행 결과와 terminal stage를 독립적으로 보존해야 한다.
- 장점: stage 유일성/순서, 진행 UI, partial forensic query.
- 단점: run 상세에 1 JOIN.
- 영향을 받는 요구사항: AC-44/57, run state/stage 후보, 실패 결과 보존.
- 향후 변경 조건: stage pipeline이 nested DAG가 되면 parent_stage_id를 새 migration으로 검토하되 P0 row 의미는 유지한다.

## ADR-015 — DB와 core engine의 검증 경계

- 결정: DB는 row/relationship/aggregate conservation만 강제하고 궤도 전파·접촉 탐색·rate 적분·충돌 최적화·queue/storage reducer·grade 전파는 core engine/service validator가 수행한다.
- 대안: 계산 trigger/generated column/ORM hook; DB가 아무 교차 검증도 하지 않음.
- 선택 이유: 계산 독립성과 testability를 유지하면서 allocation 초과 같은 저장 무결성은 DB가 막아야 한다.
- 장점: deterministic engine 재사용, clear transaction gate, 잘못된 row-local 상태 방지.
- 단점: publish/finalize validator 누락 시 DB CHECK만으로 모든 semantic 오류를 막지 못한다.
- 영향을 받는 요구사항: 계산 로직 위치, allocation 합, dependency cycle, terminal result.
- 향후 변경 조건: service invariant마다 integration/property test와 transaction API를 필수화한다. 단순 불변식으로 환원되는 규칙만 DB constraint로 승격한다.

## ADR-016 — Archive/tombstone/audit와 권한 분리

- 결정: 주요 head/terminal run은 hard delete 금지, terminal 계산/hash는 불변이며 보존 metadata만 `STANDARD→BASELINE`으로 한 번 승격할 수 있다. 민감 source는 tombstone, 보안 행위는 nullable 실제 FK를 가진 append-only `audit_event`로 기록한다. migration/application role은 배포에서 분리한다.
- 대안: cascade delete; soft-delete boolean만; 문자열 entity_type/id audit; migration과 runtime 단일 role.
- 선택 이유: 공개 저장소, 과거 재현, source redaction과 최소 권한을 동시에 만족해야 한다.
- 장점: 복구 가능성, FK 보존, 검증된 audit subject, credential 비저장.
- 단점: 저장량 증가, GDPR/법적 삭제가 필요한 운영에서는 별도 anonymization/redaction 절차 필요.
- 영향을 받는 요구사항: source tombstone, terminal/baseline 보존, public repo 보안, DB role.
- 향후 변경 조건: 실제 사용자 계정/tenant가 도입되면 IAM/tenant 경계와 RLS를 별도 보안 ADR로 추가한다.

## ADR-017 — P0 numeric/time canonical representation

- 결정: byte/exact integer는 `numeric(...,0)`, coordinate는 scaled `bigint`, 시간은 `timestamptz`와 canonical UTC µs serializer, rate/value는 정수 rational pair로 저장한다.
- 대안: double precision; decimal rate; 표시 MB 저장.
- 선택 이유: 2^53 초과 byte, platform별 float/rounding/hash 차이를 방지한다.
- 장점: exact capacity/allocation/storage 비교, known zero 보존, canonical hash 안정.
- 단점: `numeric` 연산/저장 비용과 application rational helper 필요.
- 영향을 받는 요구사항: AC-04/19/33/41, PB-C14N-JSON-V1, MB/MiB 분리.
- 향후 변경 조건: 성능 측정에서 numeric 병목이 확인되면 범위가 증명된 field만 bigint로 좁히며 canonical semantic value는 유지한다.

## ADR-018 — 최종 readiness 판정

- 결정: 스키마는 `READY_WITH_REQUIRED_DECISIONS`다.
- 대안: `READY_FOR_EXECUTABLE_MODEL`, `SCHEMA_TOO_COMPLEX`, `SCHEMA_INTEGRITY_INSUFFICIENT`.
- 선택 이유: 30-table P0는 executable model을 구현할 만큼 작고 핵심 무결성을 보존하지만 orbit/canonical/CI evidence와 일부 owner decision이 아직 release blocker다.
- 장점: 구현을 불필요하게 막지 않으면서 검증 완료를 과장하지 않는다.
- 단점: application service invariant와 evidence gate 구현 없이는 DDL 단독으로 release할 수 없다.
- 영향을 받는 요구사항: 최종 판정, v1.5 출시 상태, 남은 위험.
- 향후 변경 조건: clean migration, 사례 A~D, G-01~14, AC-41~58과 복구시험이 통과하면 `READY_FOR_EXECUTABLE_MODEL` 이후 release readiness를 별도로 재판정한다.

## ADR-019 — FIXED_RATE와 time reserve는 exact timeline child로 저장

- 결정: `communication_timeline_segment`가 active-data interval 상대 `[start_offset,end_offset)`에 RATE와 TIME_RESERVE를 구분해 저장한다. RATE는 exact rational이고 상수 rate는 `[0,NULL)` 한 row다.
- 대안: communication revision의 단일 rate pair; JSONB segment 배열; pass마다 계산된 rate row 저장.
- 선택 이유: v1.5의 3-bin 60MB oracle, pass 내부 completion과 고율 구간 time-reserve를 재현하려면 반복 구간과 위치가 필요하고, 이는 입력 revision의 사실이지 run 결과가 아니다.
- 장점: 구간별 FK/UNIQUE/CHECK, exact 산술, segment 분할/병합 property 시험 가능.
- 단점: communication 상세에 1 JOIN; coverage/overlap과 provider-kind는 publish validator가 검사해야 한다.
- 영향을 받는 요구사항: AC-04/11/33, FIXED_RATE, exact rational 단일 floor, JSONB 제한.
- 향후 변경 조건: 연속 empirical curve/adaptive MCS는 P1 provider subtype으로 추가하며 기존 fixed segment 의미를 변경하지 않는다.

## ADR-020 — Contact source provenance와 조건부 orbit/elevation 계약

- 상태: `ACCEPTED_FOR_V0.2` (Alembic `0002_contact_source_provenance`)
- 결정: `contact_source_kind` enum(`ORBIT_DERIVED`/`SYNTHETIC_INJECTED`)을 도입하고,
  `scenario_revision.orbit_revision_id`와 `geometric_access.maximum_elevation_udeg/at`의
  필수 여부를 그 값에 따라 조건부로 만든다. `ORBIT_DERIVED`는 v0.1 계약을 그대로 강제하고,
  `SYNTHETIC_INJECTED`는 orbit revision과 elevation을 금지하며
  `synthetic_contact_provider_revision`을 요구한다. discriminator는
  `geometric_access → scenario_station → scenario_revision` composite FK 사슬로 전파해
  불가능한 조합을 DB가 거부한다.
- 대안: 두 컬럼을 단순 nullable로 완화; synthetic 행에 sentinel orbit revision과
  `maximum_elevation_udeg=0`을 삽입; synthetic 실행을 PostgreSQL에서 제외;
  `synthetic_access` 별도 테이블; 서비스 계층에서만 검사.
- 선택 이유: 단순 nullable은 실제 궤도 접촉의 AOS/LOS/최대고도각 보장을 잃는다. sentinel 값은
  23.3이 금지한 "적용되지 않는 값을 known 0으로 채우기"다. 별도 테이블은 ADR-009의
  result root/`result_kind` 계약을 이중화한다. ADR-015에 따르면 이 규칙은 row-local
  불변식이므로 DB constraint로 승격하는 것이 맞다.
- 장점: synthetic 실행을 typed relational 정본으로 저장할 수 있고 `NOT_APPLICABLE`이 명시적
  상태가 된다. 실제 궤도 행의 계약은 약화되지 않는다. 접촉 출처가 1급 컬럼이 되어 합성 실행이
  궤도 실행으로 오인될 수 없다.
- 단점: 3개 테이블에 discriminator 컬럼과 2개 composite unique key가 추가된다. 세 번째
  contact source가 생기면 enum과 CHECK를 확장해야 한다. synthetic 행이 존재하면 downgrade가
  무손실일 수 없다.
- 영향을 받는 요구사항: AC-03A, AC-17, AC-P0-01/20, `PB-GOLDEN-CORE-01` 영속화, 13장의
  "GP_TLE 독립 oracle" release blocker와의 분리.
- 향후 변경 조건: `PB-GOLDEN-ORB-01` evidence가 확보되어 `ORBIT_DERIVED` 경로가 실제로
  실행될 때 재검토한다. 두 label의 의미 자체는 그대로 둔다.
- 상세 근거와 대안 비교: `docs/architecture/ADR-0002-synthetic-contact-provenance.md`
