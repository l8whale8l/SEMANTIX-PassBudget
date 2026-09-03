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

## CONFLICT-QUEUE-02 — 전역 objective와 조밀한 충돌의 계산 가능성

| 문서 | 주장 |
|---|---|
| `골든시나리오설계도.md` §24, `P0_FUNCTIONAL_SPEC.md` §6.5 | `QUEUE_AWARE`는 "남은 분석기간의 미래 세션을 포함하는 deterministic rollout"으로 lexicographic objective를 적용한다 — 즉 목적함수가 전역이다 |
| 계산 복잡도 | 충돌 component 간 결합은 payload queue 상태를 통해 일어나므로 분리되지 않고, 전역 최적 선택은 NP-hard다 |

- 판정: `RESOLVED_BY_PM_DECISION (b)` — 2026-09-03
- 근거: 두 요구를 동시에 만족하는 방법은 없다. 조합 폭발 앞에서 선택지는 (a) 명세의 전역
  objective를 유지하고 계산 불가능한 입력을 거부하거나, (b) 답을 내되 component-local
  휴리스틱으로 근사하는 것뿐이다. (b)는 결과를 최적이라고 부르면서 아닌 값을 반환하므로
  채택하지 않았다. `QUEUE_AWARE_LEXICOGRAPHIC_HORIZON_V2`가 사실상 (b)였고,
  `tests/unit/test_horizon.py`의 2-component 반례에서 오답을 냈다.
- 구현: `domain/horizon.py`의 V3가 분기 component 대안의 모든 조합을 전체 분석기간 rollout으로
  채점한다. 상한은 `MAXIMAL_SET_BUDGET`(component 내부)과
  `GLOBAL_COMBINATION_BUDGET`(전역, 4096 조합)이며, 초과하면 각각
  `QUEUE_HORIZON_SEARCH_BUDGET_EXCEEDED`와 `QUEUE_HORIZON_GLOBAL_SEARCH_BUDGET_EXCEEDED`로
  거부한다. byte-only나 greedy로 조용히 내려가지 않는다.
- 잔여 위험: 기준 규모에서 exact가 거부하는 입력이 있다. 20 station × 7일에서 접촉의 절반이
  짝을 이뤄 겹치면 분기 component가 350개(2^350 조합)이므로 exact는 거부한다. PM 결정 `(b)`
  이후 그 입력에는 답이 있다 — `BOUNDED_APPROXIMATE`로 1.5초 안에 계산되며, 최적이라고
  주장하지 않는다. 남은 위험은 사용자가 등급을 읽지 않고 두 mode의 숫자를 섞어 비교하는 것이며,
  `OPTIMIZATION_GRADE_MISMATCH` warning이 그 지점을 표시한다.
- **PM 결정 (2026-09-03): `(b)`.** 명시적으로 표시된 근사 mode를 추가하되, 결과를 최적이라
  부르지 않는다. `execution_strategy`를 시나리오의 semantic input으로 두고 `EXACT_GLOBAL`을
  기본값으로 한다. exact가 상한을 초과해도 approximate로 **자동 전환하지 않는다** — 사용자가
  명시적으로 선택해야 한다. 계약은 `P0_FUNCTIONAL_SPEC.md` §6.5.1에 기록했다.
- 결정 이후 구현: `domain/horizon.py`의 `_select_exact_global`과
  `_select_bounded_approximate`. approximate는 feasible과 deterministic만 보증하고
  `optimization_status=APPROXIMATE`, `globally_optimal=false`,
  `algorithm_revision=QUEUE_AWARE_BOUNDED_POLICY_FAMILY_V2`(3개의 다항시간 interval scheduling
  정책 중 최선; component 분해와 maximal set 열거를 하지 않으므로 exact의 세 상한이 적용되지
  않는다),
  `NOT_GLOBALLY_OPTIMAL` warning을 결과에 싣는다. exact는 조합 수와 작업량 두 상한을 갖고
  각각 `QUEUE_HORIZON_GLOBAL_SEARCH_BUDGET_EXCEEDED`,
  `QUEUE_HORIZON_EXACT_WORK_BUDGET_EXCEEDED`로 거부한다.
- 잔여 결정: `optimality_gap`은 현재 항상 `null`이다. objective 전체에 대한 계산 가능한
  bound를 P0에서 요구할지, 아니면 등급 표기만으로 충분한지는 열려 있다.

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

## CONFLICT-ORB-01 — Orekit의 JVM 요구 vs ADR-0001 이식성 계약

| 문서 | 주장 |
|---|---|
| 세션 지시 | 제품 엔진 후보는 Orekit, 독립 oracle은 NASA GMAT |
| `ADR-0001` "Portability contract" | Python·CPU-first, host 레이아웃 의존 금지 |
| `README.md` "Install and first run" | "Python 3.12 is required. Nothing else is." |

- 사실 확인(2026-09-03, 패키지 메타데이터): `orekit_jpype` 13.1.7.1은 Apache-2.0(MIT와 호환)
  이지만 JVM을 요구한다. JVM 조달 경로는 (A) 시스템 JDK 요구 — README 계약 위반이자 engine
  manifest 재현성 붕괴(호스트 JDK가 통제되지 않음), (B) `jdk4py` 번들 — 플랫폼당 ~30 MiB이며
  PyPI 분류가 **GPL-2.0**(OpenJDK는 GPLv2+Classpath Exception이나 분류자에는 기록되지 않음),
  (C) Java를 제품에서 배제. 어느 쪽이든 `orekit-data` 번들도 별도로 vendoring해야 한다.
