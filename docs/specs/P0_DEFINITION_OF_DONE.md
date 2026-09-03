# P0 백엔드 Definition of Done 상태

> 기준: `docs/specs/P0_FUNCTIONAL_SPEC.md` §16의 10개 항목
> 갱신: 2026-09-03, P0 2차 보정 작업 이후

`docs/specs/P0_ACCEPTANCE_MATRIX.md`는 §16의 4번 항목(25개 수용 기준) 하나만 다룬다. 이 문서는
나머지 아홉 개를 포함한 열 개 전부의 상태를 기록한다.

## 검증 상태 — `LOCAL PASS / CI PENDING`

`QUEUE_AWARE_LEXICOGRAPHIC_HORIZON_V3`(전역 horizon 선택), `execution_strategy`(exact /
approximate), 입력 상한, HTTP 수신 바이트 제한, fixture 경로 차단은 **로컬에서만 검증됐다.**
아직 commit·push되지 않았으므로 GitHub Actions에서 한 번도 실행되지 않았다.

| 항목 | 상태 |
|---|---|
| ruff / mypy / pytest / verify-golden / secret_scan / alembic (로컬) | `LOCAL PASS` |
| `backend` workflow (`verify`, `clean-install`, `docker`, `audit`) | `CI PENDING` |
| `postgresql` workflow | `CI PENDING` — 위 변경은 PostgreSQL adapter를 건드리지 않지만, canonical input hash가 바뀌었으므로 3-tier 동등성 suite가 다시 실행되어야 한다 |

**아래 표의 `MET`은 그 항목이 마지막으로 CI에서 통과했을 때의 근거를 가리킨다.** 이번 변경분에
대한 CI 근거와 commit SHA는 실제로 CI가 통과한 뒤에만 기록한다. 통과하지 않은 것을 통과했다고
적지 않는다.

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
| 4 | 25개 필수 수용 기준과 property test가 CI에서 통과한다 | `MET` | `docs/specs/P0_ACCEPTANCE_MATRIX.md` 25/25 `PASS`. property test는 `tests/property/test_horizon_properties.py`, `tests/property/test_rate_properties.py`. horizon property test가 보장하는 범위는 **작은 인스턴스(후보 6개 이하)에서 전역 탐색이 모든 pairwise non-overlap 부분집합 완전탐색과 같은 선택을 낸다**는 것이며, 탐색 비용이나 기준 규모 동작은 보장하지 않는다 — 그쪽은 `GLOBAL_COMBINATION_BUDGET`과 `tests/unit/test_scalability.py`가 담당한다. `backend` workflow의 `verify` job이 매 push마다 전체를 돌린다. **2026-09-03 2차 보정분은 아직 CI에서 실행되지 않았다 (`LOCAL PASS / CI PENDING`)** |
| 5 | frozen TLE와 virtual circular 독립 orbit fixture가 통과한다 | `PARTIAL` | 궤도 증거 gate는 **PASS**이고(`EVD-ORB-02` 합성 fixture가 GMAT과 교차검증, 최악 AOS 0.014 s), `ORBIT_DERIVED`가 제품에 통합되어 API·CLI에서 접촉창→용량→모델 우선순위까지 흐른다(`PB-GOLDEN-ORB-01`, `tests/integration/test_orbit_derived_flow.py`). **빠진 것: pushed commit에서의 GitHub CI green.** `LOCAL PASS / CI PENDING`. `EVD-ORB-01`은 CelesTrak TLE 재배포 조건(`Q-ORB-LICENSE-01`) 미해결로 public에서 제외하고 로컬 전용으로 유지하며, 그 교차검증 case는 CI에서 skip으로 표기된다(pass로 계산하지 않는다). |
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

남은 세 항목은 **외부 입력이나 환경, 또는 CI 실행이 먼저 필요하다.** 아래는 각 항목에서 해야 할
남은 일이다.

- **#5의 orbit fixture** — 코드 작업은 완료됐다: `GP_TLE`/`TWO_BODY_V1` orbit provider가
  `ContactProvider` port 뒤에서 구현됐고, `ORBIT_DERIVED` contact source gate가 열렸으며(더 이상
  `UNSUPPORTED_CONTACT_SOURCE`로 막지 않는다), `PB-GOLDEN-ORB-01` 골든과 API·CLI 통합 테스트가
  추가됐고, engine manifest의 `orbit_provider_revision`·`constants_revision`·
  `frame_transform_revision`·`event_solver_revision`이 `ORBIT_DERIVED` 실행에서 실제 값으로
  채워진다(synthetic 실행은 여전히 `NOT_APPLICABLE`이라 기존 golden hash 불변). **남은 것:
  pushed commit에서 required GitHub Actions가 green이 되는 것.** 그리고 `EVD-ORB-01`의 public
  게시는 `Q-ORB-LICENSE-01` 해결까지 보류한다(로컬 전용, CI에서 skip 표기).
- **#2의 백업/복원** — 먼저 필요한 것: 이 절차가 P0 범위인지에 대한 PM 결정. 범위라면 남는 일:
  dump/restore 절차 문서화와, 그것을 `postgresql` workflow에서 실제로 실행하는 검증 단계.
- **#9의 H100 실행** — 먼저 필요한 것: 해당 하드웨어 접근. 받은 뒤 남는 일: 이미지 실행 근거
  기록과, CUDA 없이 도는지에 대한 실측(현재는 "이미지에 GPU 의존성이 없다"는 논거뿐이다).

궤도 증거 gate는 **PASS**이고 `ORBIT_DERIVED` 제품 통합이 구현됐으므로 release 상태는
`P0_RELEASE_BLOCKED_NEEDS_EVIDENCE`에서 **`P0_RELEASE_BLOCKED_ORBIT_INTEGRATION`**으로 바뀐다.
이 상태는 pushed commit에서 required GitHub Actions가 green이 되면 해제된다. 실행하지 않은
PostgreSQL 운영 절차, H100 실행은 어느 것도 `MET`으로 바꾸지 않았고, skip된 검사는 pass로 계산하지
않는다.
