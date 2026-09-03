# P0 명세 충돌 등록부

> 상태: 구현 기준선 v0.2  
> 권위 순서: `골든시나리오설계도.md` 27장 → 26 → 25 → 24 → 23장 →
> `docs/specs/P0_FUNCTIONAL_SPEC.md` → `docs/database/*` → `docs/prompts/BACKEND_KICKOFF_PROMPT.md`

문서가 충돌할 때 임의로 한쪽을 선택하고 숨기지 않는다. 각 충돌은 여기에 등록하고, 구현이
어느 쪽을 따랐는지와 그 근거를 남기며, 결정 주체가 필요한 항목은 `OPEN`으로 유지한다.

## CONFLICT-FIX-01 — `PB-GOLDEN-CORE-01`의 `analysis_mode`

| 문서 | 주장 |
|---|---|
| `골든시나리오설계도.md` §12 공통 조건 | `analysis_mode = QUEUE_AWARE` |
| `P0_FUNCTIONAL_SPEC.md` §13.1 | `analysis_mode = QUEUE_AWARE` |
| `docs/prompts/BACKEND_KICKOFF_PROMPT.md` §4.D | `NETWORK_ONLY` 결과(16 contacts, 560,000,000 B, `scheduled_unique = candidate`)를 이 fixture의 필수 골든 결과로 지정 |

- 판정: `RESOLVED_BY_SPLIT`
- 근거: 두 상위 문서는 일치하고 kickoff prompt만 다르다. kickoff prompt는 권위 순서에서 가장
  낮지만, 그 안의 수치 oracle(16 contacts / 560 MB / 비중첩)은 §12의 접촉 oracle과 완전히
  일치한다. 즉 충돌은 값이 아니라 **하나의 fixture id에 두 mode를 요구한 것**이다.
- 구현: `골든시나리오설계도.md` §19.4가 이미 승인한 fixture 분리 원칙을 적용해
  `PB-GOLDEN-CORE-01`은 kickoff가 요구한 `NETWORK_ONLY` 계약을 유지하고, §12/§13.1의
  `QUEUE_AWARE` queue oracle은 동일한 접촉·용량 입력을 쓰는 `PB-GOLDEN-QUEUE-01`이 담당한다.
  두 fixture의 station/contact/capacity 입력은 동일하므로 어느 문서의 수치 oracle도 버려지지
  않는다. `passbudget verify-golden`이 둘 다 검사한다.
- 잔여 위험: 없음. 단, 문서를 갱신할 때 §12의 fixture id를 `PB-GOLDEN-QUEUE-01`로 바꾸거나
  kickoff의 fixture id를 바꾸면 이 등록부 항목을 함께 정리해야 한다.

## CONFLICT-C14N-01 — canonical timestamp 표현

| 문서 | 주장 |
|---|---|
| `골든시나리오설계도.md` §26.10 (v1.4 ADR `PB-C14N-JSON-V1`) | `time`: `YYYY-MM-DDTHH:MM:SS.ffffffZ`, UTC 고정 6자리 |
| `P0_FUNCTIONAL_SPEC.md` §10 | "timestamp는 UTC integer microseconds로 표현한다" |

- 판정: `RESOLVED_BY_AUTHORITY`
- 근거: 26장은 canonicalization ADR의 권위 문서이고 P0 기능 명세보다 상위다. 두 표현은
  bijective하지만 canonical **bytes**가 달라지므로 동시에 채택할 수 없다.
- 구현: 26.10의 고정 6자리 UTC `Z` 문자열을 사용한다
  (`domain/time.py::UtcInstant.isoformat`). 내부 계산과 비교는 계속 integer microseconds이며,
  직렬화 경계에서만 문자열이 된다. `P0_FUNCTIONAL_SPEC.md` §10은 26.10과 일치하도록 갱신이
  필요하다.
- 필요한 결정: 문서 소유자가 §10 문구를 26.10에 맞춰 정정. 구현 변경은 필요 없다.

## CONFLICT-DB-01 — synthetic contact의 orbit revision과 maximum elevation

| 문서 | 주장 |
|---|---|
| `db/postgresql/schema_v0_1.sql` | `scenario_revision.orbit_revision_id NOT NULL`; `geometric_access.maximum_elevation_udeg/at NOT NULL` |
| `골든시나리오설계도.md` §12·§13 AC-03A, `P0_FUNCTIONAL_SPEC.md` §13 | synthetic fixture는 `orbit_dependency = NOT_APPLICABLE`이며 궤도 정확성을 주장하지 않는다 |
| `골든시나리오설계도.md` §23.3 | 적용되지 않는 값은 UNKNOWN이 아니라 `NOT_APPLICABLE`로 표현한다 |

