# P0 백엔드 Definition of Done 상태

> 기준: `docs/specs/P0_FUNCTIONAL_SPEC.md` §16의 10개 항목
> 갱신: 2026-09-03, 커밋 `edcad89` 기준

`docs/specs/P0_ACCEPTANCE_MATRIX.md`는 §16의 4번 항목(25개 수용 기준) 하나만 다룬다. 이 문서는
나머지 아홉 개를 포함한 열 개 전부의 상태를 기록한다.

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
| 4 | 25개 필수 수용 기준과 property test가 CI에서 통과한다 | `MET` | `docs/specs/P0_ACCEPTANCE_MATRIX.md` 25/25 `PASS`. property test는 `tests/property/test_horizon_properties.py`, `tests/property/test_rate_properties.py`. `backend` workflow의 `verify` job이 매 push마다 전체를 돌린다 |
| 5 | frozen TLE와 virtual circular 독립 orbit fixture가 통과한다 | `BLOCKED` | evidence `EVD-ORB-01`, `EVD-ORB-02` 부재. 근거와 필요한 산출물은 `docs/specs/ORBIT_RELEASE_GATE.md`. 소유자: Orbit/Backend + V&V. **합성 결과를 실제 궤도 성능으로 제시하지 않기 위해 이 항목은 채우지 않는다** |
| 6 | 독립 canonical reference implementation과 production hash가 vectors에서 일치한다 | `MET` | `tests/reference_c14n.py`가 production 코드를 재사용하지 않는 별도 구현이고, `tests/unit/test_canonical.py`가 두 구현의 digest를 vector마다 대조한다 |
| 7 | terminal run의 snapshot/result/hash가 persistence round trip 후 바뀌지 않는다 | `MET` | 세 tier 모두: `test_repository_equivalence.py`(memory·SQLite 상시, PostgreSQL은 URL이 있을 때), `test_postgres_persistence.py`. 저장 타입과 행 삽입 순서가 hash를 바꾸지 않음을 `test_input_order_permutation_reaches_the_same_stored_rows`가 확인한다 |
| 8 | public repository secret scan과 dependency vulnerability 검사가 통과한다 | `MET` | secret scan은 `scripts/secret_scan.py`(`verify` job). dependency 검사는 `backend` workflow의 `audit` job(`pip-audit`)이며 `edcad89`에서 통과했다. 도입 시점에 실제 취약점 하나(`pytest` `PYSEC-2026-1845`)를 검출했고, `pytest>=9.0.3`으로 올려 해소한 뒤 `No known vulnerabilities found`가 됐다 |
| 9 | Docker image를 일반 CPU host와 H100 서버에서 CUDA 없이 실행할 수 있다 | `PARTIAL` | 일반 CPU host(linux/amd64)는 `backend` workflow의 `docker` job이 `edcad89`에서 실행해 검증했다: 빌드, 이미지 안의 `verify-golden`·`where`, API로 run 계산, **컨테이너 재시작 후 같은 run 재조회**. **빠진 것: H100 host 실행.** 해당 하드웨어에 접근할 수 없어 실행하지 못했다. 이미지에 CUDA·GPU 의존성이 없다는 것은 근거가 아니라 논거이므로 `MET`으로 적지 않는다. 소유자: 인프라 접근 권한을 가진 쪽 |
| 10 | README에 local 실행, test, migration, fixture 실행과 결과 해석 방법이 있다 | `MET` | `README.md`의 `Install and first run`, `Quality checks`, `PostgreSQL: the optional server tier`(Alembic), `Public fixtures`, `Reading a result` |

## 요약

| 상태 | 개수 |
|---|---|
| MET | 7 |
| PARTIAL | 2 |
| BLOCKED | 1 |

남은 세 항목은 모두 코드 작업이 아니다.

- **#2의 백업/복원**: 선택적 PostgreSQL tier의 운영 절차다. ADR-0003 이후 PostgreSQL은
  필수 기반이 아니므로, 이 절차가 P0 release를 막는지 아니면 tier를 실제로 배포할 때
  필요한지는 결정 사항이다.
- **#9의 H100 실행**: 하드웨어 접근이 필요하다.
- **#5의 orbit fixture**: 외부 evidence가 필요하다. `docs/specs/ORBIT_RELEASE_GATE.md`의
  `P0_RELEASE_BLOCKED_NEEDS_EVIDENCE`와 같은 항목이다.
