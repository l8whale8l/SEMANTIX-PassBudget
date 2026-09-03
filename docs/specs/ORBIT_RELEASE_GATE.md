# 실제 궤도 release gate 감사 — `PB-GOLDEN-ORB-01`

> 상태: **`P0_RELEASE_BLOCKED_NEEDS_EVIDENCE`**  
> 감사일: 2026-09-03  
> 기준: `골든시나리오설계도.md` §25.11, §25.9 `G-01 ORBIT`, `P0_FUNCTIONAL_SPEC.md` §14 말미

`골든시나리오설계도.md` §25.11은 아래 literal artifact가 **모두** 저장되기 전까지
`PB-GOLDEN-ORB-01`을 `BLOCKED`로 유지하라고 규정한다. 이 문서는 저장소와 부모 프로젝트
폴더를 실제로 검색한 결과이며, 없는 것을 코드로 만들어 채우지 않았다.

## 감사 결과

| §25.11 필수 artifact | 저장소 존재 여부 | 확인 방법 |
|---|---|---|
| `tle_line_1` / `tle_line_2` frozen 공개 TLE | **없음** | 저장소 및 부모 폴더 전체에 TLE 원문 라인이 없다. `orbit_revision.tle_line1/2` 컬럼만 존재한다 |
| `content_sha256` + `provider` + `retrieved_at` | **없음** | 위와 동일 |
| source URL과 license/provenance | **없음** | 공개 출처가 문서에 지정되어 있지 않다 |
| `analysis_start`/`analysis_end` UTC | 없음 (fixture 미정의) | orbit fixture 자체가 없다 |
| WGS-84 station lat/lon/ellipsoidal height literal | **없음** | 합성 fixture의 station은 좌표가 없다(`NOT_APPLICABLE`) |
| constant minimum elevation mask | **없음** | `scenario_station.minimum_elevation_udeg`는 synthetic 실행에서 NULL |
| propagator / constants revision | **없음** | `Q-DATA-03`이 미해결(§26.14) |
| time reference / leap data hash | 부분 | engine manifest에 `UTC_US_NO_LEAP_SECOND_V1`은 있으나 leap-second 데이터 해시는 없다 |
| frame transform profile | **없음** | manifest에 `NOT_APPLICABLE`로 기록 |
| event solver profile | **없음** | manifest에 `NOT_APPLICABLE`로 기록 |
| 독립 oracle 도구 이름과 버전 | **없음** | 어떤 문서에도 지정되어 있지 않다 |
| static expected pass event table | **없음** | AOS/LOS/max-elevation 기대표가 없다 |
| cross-tool delta table과 evidence-backed tolerance revision | **없음** | ±1초는 §25.11이 명시한 대로 "초기 목표"일 뿐 승인 기준이 아니다 |

`VIRTUAL_CIRCULAR` 쪽도 동일하게 미충족이다. §23.10과 §26.14의 `Q-DATA-03`
("가상궤도 P0 전파기: TWO_BODY / J2 선택")이 아직 결정되지 않았다.

## 이 감사에 따른 구현 결정

1. **production orbit adapter를 만들지 않았다.** 독립 oracle이 없는 상태에서 SGP4 adapter를
   추가하면, 그 출력을 기대값으로 복사하는 것 외에 검증할 방법이 없다. 그것은 §25.10이
   금지한 "production 구현으로 만든 oracle"이다.
2. **`ScenarioSnapshot.contact_source`는 `SYNTHETIC_INJECTED`만 허용한다.**
   `ORBIT_DERIVED` 입력은 `UNSUPPORTED_CONTACT_SOURCE`로 거부한다. 스키마와 migration은
   `ORBIT_DERIVED`를 완전히 표현할 수 있으므로(ADR-0002), 증거가 확보되면 domain gate만
   열면 된다.
3. **engine manifest는 orbit 관련 revision을 `NOT_APPLICABLE`로 명시한다.** 빈 문자열이나
   그럴듯한 기본값을 넣지 않는다.
4. `passbudget verify-golden`과 CI는 궤도 정확성을 전혀 주장하지 않는다.

## gate를 열기 위해 필요한 작업

담당: Orbit/Backend + V&V (`EVD-ORB-01`, `EVD-ORB-02`)

1. 공개 TLE 하나를 고정하고 원문 두 줄, provider, retrieval timestamp, source URL, license,
   SHA-256을 저장소에 커밋한다. 비공개 mission TLE는 사용할 수 없다(`SECURITY.md`).
2. WGS-84 지상국 좌표 literal, 고정 최소 앙각, 분석 구간 UTC를 고정한다.
3. propagator/constants/time/frame/event-solver revision을 결정하고
   `Q-DATA-03`(`VIRTUAL_CIRCULAR` 전파기)을 확정한다.
4. 독립 도구(이름과 정확한 버전)로 pass count와 AOS/LOS/max-elevation expected table을
   생성해 static artifact로 커밋한다.
5. 두 구현의 delta table을 만들고, 그 delta로부터 tolerance revision을 정한다. ±1초를 먼저
   가정하지 않는다.
6. 위가 모두 갖춰진 뒤에 production orbit adapter와 cross-tool 테스트를 구현하고,
   `ScenarioSnapshot`의 `ORBIT_DERIVED` gate를 연다.

그때까지 release 상태는 `P0_RELEASE_BLOCKED_NEEDS_EVIDENCE`로 유지한다.