- 판정: `RESOLVED_BY_SCHEMA_DECISION`
- 근거: 두 요구는 orbit-derived contact에 대해서는 모두 옳고, synthetic injected contact에
  대해서만 충돌한다. 조건부 계약으로 분리하면 어느 쪽도 약화되지 않는다.
- 구현: `docs/architecture/ADR-0002-synthetic-contact-provenance.md`,
  `db/postgresql/schema_v0_2_contact_source.sql`, Alembic `0002_contact_source_provenance`.
  `contact_source_kind` discriminator를 도입해 `ORBIT_DERIVED`는 v0.1 계약을 그대로 강제하고
  `SYNTHETIC_INJECTED`는 orbit revision과 elevation을 **금지**한다. 가짜 값은 넣지 않는다.
- 잔여 위험: 세 번째 contact source(예: 관측 pass 가져오기)가 생기면 enum과 CHECK를 확장해야
  한다.

## CONFLICT-CMP-01 — evidence 등급 불일치 경고 코드 이름

| 문서 | 주장 |
|---|---|
| `골든시나리오설계도.md` §26.11 | `COMPARABLE_WITH_EVIDENCE_DIFFERENCE` |
| `P0_FUNCTIONAL_SPEC.md` §8.5 | `EVIDENCE_GRADE_MISMATCH` |

- 판정: `RESOLVED_BY_EMITTING_BOTH`
- 근거: 의미가 동일한 같은 사건의 이름만 다르다. 상위 문서 이름을 택하면 하위 문서를 참고해
  작성될 소비자가 깨지고, 그 반대도 마찬가지다.
- 구현: `application/comparison.py`가 두 코드를 모두 warning으로 낸다
  (`ComparisonReasonCode`). 이름이 통일되면 하나를 제거한다.
- 필요한 결정: 문서 소유자가 정식 코드명을 고정.

## CONFLICT-STORE-01 — `release_trigger`의 허용 값 집합

| 문서 | 주장 |
|---|---|
| `골든시나리오설계도.md` §24.8 | `TX_END/RECEIVED/VERIFIED/ACKED/NEVER` |
| `db/postgresql/schema_v0_1.sql` `release_trigger` enum | `NEVER`, `TX_END`만 |
| `골든시나리오설계도.md` §13 AC-25B | `release=ACKED`, `event_origin=TEST_SYNTHETIC`를 P0 수용 기준으로 요구 |

- 판정: `OPEN — 구현은 domain에서만 지원`
- 근거: AC-25B는 P0 수용 기준이므로 `ACKED`를 계산할 수 있어야 한다. 그러나 accepted DDL의
  enum에는 `ACKED`가 없고, DDL을 넓히는 것은 실제 ACK 수집(P2)을 P0 스키마에 앞당겨 여는
  것으로 오해될 수 있다.
- 구현: domain/ledger는 `ReleaseTrigger.ACKED`를 `TEST_SYNTHETIC` 이벤트에 한해 지원하고
  (`PB-GOLDEN-ACK-01`), 결과에 `SYNTHETIC_TEST_DELIVERY_EVENTS_ONLY` 경고를 붙인다.
  `scenario_revision.release_trigger` 컬럼은 accepted enum을 그대로 쓰므로 `ACKED` 시나리오는
  현재 PostgreSQL에 저장할 수 없다. `PB-GOLDEN-ACK-01`은 in-memory 실행과 golden 검증에서만
  사용한다.
- 필요한 결정: Data Architect가 (a) `release_trigger` enum에 `ACKED`를 추가하되 P0 사용자
  API에서는 test-only로 잠글지, (b) AC-25B를 P0 domain-only 수용 기준으로 명시할지 결정.
  결정 전까지 `PB-GOLDEN-ACK-01`의 PostgreSQL 영속화는 `BLOCKED`다.

## CONFLICT-QUEUE-01 — `DEADLINE_SEVERITY` comparator 안의 severity 위치

| 문서 | 주장 |
|---|---|
| `골든시나리오설계도.md` §24.6 | `service_class → deadline_at ASC → severity_rank DESC → mission_priority DESC → queue_sequence ASC → ID` |
| 기존 구현 (v0.1) | severity를 `deadline_at`보다 먼저 오름차순 비교 |

- 판정: `RESOLVED_BY_AUTHORITY`
- 근거: §24.6이 유일한 comparator 정의다. 기존 구현은 명세와 어긋났다.
- 구현: `domain/queue.py::queue_order_key`가 §24.6 순서를 따른다. golden queue oracle은 모든
  severity가 0이라 결과가 바뀌지 않으며, `passbudget verify-golden`이 이를 확인한다.

## CONFLICT-PERSIST-01 — P0의 권위 persistence

