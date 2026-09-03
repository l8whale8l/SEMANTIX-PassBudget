# 실제 궤도 release gate 감사 — `PB-GOLDEN-ORB-01`

> 상태: **`P0_RELEASE_BLOCKED_ORBIT_INTEGRATION`** — 궤도 증거 gate PASS, 제품 통합 구현 완료,
> pushed commit의 required GitHub Actions green 대기 (2026-09-04 갱신)
> 이전 상태: `ORBIT_EVIDENCE_COMPLETE` (2026-09-03), `P0_RELEASE_BLOCKED_NEEDS_EVIDENCE` (최초 감사)
> 기준: `골든시나리오설계도.md` §25.11, §25.9 `G-01 ORBIT`, `P0_FUNCTIONAL_SPEC.md` §14 말미

최초 감사는 §25.11이 요구한 literal artifact가 저장소에 **하나도** 없다고 기록했다. 그 목록은
이제 모두 채워졌고, 각 항목은 실행 결과와 파일로 증명된다. 아래 표는 그 재감사 결과다.

## 재감사 결과

| §25.11 필수 artifact | 상태 | 근거 |
|---|---|---|
| `tle_line_1` / `tle_line_2` frozen 공개 TLE | **확보** | `evidence/orbit/EVD-ORB-01/tle_25544.celestrak.raw` (NORAD 25544, 공개 비임무 객체) |
| `content_sha256` + `provider` + `retrieved_at` | **확보** | `provenance.json`: CelesTrak, 2026-09-03T11:47:24Z, SHA-256 `baafb0e9…` (수신 원문 바이트 기준) |
| source URL과 license/provenance | **부분** | URL·출처·checksum 검증 기록됨. CelesTrak 재배포 조건은 `Q-ORB-LICENSE-01`로 **미해결** |
| `analysis_start`/`analysis_end` UTC | **확보** | `W1` 24 h, `W2` clipping 창. 두 fixture 모두 `inputs.json`에 literal |
| WGS-84 station lat/lon/ellipsoidal height literal | **확보** | 합성 검증 좌표 4~5개. 실제 KMU 좌표가 아님을 모든 artifact에 명시 |
| constant minimum elevation mask | **확보** | 전 station 5.000000° |
| propagator / constants revision | **확보** | `EVD-ORB-01` SGP4 (Vallado rev 2, WGS-72 상수), `EVD-ORB-02` `TWO_BODY_V1` (`Q-DATA-03` 해결) |
| time reference / leap data hash | **확보(단, 설계상 미사용)** | UT1−UTC와 polar motion을 양쪽 도구에서 0으로 고정했으므로 EOP/leap 테이블이 계산에 참여하지 않는다. 이는 누락이 아니라 계약 §2에 기록된 의도적 단순화이며 그 대가도 함께 기록했다 |
| frame transform profile | **확보** | `EVD-ORB-01` TEME→ITRF (GMST82), `EVD-ORB-02` EME2000→ITRF (IAU-76/80 전체 축약) |
| event solver profile | **확보** | 10 s bracket → 1×10⁻⁶ s bisection; peak는 golden-section |
| 독립 oracle 도구 이름과 버전 | **확보** | NASA GMAT **R2026a** (Apache-2.0, NASA Docket GSC-19468-1), `SPICESGP4` + `ContactLocator` |
| static expected pass event table | **확보** | `expected_table.json` 2건. 원시 report에서 변환기로 생성, 손으로 옮겨 적은 숫자 없음 |
| cross-tool delta table과 evidence-backed tolerance revision | **확보** | `delta_table.json` 2건. 총 58 pass, ceiling 위반 0 |

## 결과

| Quantity | Ceiling (사전 고정) | `EVD-ORB-01` 최악 | `EVD-ORB-02` 최악 |
|---|---|---|---|
| pass count | 정확히 일치 | 일치 (13) | 일치 (45) |
| AOS | 1.000 s | 0.017031 s | 0.013835 s |
| LOS | 1.000 s | 0.007365 s | 0.013816 s |
| duration | 2.000 s | 0.024554 s | 0.025763 s |
| maximum elevation | 0.050° | 0.005075° | 0.004992° |
| max-elevation time | 2.000 s | 0.010703 s | 0.030667 s |
| 무접촉 station | 정확히 일치 | 일치 | 일치 |
| 반복 실행 차이 | 0 | 0 | 0 |

±1초는 §25.11이 말한 대로 "초기 목표"였을 뿐이며, 승인 기준은 계약 §10.1의 error budget에서
유도한 ceiling이다. 관측된 최악값은 그 ceiling보다 한 자릿수 이상 작다.

## 이 gate가 실제로 잡아낸 결함