- 처리: 임의로 강행하지 않고 `Q-ORB-RUNTIME-01`로 PM에 상신했다.
- 결정(2026-09-03, PM): **옵션 C**. 제품 엔진은 순수 Python **python-sgp4 2.27(MIT)**,
  Orekit은 제품에서 제외하고 offline oracle로만 남긴다. 근거와 대안 비교는 `ADR-0004`.
- 결과: ADR-0001과 README 계약이 그대로 유지된다. wheel clean-install로 검증했다 — 기본
  설치는 `sgp4`를 끌어오지 않으며(`orbit` extra), golden hash는 저장소 실행과 byte-identical.

## CONFLICT-ORB-02 — 검증 계약 §3(TEME 전제) vs §7.2(EME2000 상태)

| 문서 | 주장 |
|---|---|
| `ORBIT_VERIFICATION_CONTRACT.md` §3 | 지구고정계는 TEME에서 항성시 회전 **하나로** 도달한다 |
| 동 §7.2 | `EVD-ORB-02`의 초기상태는 **EME2000**에 정의된다 |

- 충돌 내용: §3의 프레임 경로는 SGP4/TEME 전용으로 작성되었으나, `VIRTUAL_CIRCULAR`는
  EME2000 상태를 쓰므로 세차·장동을 포함한 IAU-76/FK5 전체 축약이 필요하다. §3만 따르면
  26년치 세차(약 534 arcsec)를 누락한다.
- 조용히 한쪽을 고르지 않고 두 경로를 모두 구현했다: `geometry.teme_to_ecef`(GMST 단독,
  `EVD-ORB-01`)와 `twobody.eme2000_to_ecef`(전체 축약, `EVD-ORB-02`). 각 fixture가 어느 경로를
  쓰는지는 `inputs.json`에 명시된다.
- 이 충돌을 처음 드러낸 것은 독립 oracle이다. 초기 구현이 세차 중간 회전을 X축으로 잘못
  적용해 지구고정계 위치가 18.29 km 어긋났고 AOS 오차가 22.3 s에 달했다. 축을 Y로 바로잡자
  0.1 m 이내로 수렴했다. 자기일관성 검사로는 절대 드러나지 않았을 결함이다.
- 필요한 결정: 없음. §3을 fixture별 프레임 경로로 읽도록 계약에 반영했다.

## CONFLICT-ORB-03 — GMAT EOP 테이블 vs 계약 §2(UT1−UTC·극운동 0 고정)

| 문서 | 주장 |
|---|---|
| `ORBIT_VERIFICATION_CONTRACT.md` §2 | 두 도구 모두 UT1−UTC = 0, 극운동 = 0 |
| GMAT 기본 배포 | IERS EOP 실측 테이블을 읽는다(2026-09-03 행: UT1−UTC = 0.0888341 s) |

- 충돌 내용: 제품 엔진은 구조상 0이지만 GMAT은 실측 EOP를 적용하므로, 그대로 비교하면 두
  구현이 아니라 서로 다른 날짜의 EOP 테이블을 비교하게 된다.
- 처리: GMAT의 EOP 파일을 컬럼 폭을 유지한 채 x·y·UT1−UTC·LOD·dPsi·dEps만 0으로 채운 사본으로
  교체했다. 생성기는 `scripts/orbit/make_zero_eop.py`이며 원본과 교체본의 SHA-256을 모두
  기록했다. 이는 숨은 조정이 아니라 계약이 요구한 설정이며 재현 절차에 포함된다.
- 대가: 실제 지구 자전 대비 최대 ±0.9 s의 회전 변위. 따라서 이 fixture는 **두 구현의 일치**를
  증명할 뿐 절대 궤도 정확도를 보증하지 않으며, 그 한계를 모든 산출물에 명시했다.

## 미해결 evidence (충돌이 아니라 부재)

| ID | 필요한 산출물 | 소유자 | 영향 |
|---|---|---|---|
| ~~`EVD-ORB-01`~~ | **확보(2026-09-03)** — frozen TLE·provenance·expected table·delta table 모두 존재. 최악 AOS 오차 0.017 s (ceiling 1.000 s) | Orbit/Backend + V&V | 해소 |
| ~~`EVD-ORB-02`~~ | **확보(2026-09-03)** — `Q-DATA-03`이 `TWO_BODY_V1`로 결정되고 delta table 생성. 최악 AOS 오차 0.014 s | Orbit/Backend + PM | 해소 |
| `Q-ORB-LICENSE-01` | CelesTrak 재배포 조건 확인(공개 저장소 게시 전). 미해결이므로 `EVD-ORB-01`(입력·provenance·raw TLE·GMAT oracle 산출물)은 public git에서 제외(`.gitignore`)하고 로컬 전용으로 유지한다. cross-tool 공개 gate는 합성 `EVD-ORB-02`가 담당하며, `EVD-ORB-01` case는 CI에서 명시적 사유와 함께 skip(포함하지 않으면 pass로 계산되지 않음) | PM / legal | `EVD-ORB-01` 공개 |
| `EVD-PRODUCT-01` | 실제 KMU MANDATORY/severity/value/bundle 정책 승인 | Mission Product Owner | 실제 preset 전환 |
| `EVD-OBDH-01` | 실제 completion/reclaim/chunk 근거 | OBDH | storage PROXY 제거 |
| `EVD-RF-01` | `APPLICATION_GOODPUT` measurement point 정의 | Ground/RF | 현재 fixture는 합성 literal `SYNTHETIC_SPACECRAFT_APPLICATION_EGRESS`를 PROXY로 사용 |

자세한 궤도 gate 상태는 `docs/specs/ORBIT_RELEASE_GATE.md`를 참조한다.