| 문서 | 주장 |
|---|---|
| `docs/architecture/ADR-0001-runtime-and-portability.md` "Persistence contract" | "PostgreSQL 16+ is the P0 authority... SQLite may be used only for isolated experiments and is not a supported substitute for authoritative P0 persistence." |
| `P0_FUNCTIONAL_SPEC.md` §15.3, §16-2 | PostgreSQL 16+를 이식성 요구와 Definition of Done에 포함 |
| PM 결정 (2026-09-03) | PostgreSQL은 폐기하지 않되 필수 기반이 아닌 **선택 가능한 서버용 adapter**. 기본 실행은 DB 없는 계산 CLI이고 로컬 영속 기본값은 SQLite |

- 판정: `SUPERSEDED_BY_NEWER_DECISION`
- 근거: 두 문서 모두 이전 결정이며, PM 결정이 더 최신이다. 문서를 몰래 고쳐 쓰지 않고
  `docs/architecture/ADR-0003-persistence-tiers.md`를 새 결정으로 추가해 무엇이 왜 바뀌었는지
  기록했다. ADR-0001의 나머지 조항(Python CPU-first, modular monolith, 수치 계약)은 그대로다.
- 구현: `application/composition.py`의 3-tier 선택 정책, `adapters/sqlite/`,
  `db/sqlite/schema_v1.sql`. PostgreSQL adapter·migration·통합 테스트는 삭제하지 않았고 계속
  동작한다. 기본 설치와 기본 테스트는 PostgreSQL과 Docker 없이 통과한다.
- 필요한 결정: 문서 소유자가 `P0_FUNCTIONAL_SPEC.md` §15.3과 §16-2의 문구를 tier 구조에 맞게
  갱신할지, ADR-0003 참조로 충분하다고 볼지 결정.

## CONFLICT-STORE-02 — rendered result document의 저장 위치

| 문서 | 주장 |
|---|---|
| `P0_FUNCTIONAL_SPEC.md` §11.3 | `GET /api/v1/runs/{run_id}/results`와 `/report`가 typed 결과와 보고서를 반환해야 한다 |
| `db/postgresql/schema_v0_1.sql` | run 결과는 typed subtype row로만 저장되며 rendered result document를 담을 table이 없다 |
| ADR-008 | `input_snapshot.canonical_payload`는 typed 정본을 대체하지 않는 versioned immutable artifact로 허용된다 |

- 판정: `OPEN — SQLite tier에서만 해결`
- 근거: 입력 쪽에는 canonical artifact 자리가 있으나 결과 쪽에는 없다. 재시작 후
  `/results`를 제공하려면 결과 문서를 보관하거나 typed row에서 문서를 재구성해야 하는데,
  후자는 hash 재현성을 위태롭게 한다.
- 구현: SQLite schema v1에 `run_result_document`(canonical bytes + `content_sha256`)를 두고
  읽을 때 `scenario_run.result_content_hash`와 대조한다. typed row는 그대로 관계형 정본이다.
  accepted PostgreSQL 스키마에는 임의로 table을 추가하지 않았으므로, PostgreSQL tier에서
  재시작 후 조회하면 빈 객체 대신 `501 RESULT_DOCUMENT_NOT_PERSISTED`를 명시적으로 반환한다.
- 필요한 결정: Data Architect가 PostgreSQL 스키마에 결과 문서 table을 추가할지, 아니면
  PostgreSQL tier에서 `/results`를 재계산 기반으로 제공할지 결정.

## 미해결 evidence (충돌이 아니라 부재)

| ID | 필요한 산출물 | 소유자 | 영향 |
|---|---|---|---|
| `EVD-ORB-01` | frozen 공개 TLE, source URL, retrieval timestamp, license, SHA-256, WGS-84 station literal, mask, propagator/constants/time/frame/event-solver revision, 독립 도구 이름·버전, static AOS/LOS/max-elevation expected table, tolerance와 cross-tool delta | Orbit/Backend + V&V | `PB-GOLDEN-ORB-01`, P0 release |
| `EVD-ORB-02` | `VIRTUAL_CIRCULAR` propagator/constants 결정(`Q-DATA-03`)과 독립 expected table | Orbit/Backend + PM | 동일 |
| `EVD-PRODUCT-01` | 실제 KMU MANDATORY/severity/value/bundle 정책 승인 | Mission Product Owner | 실제 preset 전환 |
| `EVD-OBDH-01` | 실제 completion/reclaim/chunk 근거 | OBDH | storage PROXY 제거 |
| `EVD-RF-01` | `APPLICATION_GOODPUT` measurement point 정의 | Ground/RF | 현재 fixture는 합성 literal `SYNTHETIC_SPACECRAFT_APPLICATION_EGRESS`를 PROXY로 사용 |

자세한 궤도 gate 상태는 `docs/specs/ORBIT_RELEASE_GATE.md`를 참조한다.