`EVD-ORB-02` 첫 실행은 AOS 오차 최대 **22.3 s**로 실패했다. 관성계 상태는 GMAT과 정확히 일치했고
지구고정계 위치만 **18.29 km**(대부분 Z축) 어긋났는데, 이는 J2000 이후 26년치 세차의 크기다.
원인은 `twobody.py`의 IAU-76 세차 중간 회전 `R2(θ)`를 X축 회전으로 잘못 구현한 것이었다. 축을
바로잡자 지구고정계 위치가 GMAT과 **0.1 m** 이내로 수렴했고 fixture는 통과했다.

이 결함은 그럴듯한 출력을 냈고 자기일관성 검사로는 절대 드러나지 않았다. §25.10이 자기검증을
금지하고 독립 구현을 요구하는 이유가 바로 이것이다.

## 최초 감사의 구현 결정 재검토

1. ~~production orbit adapter를 만들지 않았다~~ → 독립 oracle이 확보되었으므로
   `adapters/orbit`을 구현했다. 제품 엔진은 **python-sgp4 2.27(MIT, 순수 Python)** 이며,
   Orekit은 JVM 요구가 ADR-0001의 Python·CPU-first 이식성 계약과 충돌하여 제품에서 제외하고
   offline oracle로만 남겼다(`ADR-0004`, `Q-ORB-RUNTIME-01`).
2. **`ScenarioSnapshot.contact_source`는 이제 `ORBIT_DERIVED`를 허용한다.** domain gate가 열렸고
   provider가 접촉창을 생성한다. 아래 "완료된 작업" 참조.
3. engine manifest의 orbit 관련 revision은 `ORBIT_DERIVED` 실행에서 실제 값으로 채워진다
   (synthetic 실행은 `NOT_APPLICABLE` 유지).
4. `passbudget verify-golden`과 CI는 궤도 정확성을 절대 성능으로 주장하지 않는다. 결과는 합성
   입력에 대한 가정 기반 추정값이며, 두 독립 구현의 일치일 뿐 실제 지구 궤도 인증이 아니다.

## 완료된 작업 — `ORBIT_DERIVED` domain gate

궤도 **증거**와 제품 **통합**이 모두 완료되었다. 아래 7단계는 이 변경으로 구현됐다.

1. ✅ `Station`에 `GeodeticSite`(WGS-84 위/경도·타원체 고도·최소 앙각, 모두 정수 micro-unit) 추가.
2. ✅ 접촉(`SyntheticContact`/`ContactResult`)에 maximum elevation과 그 시각 추가 —
   `ORBIT_DERIVED`는 채우고 `SYNTHETIC_INJECTED`는 비운다(ADR-0002 CHECK 제약과 일치, geometric
   result·persisted row 모두).
3. ✅ `ScenarioSnapshot.validate()`의 `UNSUPPORTED_CONTACT_SOURCE` gate 해제 →
   provenance split 검증(`MISSING_ORBIT_SPEC`/`MISSING_STATION_SITE`/`SYNTHETIC_FORBIDS_*`/
   `ORBIT_DERIVED_CONTACTS_ARE_GENERATED`)으로 교체.
4. ✅ `OrbitContactProvider`(`adapters/orbit/provider.py`)를 `ContactProvider` port로 등록,
   composition root와 CLI가 `ORBIT_DERIVED`에만 주입(fallback 없음, ADR-0004).
5. ✅ engine manifest의 `orbit_provider_revision`·`constants_revision`·`frame_transform_revision`·
   `event_solver_revision`을 `ORBIT_DERIVED` 실행에서 실제 값으로 교체(synthetic 실행은
   `NOT_APPLICABLE` 유지 → 기존 golden hash 불변).
6. ✅ canonical input에 orbit 가정과 station site 포함(조건부 직렬화로 synthetic bytes 불변),
   `PB-GOLDEN-ORB-01` 골든 추가, 기존 synthetic golden hash 불변 확인.
7. ✅ API/CLI에서 provider revision과 orbit provenance 표시, `passbudget verify-golden`이
   `PB-GOLDEN-ORB-01`을 GMAT-anchored pass 수·산술 항등식·선택 결과로 검증.

남은 것은 pushed commit에서 required GitHub Actions가 green이 되는 것뿐이다.

## 남은 미해결 항목

| ID | 내용 | 소유자 |
|---|---|---|
| `Q-ORB-LICENSE-01` | CelesTrak 재배포 조건 확인 후 `EVD-ORB-01` 공개 게시 가부. 현재는 public 저장소에서 제외(로컬 전용), CI cross-tool은 합성 `EVD-ORB-02`로만 실행 | PM / legal |
| required CI green | pushed commit에서 `backend` workflow green 확인 | Backend |
