# 백엔드 개발 시작 프롬프트

아래 내용을 백엔드 개발 담당자 또는 코딩 에이전트에게 그대로 전달한다.

---

당신은 SEMANTIX PassBudget의 수석 백엔드 엔지니어다. 단순한 설계 제안이나 샘플 코드가 아니라, 저장소에서 실행·검증되는 첫 번째 백엔드 vertical slice를 구현하라.

## 1. 작업 위치와 목표

작업 저장소:

```text
C:\Users\0whal\Desktop\다학제간 캡스톤\SEMANTIX-PassBudget
```

이번 작업의 목표는 다음과 같다.

> 확정된 P0 기능·데이터 계약을 코드 구조로 고정하고, 합성 fixture `PB-GOLDEN-CORE-01`의 접촉 → logical capacity → NETWORK_ONLY 결과가 DB 없이 CLI에서 실행되며 같은 application service를 HTTP API에서도 호출하는 첫 vertical slice를 완성한다.

프론트엔드는 작업하지 않는다. 실제 KMU-ET02 값은 하드코딩하지 않는다. C++/CUDA는 사용하지 않는다.

## 2. 먼저 끝까지 읽을 문서

다음 파일을 작업 전에 전문으로 읽고, 서로의 관계를 짧게 요약한 뒤 구현을 시작하라.

1. `docs/specs/P0_FUNCTIONAL_SPEC.md` — 제품 기능과 계산 계약의 1차 구현 기준
2. `docs/database/schema_decisions.md` — 데이터 경계와 설계 결정
3. `docs/database/database_schema_v0.1.md` — 물리 스키마 설명
4. `db/schema_v0_1.sql` — PostgreSQL 16+ 실행 DDL
5. `docs/architecture/ADR-0001-runtime-and-portability.md` — Python/이식성 아키텍처
6. `SECURITY.md`와 `.gitignore` — 공개 저장소 안전 기준
7. `README.md`

부모 프로젝트 폴더에 다음 문서가 있으면 관련 P0 절을 함께 읽어라.

- `../골든시나리오설계도.md` 최신 버전
- `../capstone_total_docs/마일스톤.md`
- `../capstone_total_docs/09_passbudget_phase1_product_plan.md`

권위 순서는 최신 `골든시나리오설계도.md`의 27 → 26 → 25 → 24 → 23장, 그 내용을 공개 구현 계약으로 정리한 `P0_FUNCTIONAL_SPEC.md`, 데이터 문서 순이다. 문서가 충돌하면 임의로 선택하지 말고 충돌 위치와 영향을 기록하되, 충돌하지 않는 범위의 구현은 계속 진행하라. P1/P2 기능을 P0에 선구현하지 않는다.

## 3. 기술 기준

- Python 3.12, CPU-first modular monolith
- FastAPI HTTP adapter
- Pydantic v2 request/response DTO
- SQLAlchemy 2.x + Alembic + PostgreSQL 16+
- pytest + Hypothesis, Ruff, mypy
- 표준 `src/` layout
- domain core는 FastAPI, Pydantic request DTO, SQLAlchemy, DB, 파일시스템, CUDA를 import하지 않아야 한다.
- byte/count는 Python `int`, rate/factor는 `fractions.Fraction` 또는 동등한 exact rational type을 사용한다.
- orbit 계산의 float는 향후 orbit adapter 경계에서만 허용한다.
- CLI/API/test는 동일한 application service를 호출한다.
- 설정은 환경변수로 주입하고 `.env`나 credential을 commit하지 않는다.

권장 구조는 다음과 같다. 이름은 합리적 근거가 있을 때만 조금 조정할 수 있다.

```text
src/semantix_passbudget/
  domain/          # value objects, enums, policies, pure calculation
  application/     # use cases and orchestration
  ports/           # repository, contact/orbit provider, artifact interfaces
  adapters/        # PostgreSQL, synthetic contact, later SGP4
  interfaces/api/  # FastAPI
  interfaces/cli/  # CLI
tests/
  unit/
  property/
  integration/
  fixtures/
```

## 4. 이번에 구현할 범위

### A. 프로젝트 기반

1. `pyproject.toml`, package layout, test/lint/type-check 설정을 만든다.
2. 공개 저장소용 multi-stage `Dockerfile`과 로컬 PostgreSQL용 `compose.yaml`을 만든다. 이미지에 secret을 넣지 않는다.
3. `.env.example`은 가짜 로컬 값만 유지한다.
4. README에 설치, CLI/API 실행, test와 migration 방법을 추가한다.

