# P0 백엔드 Definition of Done 상태

> 기준: `docs/specs/P0_FUNCTIONAL_SPEC.md` §16의 10개 항목
> 갱신: 2026-09-04, ORBIT_DERIVED 제품 통합 및 required CI 확인 이후

`docs/specs/P0_ACCEPTANCE_MATRIX.md`는 §16의 4번 항목(25개 수용 기준) 하나만 다룬다. 이 문서는
나머지 아홉 개를 포함한 열 개 전부의 상태를 기록한다.

## 검증 상태 — `P0_CORE_ACCEPTED` (기준선 `d467468`)

`QUEUE_AWARE_LEXICOGRAPHIC_HORIZON_V3`, exact/approximate 전략, 입력 상한, HTTP 수신 제한,
fixture 경로 차단 및 `ORBIT_DERIVED` 통합은 `d467468`의 required `backend` CI에서 검증됐다.
[실행 근거](https://github.com/l8whale8l/SEMANTIX-PassBudget/actions/runs/33773033361).
이 상태는 lean P0 핵심 사용 흐름의 승인이지 모든 선택 배포 계층의 검증 완료나 merge 승인이 아니다.

| 항목 | 상태 |
|---|---|
| ruff / mypy / pytest / verify-golden / secret_scan / alembic (로컬) | `LOCAL PASS` |
| `backend` workflow (`verify`, `clean-install`, `docker`, `audit`) | `PASS` — `d467468`, 4/4 job |
| `postgresql` workflow | `NOT RUN` — 이번 branch에서는 선택 workflow 미실행, 현재 PostgreSQL 검증으로 계산하지 않음 |

**아래 표의 근거는 명시된 commit에 한정된다.** 후속 변경은 해당 commit의 CI green을 다시
확인해야 한다. 미실행 PostgreSQL 운영 절차와 H100 검증은 lean P0의 차단 조건이 아니다.

상태 표기는 수용 기준 표와 같다.

- `MET` — 실행된 근거가 있다.
- `PARTIAL` — 일부만 검증됐다. 무엇이 빠졌는지 적는다.
- `BLOCKED` — 외부 evidence나 결정이 없어 완료할 수 없다.

**skip은 통과가 아니다.** 실행되지 않은 검사는 어떤 경우에도 `MET`으로 적지 않는다.

| # | 항목 | 상태 | 근거 |
|---|---|---|---|
| 1 | framework 독립 domain core와 CLI/API adapter가 같은 application service를 호출한다 | `MET` | `tests/unit/test_architecture.py`, `tests/unit/test_boundaries.py`가 domain의 FastAPI·SQLAlchemy·Pydantic·env·system clock·DB import를 금지하고, composition root 외의 env 접근을 금지한다. CLI와 API는 둘 다 `RunScenarioService`를 호출한다 |
| 2 | schema migration이 빈 PostgreSQL 16 DB에 적용되고 rollback/restore 절차가 검증된다 | `PARTIAL` | upgrade·delta·downgrade는 `tests/integration/test_postgres_migration.py::test_postgresql_16_clean_upgrade_and_downgrade`가 실제 PostgreSQL 16에서 검증했다(`postgresql` workflow, `b4056c1`). **빠진 것: 백업/복원 절차.** dump·restore 절차가 문서화되지도 실행되지도 않았다 |
| 3 | `PB-GOLDEN-CORE-01`이 DB 없이 CLI에서, DB를 사용한 API에서 동일 의미 결과를 낸다 | `MET` | `tests/integration/test_vertical_slice.py::test_api_and_cli_use_same_result_hash`, `tests/integration/test_repository_equivalence.py::test_every_available_tier_agrees` |
| 4 | 25개 필수 수용 기준과 property test가 CI에서 통과한다 | `MET` | `d467468`의 `verify` job PASS. 수용 기준은 `docs/specs/P0_ACCEPTANCE_MATRIX.md`, property test는 `tests/property/test_horizon_properties.py`, `tests/property/test_rate_properties.py`. horizon property test의 최적성 보장은 작은 인스턴스(후보 6개 이하)에 한정되며, 기준 규모 성능은 `tests/unit/test_scalability.py`로 별도 검증한다. |
| 5 | frozen TLE와 virtual circular 독립 orbit fixture가 통과한다 | `PARTIAL` | lean P0 evidence gate는 PASS. `EVD-ORB-02` two-body 공개 교차검증과 `PB-GOLDEN-ORB-01` API·CLI 흐름은 `d467468` CI에서 PASS. SGP4 `EVD-ORB-01`은 로컬 교차검증 PASS이나 CelesTrak 재배포 조건 미해결로 공개 재현 검증은 보류, public CI에서 11건 skip. 이 제한은 P0 핵심 흐름의 차단 조건이 아니며 SGP4 공개 검증 완료로 주장하지 않는다. |
| 6 | 독립 canonical reference implementation과 production hash가 vectors에서 일치한다 | `MET` | `tests/reference_c14n.py`가 production 코드를 재사용하지 않는 별도 구현이고, `tests/unit/test_canonical.py`가 두 구현의 digest를 vector마다 대조한다 |
| 7 | terminal run의 snapshot/result/hash가 persistence round trip 후 바뀌지 않는다 | `MET` | 세 tier 모두: `test_repository_equivalence.py`(memory·SQLite 상시, PostgreSQL은 URL이 있을 때), `test_postgres_persistence.py`. 저장 타입과 행 삽입 순서가 hash를 바꾸지 않음을 `test_input_order_permutation_reaches_the_same_stored_rows`가 확인한다 |
| 8 | public repository secret scan과 dependency vulnerability 검사가 통과한다 | `MET` | secret scan은 `scripts/secret_scan.py`(`verify` job). dependency 검사는 `backend` workflow의 `audit` job(`pip-audit`)이며 `edcad89`에서 통과했다. 도입 시점에 실제 취약점 하나(`pytest` `PYSEC-2026-1845`)를 검출했고, `pytest>=9.0.3`으로 올려 해소한 뒤 `No known vulnerabilities found`가 됐다 |
| 9 | Docker image를 일반 CPU host와 H100 서버에서 CUDA 없이 실행할 수 있다 | `PARTIAL` | 일반 CPU host(linux/amd64)는 `backend` workflow의 `docker` job이 `edcad89`에서 실행해 검증했다: 빌드, 이미지 안의 `verify-golden`·`where`, API로 run 계산, **컨테이너 재시작 후 같은 run 재조회**. **빠진 것: H100 host 실행.** 해당 하드웨어에 접근할 수 없어 실행하지 못했다. 이미지에 CUDA·GPU 의존성이 없다는 것은 근거가 아니라 논거이므로 `MET`으로 적지 않는다. 소유자: 인프라 접근 권한을 가진 쪽 |
| 10 | README에 local 실행, test, migration, fixture 실행과 결과 해석 방법이 있다 | `MET` | `README.md`의 `Install and first run`, `Quality checks`, `PostgreSQL: the optional server tier`(Alembic), `Public fixtures`, `Reading a result` |

## 요약

| 상태 | 개수 |
|---|---|
| MET | 7 |
| PARTIAL | 3 |
| BLOCKED | 0 |

남은 세 PARTIAL 항목은 **lean P0 이후의 선택 검증**이다. 실행되지 않은 항목을 MET으로
바꾸지는 않지만, 아래 작업을 프론트엔드 개발의 선행 조건으로 요구하지 않는다.

- **#5의 orbit fixture** — 코드 작업은 완료됐다: `GP_TLE`/`TWO_BODY_V1` orbit provider가
  `ContactProvider` port 뒤에서 구현됐고, `ORBIT_DERIVED` contact source gate가 열렸으며(더 이상
  `UNSUPPORTED_CONTACT_SOURCE`로 막지 않는다), `PB-GOLDEN-ORB-01` 골든과 API·CLI 통합 테스트가
  추가됐고, engine manifest의 `orbit_provider_revision`·`constants_revision`·
  `frame_transform_revision`·`event_solver_revision`이 `ORBIT_DERIVED` 실행에서 실제 값으로
  채워진다(synthetic 실행은 여전히 `NOT_APPLICABLE`이라 기존 golden hash 불변).
  required CI는 `d467468`에서 통과했다. 남은 것은 `EVD-ORB-01`의 공개 재현 검증이며
  `Q-ORB-LICENSE-01` 해결까지 보류한다(로컬 전용, CI에서 skip 표기).
- **#2의 백업/복원** — 선택 PostgreSQL 운영 단계로 이관. 향후 해당 계층을 운영할 때
  dump/restore 절차 문서화와 실제 복원 검증이 필요하다.
- **#9의 H100 실행** — 먼저 필요한 것: 해당 하드웨어 접근. 받은 뒤 남는 일: 이미지 실행 근거
  기록과, CUDA 없이 도는지에 대한 실측(현재는 "이미지에 GPU 의존성이 없다"는 논거뿐이다).

궤도 증거·제품 통합·required CI 기준선이 확인되어 lean P0 상태는 **`P0_CORE_ACCEPTED`**다.
`d467468`의 Docker job은 이미지 빌드·실행·재시작 후 SQLite 결과 재조회까지 성공했으며,
Docker 미실행으로 기록하지 않는다. 외부 GMAT 재실행, H100 실행, 최신 PostgreSQL 운영 검증과는
별개다. 로컬 기준선은 378 passed / **11 PostgreSQL skipped**이고, public checkout에서는
withheld TLE의 11건도 추가 skip된다. 후속 commit은 CI를 재통과해야 하며 merge는 사용자 승인 대상이다.