### B. executable domain contract

다음 type과 validation을 최소 구현한다.

- `AnalysisMode`, `CapacityProvider`, `CalculationStatus`, `DecisionGrade`
- `EvidenceState`, `ValueState`, `PresenceState`와 `ResolvedEvidenceValue[T]`
- UTC microsecond timestamp와 `[start,end)` interval
- exact rate/factor와 integer logical byte
- station/contact/rate segment/candidate/scheduled session
- scenario snapshot의 이번 vertical slice에 필요한 최소 typed model
- 구조화된 reason/warning code

필수 규칙:

- 0, UNKNOWN, omitted, N/A를 구분한다.
- UNKNOWN은 의존 branch만 `BLOCKED/null`로 만든다.
- invalid 조합은 `INVALID/null`이다.
- guard 합이 pass 이상이면 `KNOWN_ZERO/GUARD_EXCEEDS_WINDOW`다.
- fixed rate와 fixed capacity 입력을 섞으면 `INPUT_FACTOR_CONFLICT`다.
- UTC `Z` 이외와 leap-second window를 조용히 변환하지 않는다.

### C. canonicalization과 hash

`PB-C14N-JSON-V1` production 구현을 만들고 test-only reference 구현은 production module을 import하지 않게 분리한다.

- Unicode NFC
- UTC integer microseconds
- integer를 decimal string으로 표현
- rational을 기약 numerator/denominator로 표현
- schema registry에 따른 set-array stable sort와 ordered-array 보존
- null/omitted/N/A 분리
- 명세의 framing을 적용한 SHA-256 input/result/run hash

최소 vector는 key 순서, station/payload 행 순서, 단위 정규화, NFC/NFD, 2^53 초과 byte와 rational permutation을 포함한다.

### D. DB 없는 계산 vertical slice

1. `SyntheticContactProvider` port/adapter를 만든다. 이는 test/demo용이며 orbit 정확성을 주장하지 않는다.
2. `PB-GOLDEN-CORE-01`의 GS-A/B/C 접촉을 literal fixture 파일로 둔다.
3. guard와 interval clipping을 구현한다.
4. `FIXED_RATE` exact integration을 구현한다. 전체 연속 bitstream에서 한 번만 whole byte floor한다.
5. `NETWORK_ONLY`에서 non-overlap 후보의 logical capacity를 집계한다.
6. 이번 slice의 output에도 geometric/modeled/scheduled 단계, candidate와 scheduled unique, status/grade, reason, provenance, hashes를 분리한다.

이번 작업의 필수 골든 결과:

```text
GS-A contacts = 4, 60,000,000 B/contact, total 240,000,000 B
GS-B contacts = 4, 40,000,000 B/contact, total 160,000,000 B
GS-C contacts = 8, 20,000,000 B/contact, total 160,000,000 B
TOTAL contacts = 16
candidate_capacity_sum_bytes = 560,000,000 B
scheduled_unique_capacity_bytes = 560,000,000 B  # 이 기본 fixture는 비중첩
orbit_dependency = NOT_APPLICABLE
decision_grade = CONCEPT_ONLY
```

GS-A 첫 contact는 true 00:10~00:20, modeled data interval 00:11~00:19, capacity 60,000,000B여야 한다.

### E. 첫 application/API/CLI 연결

다음 인터페이스를 만든다.

- `GET /health`
- `POST /api/v1/runs` — 이번 단계에서는 fixture 또는 typed snapshot 입력으로 새 run 생성
- `GET /api/v1/runs/{run_id}`
- `GET /api/v1/runs/{run_id}/results`
- `passbudget validate <fixture>`
- `passbudget run <fixture> --output <result.json>`
- `passbudget verify-golden`

초기에는 in-memory repository를 사용해 end-to-end를 완성할 수 있다. 그러나 port를 통해 주입하고, HTTP handler나 CLI 안에 계산을 복제하지 않는다. run ID 재실행으로 결과를 덮어쓰지 않는다.

### F. PostgreSQL 기반 준비

1. `db/schema_v0_1.sql`이 빈 PostgreSQL 16 DB에 적용되는 smoke test를 만든다.
2. Alembic baseline 전략을 명시하고 적용한다.
3. 이번 vertical slice에 필요한 repository adapter를 구현하거나, 아직 연결하지 않는 부분은 구체적인 다음 작업으로 남긴다.
4. 30개 table의 ORM class를 기계적으로 전부 만드는 데 시간을 쓰기보다 typed domain과 골든 계산을 먼저 통과시킨다. 단, 기존 DDL을 몰래 축소하거나 변경하지 않는다.

## 5. 이번 작업에서 하지 않을 것

- 실제 TLE/SGP4와 virtual circular orbit provider 구현
- `QUEUE_AWARE` allocation, bundle/dependency, storage ledger 전체 구현
- overlap horizon optimizer 전체 구현
- 실제 ACK/지상국 수신 API
- 물리 link budget, wire/FEC overhead estimator
- 사용자 인증, 결제, 운영 배포
- 프론트엔드

단, 이후 확장 포트와 domain 경계는 명세에 맞게 유지한다. 빈 P1/P2 endpoint나 가짜 결과는 만들지 않는다.

## 6. 필수 테스트

최소 다음을 자동화한다.

1. A/B/C contact 수와 첫/마지막 interval
2. A1 exact rate 적분 60,000,000B
3. rate segment split/merge invariance
4. guard `<`, `=`, `>` pass duration 경계
5. endpoint-touch non-conflict와 zero-duration tangent 제외
6. UNKNOWN rate일 때 contact만 계산되고 capacity만 `BLOCKED/null`
7. valid PROXY가 `CONCEPT_ONLY`로 전파됨
8. fixed provider input conflict가 `INVALID`
9. row/key/set permutation에도 semantic result/hash 동일
10. NFC/NFD, integer >2^53, rational canonical vectors
11. API와 CLI가 core와 동일한 result content hash를 반환
12. API 오류에 stack, secret, DB URL, host absolute path가 없음
13. PostgreSQL 16 clean-schema smoke test

테스트를 통과시키기 위해 oracle을 production 함수로 다시 계산하지 않는다. fixture의 expected literal과 독립 reference path를 사용한다.

## 7. 품질·안전 규칙

- 기존 문서와 사용자 변경을 보존한다.
- hardcoded 실제 KMU-ET02 사양이나 사설 서버 정보를 넣지 않는다.
- synthetic fixture를 실제 위성/수신 성능으로 표현하지 않는다.
- binary float를 capacity, allocation 또는 semantic hash의 권위값으로 쓰지 않는다.
- 예외를 잡아 0B나 성공 상태로 바꾸지 않는다.
- 로컬 절대 경로를 result/hash/report에 포함하지 않는다.
- 명시적 요청 없이 commit 또는 push하지 않는다.
- dependency 추가는 최소화하고 선택 이유를 남긴다.

## 8. 작업 방식과 완료 보고

먼저 저장소 상태와 문서 계약을 확인한 뒤 바로 구현하라. 계획만 제시하고 멈추지 않는다. 작은 단계마다 관련 test를 실행하고, 마지막에 다음을 검증한다.

```text
lint
type check
unit/property/integration tests
PB-GOLDEN-CORE-01 CLI verification
API smoke test
PostgreSQL migration smoke test
public-repository secret scan
```

완료 보고에는 다음만 명확히 적는다.

1. 구현한 기능과 변경 파일
2. 실행한 검증 명령과 결과
3. 골든 결과의 실제 값
4. 남아 있는 명세 충돌·release blocker
5. 다음 vertical slice 제안: overlap scheduler → QUEUE_AWARE → storage → independent orbit fixtures

현재 release 상태는 `P0_RELEASE_BLOCKED_NEEDS_EVIDENCE`다. 첫 vertical slice가 통과해도 실제 궤도 독립 fixture와 canonical 교차 구현 증거가 없으면 출시 가능하다고 선언하지 않는다.

---

---

> **경로 안내 (2026-09-03 추가)** — 이 문서 본문의 `db/schema_v0_1.sql`은
> `db/postgresql/schema_v0_1.sql`로 이동했다. SQLite 전용 DDL은 `db/sqlite/schema_v1.sql`에
> 있다. 본문은 수정하지 않았으며, 이동 사유와 persistence tier 결정은
> `docs/architecture/ADR-0003-persistence-tiers.md`와
> `docs/specs/SPEC_CONFLICT_REGISTER.md`의 `CONFLICT-PERSIST-01`을 참조한다.
