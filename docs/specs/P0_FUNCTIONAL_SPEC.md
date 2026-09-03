# SEMANTIX PassBudget P0 기능 명세서

> 문서 버전: 1.0  
> 상태: 백엔드 구현 기준선  
> 대상: P0 — 가정 기반 임무 데이터 예산 비교 도구  
> 라이선스: 저장소의 MIT License 적용

## 1. 제품 정의

SEMANTIX PassBudget은 위성·궤도, 지상국, 통신 용량 가정과 온보드 데이터 목록을 조합하여 **위성–지상국 접촉 기회, 모델상 전송 가능 용량, 데이터 전송 우선순위와 미전송 잔량을 비교**하는 초기 임무설계 도구다.

이 도구가 답해야 하는 질문은 다음 네 가지다.

1. 선택한 기간에 위성이 각 지상국과 몇 번, 얼마나 오래 접촉하는가?
2. 통신 가정을 적용했을 때 충돌 전 후보 용량과 충돌 해결 후 스케줄 용량은 얼마인가?
3. 데이터 목록을 넣었을 때 무엇을 언제 얼마나 보낼 수 있고 무엇이 남는가?
4. 궤도·지상국·전송률·데이터 정책을 바꾸면 결과가 얼마나 달라지는가?

결과는 **입력 가정에 따른 모델 결과**다. 실제 지상국 예약, 위성 명령, 링크 획득, 통신 성공, 파일의 지상 수신·검증, 전력·열·ADCS 적합성 또는 운용 승인을 뜻하지 않는다.

## 2. 설계 원칙

1. **재사용 가능한 도구**: KMU-ET02 하나를 하드코딩하지 않는다. 모든 위성·지상국·통신·정책은 수정하거나 새 revision으로 교체할 수 있다.
2. **가정의 정직한 표현**: 모르는 값은 0이나 임의 기본값으로 채우지 않는다. `UNKNOWN`, 명시적 `PROXY`, 적용 대상이 아닌 `NOT_APPLICABLE`을 구분한다.
3. **재현성**: 실행은 immutable input snapshot, 엔진·정책 버전, 결과와 hash를 보존한다.
4. **결정적 계산**: 같은 의미의 입력과 같은 버전은 행 순서나 UUID와 무관하게 같은 의미 결과와 hash를 만든다.
5. **결과의 과장 금지**: candidate 용량과 충돌 해결 후 unique 용량, 계획상 전송과 실제 수신을 분리한다.
6. **CPU 우선·이식 가능**: 일반 노트북, 서버, H100 서버의 CPU 컨테이너에서 같은 계산 코어를 실행한다.

## 3. P0 범위

### 3.1 포함 기능

- 수정 가능한 위성/궤도, 지상국, 통신, payload, 정책 preset과 revision
- 한 시나리오당 위성 1기, 지상국 1개 이상, spacecraft TX resource 1개
- 궤도 입력 `GP_TLE`, `VIRTUAL_CIRCULAR`
- UTC 분석 기간과 지상국별 고정 최소 고도각
- capacity provider `FIXED_RATE`, `FIXED_CAPACITY_PER_CONTACT`
- 분석 방식 `NETWORK_ONLY`, `QUEUE_AWARE`
- whole-opportunity 단위의 중첩 접촉 충돌 해결; 패스 중 handover 없음
- payload logical size, ready time, service class, priority, deadline, expiry, partial/resume, bundle/dependency
- 선택적 storage ledger
- 입력 snapshot, 실행 단계, 결과, 근거, 경고, 결정 trace와 hash
- 실행 간 비교와 사람이 읽는 보고서 및 기계 판독 가능한 JSON 결과

### 3.2 P0에서 제외하거나 feature gate로 닫는 기능

- 실제 지상국 booking, 비용·SLA·가용성 계약
- 위성 telecommand, 실제 ACK/수신 byte/frame loss/retry ingest
- 실제 링크 획득 또는 수신 성공 확률 보증
- 물리 link budget, modulation/coding 선택, 적응형 MCS
- wire/protocol/FEC overhead 상세 estimator
- `GP_OMM_SGP4`, OEM, Cartesian/Keplerian 임의 상태벡터
- 다중 spacecraft TX chain, contact 분할, mid-pass handover
- 전력·열·자세·관측 계획의 정밀 최적화
- storage 자동 eviction과 운영 hard lock
- 계정·결제·조직 권한 관리

제외 기능을 위한 빈 테이블이나 공개 API를 미리 만들지 않는다. 이후 기능은 새 schema/API revision으로 추가한다.

## 4. 사용자와 핵심 흐름

### 4.1 주요 사용자

- 임무 시스템 엔지니어: 하루/기간별 접촉과 전송 예산 비교
- 통신 담당자: 지상국, guard, goodput/capacity 가정 관리
- AI·payload 담당자: 산출물 크기, 우선순위, deadline과 bundle 구성
- 검증 담당자: 동일 입력 재실행, trace와 골든 테스트 확인

### 4.2 일곱 화면에 대응하는 기능 흐름

1. 시나리오 홈: 저장된 시나리오·revision·최근 실행 확인
2. 새 분석 기본: 분석 방식, 궤도, 기간, 지상국 선택
3. 네트워크/용량: 최소 고도각, guard, capacity provider와 근거 입력
4. 데이터 장바구니: `QUEUE_AWARE`일 때 payload와 선택적 storage 구성
5. 실행 전 검토: 해소된 값, PROXY/UNKNOWN, 차단 branch 확인
6. 결과 작업공간: KPI, timeline, allocation, backlog, 근거와 경고 확인
7. 비교: 두 실행의 바뀐 입력과 호환되는 metric delta 확인

직접 입력한 값도 저장 시 내부 profile/scenario revision으로 물질화한다. 사용자가 catalog를 먼저 모두 만들지 않아도 첫 분석을 실행할 수 있어야 한다.

## 5. 입력 계약

### 5.1 모든 외부 값의 공통 envelope

계산에 영향을 주는 외부 값은 값과 근거를 분리해 보존한다.

```text
ResolvedEvidenceValue<T>
  presence_state: PROVIDED | OMITTED | DEFAULTED
  value_state: KNOWN | UNKNOWN | NOT_APPLICABLE | null
  value: T | null
  canonical_unit: string | null
  evidence_state: CONFIRMED | PROVISIONAL | PROXY | UNKNOWN | null
  evidence_kind: MEASURED | MANUFACTURER_PROVIDED | PUBLIC_SOURCE |
                 ANALOG_PROXY | EXPERT_ESTIMATE | USER_ASSUMPTION |
                 SYSTEM_POLICY | DERIVED | null
  source_revision_id: string | null
  rationale: string | null
  captured_at: timestamp | null
  valid_from: timestamp | null
  valid_to: timestamp | null
  origin_kind: EXPLICIT | PARSED | DERIVED | SOURCE_IMPLIED | SYSTEM_DEFAULT
```

규칙:

- 숫자 `0`은 알려진 값이며 `UNKNOWN`, `OMITTED`, `NOT_APPLICABLE`과 다르다.
- `PROXY`로 실행하려면 값, source revision, 사용 이유와 영향을 받는 결과가 있어야 한다.
- 필수값 `UNKNOWN`은 그 값에 의존하는 branch만 `BLOCKED`한다.
- 잘못된 형식이나 상충하는 입력은 의존 branch를 `INVALID`로 만든다.

### 5.2 사용자가 입력하거나 선택하는 값

| 영역 | P0 입력 | 조건 |
|---|---|---|
| 분석 | 이름, 의사결정 질문, `analysis_mode`, 시작·종료 UTC | 항상 |
| 궤도 | preset 또는 `GP_TLE`/`VIRTUAL_CIRCULAR` 세부값과 근거 | 항상 |
| 지상국 | preset 또는 WGS-84 위도, east-positive 경도, ellipsoidal 고도 | 1개 이상 |
| 지상국 binding | scenario별 최소 고도각, 선택적 station preference rank | 지상국마다 |
| 통신 | `FIXED_RATE` 또는 `FIXED_CAPACITY_PER_CONTACT`, guard, accounting 의미와 근거 | 항상 |
| payload | 이름, logical byte, ready time, service class, priority, partial/atomic 규칙 | `QUEUE_AWARE` |
| 정책 | versioned queue policy, 선택적 deadline/expiry/bundle/dependency | `QUEUE_AWARE` |
| storage | ON/OFF. ON이면 physical capacity, protected reserve, initial occupancy, payload footprint | 선택 |

`GP_TLE` 필수값:

- 원문 line 1과 line 2
- provider와 retrieval time
- source/content hash
- SGP4 propagator
- TLE checksum과 두 line의 object ID 일치

`VIRTUAL_CIRCULAR` 필수값:

- epoch, 기준 지구반경, circular altitude, inclination
- RAAN 또는 canonical plane orientation
- argument of latitude/initial phase
- `eccentricity=0`과 propagator/constants profile revision

`FIXED_RATE` 필수값:

- exact rate `numerator_bits / denominator_seconds`
- `rate_semantics`, `measurement_point`, `rate_scope`, `accounted_effects[]`
- acquisition/release guard
- 선택적 time/byte reserve. 동일 항목을 두 번 차감해서는 안 됨

`FIXED_CAPACITY_PER_CONTACT` 필수값:

- eligible whole contact 하나의 최종 logical byte
- acquisition/release guard
- 해당 byte에 효율과 reserve가 이미 반영됐다는 명시

두 capacity provider의 입력은 동시에 활성화할 수 없다.

### 5.3 시스템이 자동 생성하는 값

- UUID, revision number, immutable stable key
- 선택 revision과 override/default를 해소한 input snapshot
- canonical units, UTC integer microseconds
- schema, canonicalization, time, policy, objective, tie-break, event-order revision
- engine manifest와 code revision(사용 가능한 경우)
- geometric access, modeled contact, candidate/scheduled session stable key
- run/stage/result 상태, reason code와 trace edge
- `input_snapshot_hash`, `result_content_hash`, `run_record_hash`

자동값은 일반 입력 화면에서 수정하지 못하게 하고 근거 보기에서 읽기 전용으로 노출한다.

## 6. 계산 파이프라인

```text
profile/scenario revisions
  → validation and value resolution
  → immutable input snapshot
  → orbit propagation and geometric access
  → guard/eligibility clipping and modeled contact
  → candidate logical capacity
  → overlap scheduling
  → optional queue allocation
  → optional storage event reduction
  → metrics, gaps, trace, report and hashes
```

각 단계는 별도 `RunStage`로 기록한다. 뒤 단계가 차단돼도 유효한 앞 단계 결과는 보존하고 조회할 수 있어야 한다.

### 6.1 시간과 interval

- API 입력은 ISO-8601 UTC `Z`, 소수점 0~6자리만 허용한다.
- canonical tick은 1 microsecond다.
- 파생 rational time은 nearest microsecond, ties-to-even으로 양자화한다.
- 모든 interval은 `[start, end)`다.
- 경계만 닿는 두 interval은 충돌하지 않는다.
- duration이 0인 tangent는 contact count에 포함하지 않는다.
- leap second가 포함된 window는 `UNSUPPORTED_LEAP_SECOND_WINDOW`로 `INVALID` 처리한다.

### 6.2 접촉 구간

```text
raw_usable = [true_aos + acquisition_guard, true_los - release_guard)
modeled_usable = raw_usable
                 ∩ analysis_window
                 ∩ station_availability
                 ∩ spacecraft_tx_allowed
                 ∩ pointing_allowed
                 ∩ link_eligible_interval
```

- P0 사용자 입력에는 station availability, TX/pointing interval의 정밀 모델을 강제하지 않는다. 적용하지 않는 축은 명시적 `NOT_APPLICABLE` 또는 전체 분석 구간을 허용하는 versioned system policy로 해소한다.
- guard 합이 true pass 길이 이상이면 용량은 `KNOWN_ZERO`, reason은 `GUARD_EXCEEDS_WINDOW`다.
- 접촉 단계는 geometric access, modeled contact, scheduled session을 서로 다른 결과로 보존한다.

### 6.3 `FIXED_RATE` 용량

권위값은 binary float가 아니라 integer/rational이다.

```text
1. true pass에 acquisition/release guard를 한 번 적용
2. 허용 interval과 교차
3. TIME_INTERVAL reserve의 union을 한 번 제거
4. 남은 rate segment의 normalized logical bits를 exact rational로 합산
5. 연속 bitstream 전체에서 whole byte로 한 번 floor
6. 중복 제거된 BYTE reserve를 한 번 차감
7. max(0, value)와 status 결정

logical_bytes_before_byte_reserve = floor(total_normalized_logical_bits / 8)
logical_payload_capacity = max(0, logical_bytes_before_byte_reserve - unique_byte_reserve)
```

같은 rate segment를 같은 rate의 여러 조각으로 나누거나 합쳐도 결과가 같아야 한다. byte 비교에 epsilon을 쓰지 않는다.

### 6.4 `FIXED_CAPACITY_PER_CONTACT` 용량

- 값은 eligible whole contact의 **최종 logical byte**다.
- guard는 modeled/conflict interval의 유효성을 정하지만 literal byte를 시간 비율로 다시 줄이지 않는다.
- rate, 추가 efficiency, time reserve 또는 byte reserve를 함께 적용하면 `INPUT_FACTOR_CONFLICT`다.
- `QUEUE_AWARE`에서는 session 시작 전에 ready인 payload만 배치한다.
- progress와 completion은 session end에 일괄 commit한다. 패스 내부 완료시각을 만들어내지 않는다.

### 6.5 중첩 접촉 스케줄

모든 후보와 억제 이유를 보존한다. 한 TX resource에서 겹치는 contact를 단순 합산하지 않는다.

`NETWORK_ONLY`:

- whole opportunity가 pairwise non-overlap인 subset 중 logical payload byte 합이 가장 큰 조합을 선택한다.
- 핵심 KPI는 선택한 세션의 `scheduled_unique_capacity_bytes`다.

`QUEUE_AWARE`:

- 남은 분석기간의 미래 세션을 포함하는 deterministic rollout으로 다음 lexicographic objective를 적용한다.
  1. 물리·시간·dependency 제약 만족
  2. `MANDATORY` on-time 달성 벡터 최대화
  3. `MANDATORY` tardiness 최소화
  4. 선택 policy utility 최대화
  5. scheduled logical byte 최대화
  6. deterministic tie-break

최종 tie-break:

```text
station_preference_rank ASC
→ modeled_completion_or_session_end ASC
→ usable_start_or_true_aos ASC
→ station_id lexical ASC
```

P0는 `session_selection_granularity=WHOLE_OPPORTUNITY`, `handover_policy=NONE`이다.

#### 6.5.1 실행 전략 — `EXACT_GLOBAL`과 `BOUNDED_APPROXIMATE`

> 추가: 2026-09-03 PM 결정 `(b)`. `SPEC_CONFLICT_REGISTER.md`의 `CONFLICT-QUEUE-02` 참조.
> 위 §6.5의 objective 정의는 바뀌지 않는다. 이 절은 그 objective를 **어떻게 푸는지**와,
> 각 방식이 무엇을 보증하고 무엇을 보증하지 않는지를 정한다.

§6.5의 objective는 전역이고, 충돌 component 간 결합은 payload queue를 통해 일어나 분리되지
않는다. 전역 최적 선택은 NP-hard이므로 하나의 알고리즘으로 "항상 최적이면서 항상 빠를" 수는
없다. 따라서 `execution_strategy`를 시나리오의 **semantic input**으로 둔다.

| | `EXACT_GLOBAL` (기본값) | `BOUNDED_APPROXIMATE` |
|---|---|---|
| 보증 | §6.5 objective의 전역 최적해 | feasible · deterministic **뿐** |
| 방법 | 충돌 component로 분해하고 분기 component 대안의 모든 조합을 전체 분석기간 rollout으로 채점 | 고정된 3개의 다항시간 interval scheduling 정책이 각각 완전한 feasible selection을 만들고 그 중 최선을 같은 objective로 채점 |
| 후보 생성 | maximal set 전체 열거 (겹침 밀도에 지수적) | component 분해·maximal set 열거 **없음** |
| 비용 | 조합 수 × 입력 규모 | 3 schedule + 최대 3 rollout, 겹침 밀도와 무관 |
| 상한 | `MAXIMAL_SET_BUDGET`, `GLOBAL_COMBINATION_BUDGET`, `EXACT_WORK_BUDGET` | **없음 — 위 세 상한과 그 오류는 이 경로에 적용되지 않는다** |
| 상한 초과 시 | 구조화된 오류로 거부 | 해당 없음 |
| `optimization_status` | `EXACT` | `APPROXIMATE` |
| `globally_optimal` | `true` | `false` |

**사용 조건.** 기본값은 `EXACT_GLOBAL`이다. exact 탐색이 상한을 초과하면 **실패한다**;
approximate로 자동 전환하지 않는다. 근사 결과를 원하면 사용자가 `execution_strategy`를
명시적으로 `BOUNDED_APPROXIMATE`로 선언해야 한다. 이 규칙의 목적은 "빠른 답"과 "옳은 답"이
같은 이름으로 반환되는 상황을 만들지 않는 것이다.

**exact 상한 두 가지.** 조합 수는 `GLOBAL_COMBINATION_BUDGET`, 조합 수 × 입력 규모로 추정한
작업량은 `EXACT_WORK_BUDGET`으로 각각 제한한다. 후자가 필요한 이유는 조합 수만으로는 비용을
말할 수 없기 때문이다 — 조합 하나가 전체 분석기간 rollout 하나이므로 §15.2의 60초 목표를
사실상 무력화하는 입력이 조합 상한 안에 들어올 수 있다. 초과는 각각
`QUEUE_HORIZON_GLOBAL_SEARCH_BUDGET_EXCEEDED`와
`QUEUE_HORIZON_EXACT_WORK_BUDGET_EXCEEDED`로 거부한다.

**두 mode는 후보 생성기를 공유하지 않는다.** 전략 분기는 후보 생성보다 먼저 일어난다. 이는
설계 선택이 아니라 정확성 요건이다 — 하나의 조밀하게 연결된 component는 `MAXIMAL_SET_BUDGET`을
넘는 maximal set을 가질 수 있지만 greedy scheduling으로는 평범하게 처리되므로, 분해를 공유하면
근사 mode가 자신이 존재하는 이유인 바로 그 입력을 exact 전용 오류로 거부하게 된다.

**approximate가 보증하지 않는 것.** 최적성, 최적해와의 거리, 그리고 두 approximate 결과 사이의
비교 가능성. `optimality_gap`은 현재 항상 `null`이다. scheduled byte 항 하나에 대한 정확한
상계는 값싸게 계산되지만, 그것은 lexicographic objective의 5번째 항일 뿐이어서 한 항의 gap을
objective의 gap이라고 부를 수 없다(byte 최적이면서 MANDATORY deadline을 놓치는 선택이
존재한다). objective 전체에 대한 bound가 생기기 전까지 이 필드는 null로 둔다.

**결과 표기.** 모든 결과는 `optimization` 블록에 `execution_strategy`, `optimization_status`,
`globally_optimal`, `optimality_gap`, `algorithm_revision`을 싣는다. approximate 결과에는
`NOT_GLOBALLY_OPTIMAL` warning이 붙는다. 등급이 다른 두 결과를 비교하면 비교 문서에
`OPTIMIZATION_GRADE_MISMATCH` warning이 붙는다 — 숫자 차이를 시나리오 차이로 읽는 것을 막기
위해서다.

**hash와 provenance.** `execution_strategy`는 canonical input snapshot, result, provenance,
engine manifest, 그리고 persistence round trip에 모두 포함된다. 전략만 다른 두 실행은 같은
질문에 대한 두 답이 아니라 **서로 다른 두 질문**이며, `input_snapshot_hash`부터 다르다.

`NETWORK_ONLY`는 최대 용량 dynamic program으로 정확히 풀리므로 이 선택이 적용되지 않는다.
`NETWORK_ONLY`에 `BOUNDED_APPROXIMATE`를 선언하면 `EXECUTION_STRATEGY_NOT_APPLICABLE`로
거부한다.

### 6.6 payload queue

- service class는 `MANDATORY`, `PRIORITY`, `BEST_EFFORT`다.
- 사용 가능한 policy는 immutable revision으로 식별한다. payload 이름으로 숨은 priority를 만들지 않는다.
- `ready_at <= allocation_start`인 payload만 할당할 수 있다.
- deadline target event가 `deadline_at`과 같으면 `ON_TIME`, 이후면 `LATE`다.
- expiry interval은 `[ready_at, expiry_at)`이며 expiry는 기본적으로 자동 삭제를 의미하지 않는다.
- atomic/non-resumable은 `ONLY_IF_COMPLETABLE`일 때 해당 session에서 완결 가능한 경우에만 시작한다.
- resumable payload는 정의된 chunk 단위로 partial allocation할 수 있다.
- bundle dependency cycle은 `INVALID`다.
- required bundle member와 optional member를 구분하고 actionable과 complete 상태를 각각 계산한다.

### 6.7 storage ledger

`storage_model_mode=DISABLED`이면 queue allocation과 backlog는 계산하지만 storage 결과는 `NOT_APPLICABLE`이다. 무한 저장공간이나 0B를 가정하지 않는다.

`ENABLED`의 P0 기본 계약:

```text
reserve_enforcement = HARD
storage_admission_policy = REJECT_NEW
storage_eviction_policy = NONE
storage_admission_granularity = OBJECT
reclaim_granularity = OBJECT
release_trigger = NEVER
delivery_assumption = NONE
delete_on_expiry = false

usable_limit = physical_capacity_bytes - protected_reserve_bytes
reserve_breach_bytes = max(0, occupancy_bytes - usable_limit)
hard_overflow_bytes = max(0, occupancy_bytes - physical_capacity_bytes)
```

- HARD limit에 새 object 전체가 들어가지 않으면 기존 데이터를 지우지 않고 새 object 전체를 거부한다.
- SOFT reserve는 명시적 what-if에서만 허용하며 physical capacity 초과는 항상 거부한다.
- object reclaim에서는 부분 전송만으로 storage를 회수하지 않는다.
- 동일 timestamp event 순서는 `CLOSE_RELEASE_ADMIT_ALLOCATE_V1`을 사용한다: allocation close → modeled progress commit → test/observed delivery ingest → release/reclaim → generation → validation/admission → allocation open.
- 사용자 API는 실제 ACK를 생성하거나 관측했다고 표현하지 않는다.

## 7. 상태, 등급과 오류

### 7.1 실행 상태

`ScenarioRun.status`:

- `QUEUED`, `RUNNING`, `SUCCEEDED`, `PARTIAL`, `FAILED`, `INVALID`

### 7.2 결과 계산 상태

- `COMPUTED`: 계산 완료
- `KNOWN_ZERO`: 유효하게 계산됐고 결과가 정확히 0
- `BLOCKED`: 필요한 입력이 `UNKNOWN`; 값은 `null`
- `INVALID`: 입력 형식·범위·조합이 잘못됨; 값은 `null`
- `NOT_APPLICABLE`: 선택한 분석에는 해당 branch가 없음; 값은 `null`

### 7.3 근거 등급

- `VERIFIED`: 입력 provenance와 계산 계약이 확인됨
- `ENGINEERING_ESTIMATE`: `PROVISIONAL`에 의존
- `CONCEPT_ONLY`: valid `PROXY` 또는 synthetic 입력에 의존
- `BLOCKED`: 계산 근거가 없음

상태와 등급은 독립 축이다. 예를 들어 valid PROXY guard 때문에 0B이면 `KNOWN_ZERO + CONCEPT_ONLY`다. `VERIFIED`는 실제 비행 수신 정확도나 운용 승인을 뜻하지 않는다.

### 7.4 오류 응답

모든 API 오류는 다음 구조를 사용한다.

```json
{
  "error": {
    "code": "INPUT_FACTOR_CONFLICT",
    "message": "Human-readable recovery guidance",
    "scope": "communication_revision",
    "field_paths": ["capacity.fixed_rate", "capacity.fixed_capacity_per_contact"],
    "affected_branches": ["capacity", "schedule"],
    "details": {}
  }
}
```

예외 stack, SQL, host path, secret 또는 내부 식별 정보는 공개 응답에 포함하지 않는다.

## 8. 사용자 결과 계약

### 8.1 모든 실행

- 분석 범위와 사용한 mode
- run status와 stage별 상태
- 계산 상태와 근거 등급
- 실제 결과가 아니라는 안전 문구
- 결과가 의존하는 주요 `PROXY`/`PROVISIONAL` 가정
- 사용한 profile/scenario revision, engine/policy/time/canonicalization revision
- input/result/run hash와 reason/warning trace

### 8.2 `NETWORK_ONLY` 핵심 결과

- 지상국별/전체 geometric contact count와 duration
- modeled candidate count와 duration
- selected scheduled session count와 duration
- `candidate_capacity_sum_bytes`: 충돌 전 후보 합계
- `scheduled_unique_capacity_bytes`: 충돌 해결 후 선택 용량; 기본 KPI
- station contribution과 억제된 candidate 및 reason
- 이름과 범위가 명확한 `geometric_gap`, `active_data_gap`, `scheduled_session_gap`

### 8.3 `QUEUE_AWARE` 추가 결과

- 계획상 배치된 logical byte와 분석 종료 backlog
- session별 payload allocation
- payload별 `completed`, `partial`, `deferred`, `not_started`와 남은 byte
- deadline on-time/late, miss count와 `late_by_s`
- bundle actionable/complete 상태
- Storage ON일 때 occupancy timeline, peak, reserve breach, rejected object

### 8.4 단위 표시

- 내부, hash와 allocation의 권위 단위는 integer byte다.
- `1 MB = 1,000,000 B`, `1 MiB = 1,048,576 B`다.
- 기본 표시는 MB 소수 둘째 자리와 MiB 소수 넷째 자리다.
- 반올림한 표시값을 계산 입력으로 재사용하지 않는다.

### 8.5 실행 비교

- baseline과 candidate의 해소된 입력 차이를 먼저 보여준다.
- unit, metric definition, accounting layer와 schema revision이 호환되는 metric만 delta를 계산한다.
- baseline이 0이면 절대 차이만 표시하고 변화율은 사유와 함께 `null`로 둔다.
- 근거 등급이 다르면 `EVIDENCE_GRADE_MISMATCH` 경고를 붙인다.
- 접촉, capacity, payload 상태 변화에 구조화된 reason을 제공한다.
- 비교 read model은 원본 run/result를 수정하지 않으며 P0에서는 별도 정본으로 저장하지 않아도 된다.

## 9. 수정·revision·snapshot 계약

- Profile, Scenario head는 이름, archive 상태와 current revision pointer만 변경할 수 있다.
- 계산은 head의 current pointer가 아니라 실행 시 명시적으로 선택된 immutable revision을 참조한다.
- published revision은 수정하거나 삭제하지 않는다. 변경은 새 revision을 만든다.
- preset도 일반 profile/scenario와 같은 revision 구조를 쓰며 `is_preset`으로 구분한다.
- 실행 전 resolver는 선택 revision, 사용자 override, system default와 evidence를 해소한 자기완결 `InputSnapshot`을 만든다.
- terminal run은 수정하지 않는다. 재실행은 새 run과 선택적 `replay_of_run_id`를 만든다.
- 최신 profile 변경은 과거 snapshot, run과 result를 바꾸지 않는다.

## 10. 해시와 canonicalization

P0 canonicalization revision은 `PB-C14N-JSON-V1`이다.

- object key는 UTF-8 byte lexical order로 정렬한다.
- 문자열은 Unicode NFC로 정규화한다.
- timestamp는 UTC integer microseconds로 표현한다.
- byte/count는 decimal string integer로 표현한다.
- rate/factor는 기약 rational `{numerator, denominator}`로 표현한다.
- schema가 set으로 선언한 배열은 stable key로 정렬하고, 순서가 의미 있는 배열은 순서를 보존한다.
- `null`, omitted, `NOT_APPLICABLE`을 구분한다.
- binary float와 일반 JSON number를 exact domain 정본으로 사용하지 않는다.

Hash framing:

```text
SHA-256(
  "SEMANTIX_PASSBUDGET\0<INPUT|RESULT|RUN>\0PB-C14N-JSON-V1\0"
  + canonical_bytes
)
```

- `input_snapshot_hash`: 해소된 semantic 값, evidence/source revision, defaults, schema와 계산 정책 revision
- `result_content_hash`: stable-key 결과, status/grade, reason/warning; DB UUID·행 순서 제외
- `run_record_hash`: 앞의 두 hash, run UUID, engine manifest와 execution metadata; secret과 host absolute path 제외

SHA-256은 비밀번호 보호용이 아니라 **동일한 실행 입력·결과의 식별, 변경 탐지와 재현성 확인**에 사용한다.

## 11. HTTP API v1

API prefix는 `/api/v1`이다. JSON 필드명은 snake_case를 사용한다. 도메인 계산 규칙은 API handler에 구현하지 않는다.

### 11.1 상태와 catalog

| Method | Path | 기능 |
|---|---|---|
| GET | `/health` | 프로세스 상태; secret·DB 상세 미노출 |
| GET | `/api/v1/presets` | kind별 공개/로컬 preset 목록 |
| POST | `/api/v1/profiles` | profile head 생성 |
| GET | `/api/v1/profiles/{profile_id}` | head와 revision 목록 조회 |
| POST | `/api/v1/profiles/{profile_id}/revisions` | 새 draft revision 생성 |
| POST | `/api/v1/profile-revisions/{revision_id}/publish` | validation 후 immutable publish |

### 11.2 시나리오

| Method | Path | 기능 |
|---|---|---|
| POST | `/api/v1/scenarios` | scenario head와 최초 draft 생성 |
| GET | `/api/v1/scenarios/{scenario_id}` | head, revisions, 최근 runs 조회 |
| POST | `/api/v1/scenarios/{scenario_id}/revisions` | 선택 revision을 기반으로 새 draft 생성 |
| POST | `/api/v1/scenario-revisions/{revision_id}/publish` | 구조·근거 validation 후 publish |
| POST | `/api/v1/scenario-revisions/{revision_id}/clone` | 독립 수정 가능한 변형 생성 |
| POST | `/api/v1/scenario-revisions/{revision_id}/snapshots` | 실행 가능한 immutable snapshot 생성 또는 branch별 차단 사유 반환 |

### 11.3 실행과 결과

| Method | Path | 기능 |
|---|---|---|
| POST | `/api/v1/runs` | `snapshot_id`로 새 run 생성·실행 |
| GET | `/api/v1/runs/{run_id}` | run과 stage 상태 조회 |
| GET | `/api/v1/runs/{run_id}/results` | typed 결과와 trace 조회 |
| GET | `/api/v1/runs/{run_id}/report` | 사람이 읽는 요약 보고서 조회 |
| POST | `/api/v1/comparisons` | 두 immutable run의 호환 metric과 delta 계산 |

P0 구현은 단일 프로세스에서 동기 계산할 수 있다. 다만 API는 run resource와 lifecycle을 반환하여 이후 worker로 옮겨도 domain contract가 바뀌지 않게 한다. 동일 run ID를 재실행하지 않는다.

### 11.4 CLI 동등성

최소 명령은 다음을 제공한다.

```text
passbudget validate <snapshot-or-fixture>
passbudget run <snapshot-or-fixture> --output <result.json>
passbudget compare <baseline-result> <candidate-result>
passbudget verify-golden
```

CLI, API와 test가 동일 application service와 domain core를 호출해야 한다.

## 12. 데이터베이스 계약

물리 기준은 `docs/database/database_schema_v0.1.md`, `docs/database/schema_decisions.md`, `db/schema_v0_1.sql`이다.

핵심 구조:

- evidence source/revision과 evidence assertion
- profile head/revision 및 orbit/ground station/communication/payload/policy typed revision
- scenario head/revision과 station/payload/dependency 구성
- engine manifest, input snapshot, scenario run과 run stage
- geometric access, modeled contact, candidate/scheduled session
- transfer allocation, run event, metric, annotation과 audit event

핵심 수치·관계·상태를 자유 형식 JSON 하나로만 저장하지 않는다. `input_snapshot.canonical_payload`는 versioned immutable 실행 artifact이며 typed relational 정본을 대체하지 않는다.

## 13. 합성 골든 시나리오 `PB-GOLDEN-CORE-01`

이 fixture는 KMU-ET02 실제 사양이 아니며 `SYN-CONTACT-01`이 접촉 구간을 직접 주입한다. 따라서 orbit dependency는 `NOT_APPLICABLE`, 결과 등급은 `CONCEPT_ONLY`다.

### 13.1 공통값

```text
window = [2027-01-01T00:00:00Z, 2027-01-02T00:00:00Z)
analysis_mode = QUEUE_AWARE
spacecraft_tx_resource_count = 1
session_selection_granularity = WHOLE_OPPORTUNITY
handover_policy = NONE
capacity_accounting_layer = LOGICAL_PAYLOAD
rate_semantics = APPLICATION_GOODPUT
rate_scope = ACTIVE_DATA_WINDOW
reserve_items = []
delivery_assumption = NONE
release_trigger = NEVER
reclaim_granularity = OBJECT
gap_scope = INTERNAL
```

### 13.2 접촉과 용량 oracle

| Station | AOS 규칙 | True pass | Guard 적용 후 rate | 횟수 | 용량/회 |
|---|---|---:|---|---:|---:|
| GS-A | 00:10 + 6h×k, k=0..3 | 10분 | 60초/60초 guard, 0.5 Mbps×120s + 1.5 Mbps×240s + 0.5 Mbps×120s | 4 | 60,000,000 B |
| GS-B | 03:10 + 6h×k, k=0..3 | 8분 | 40초/40초 guard, 0.8 Mbps×400s | 4 | 40,000,000 B |
| GS-C | 01:40 + 3h×k, k=0..7 | 6분 | 20초/20초 guard, 0.5 Mbps×320s | 8 | 20,000,000 B |

기대값:

- 총 contact 16개; 첫 GS-A는 00:10~00:20, 마지막 GS-C는 22:40~22:46
- A1 data interval은 00:11~00:19, capacity는 60,000,000B
- GS-A 합 240,000,000B
- GS-A+GS-B 합 400,000,000B
- GS-A+GS-B+GS-C 합 560,000,000B

### 13.3 payload queue oracle

모두 `ready_at=2027-01-01T00:05:00Z`다.

| ID | 이름 | logical byte | Deadline | 우선순위 | 전송 규칙 |
|---|---|---:|---|---:|---|
| P-ALERT | ALERT.json | 50,000 | 00:30 | 100 | atomic |
| P-THUMB | THUMB | 950,000 | 06:00 | 90 | atomic |
| P-MASK | MASK | 4,000,000 | 06:00 | 85 | atomic |
| P-ORIGINAL | ORIGINAL | 140,000,000 | 분석 종료 | 30 | 1,000,000B fixed chunk, resume |

첫 GS-A 세션의 기대 allocation:

```text
P-ALERT       50,000 B
P-THUMB      950,000 B
P-MASK     4,000,000 B
P-ORIGINAL 55,000,000 B
TOTAL      60,000,000 B
P-ORIGINAL remaining = 85,000,000 B
```

`FIXED_RATE`의 modeled completion은 각각 00:11:00.8, 00:11:16, 00:12:20이며 ORIGINAL은 00:19에 partial이다.

### 13.4 overlap oracle

- GS-A+GS-B+D의 충돌 전 candidate 합은 440,000,000B다.
- A2와 D가 충돌하고 objective가 A2를 선택한다.
- 충돌 해결 후 `scheduled_unique_capacity_bytes=400,000,000B`다.

### 13.5 storage oracle

- physical 200,000,000B, reserve 20,000,000B, initial occupancy 50,000,000B, new objects 145,000,000B
- SOFT what-if: occupancy 195,000,000B, reserve breach 15,000,000B, physical overflow 0B
- HARD: 작은 object 5,000,000B만 admission, ORIGINAL 140,000,000B reject, occupancy 55,000,000B

## 14. 필수 수용 기준

| ID | 검증 내용 | 기대 결과 |
|---|---|---|
| AC-P0-01 | synthetic contacts 실행 | A/B/C=4/4/8, 총16; orbit N/A, grade CONCEPT_ONLY |
| AC-P0-02 | rate가 UNKNOWN | contact는 계산되고 capacity branch만 BLOCKED/null; 0 대체 금지 |
| AC-P0-03 | A1 exact rate 적분 | 60,000,000B; segment 분할/병합 permutation에도 동일 |
| AC-P0-04 | guard 합이 pass와 같거나 큼 | KNOWN_ZERO, `GUARD_EXCEEDS_WINDOW` |
| AC-P0-05 | fixed capacity와 rate/reserve 동시 입력 | INVALID, `INPUT_FACTOR_CONFLICT` |
| AC-P0-06 | 기본 queue | A1 allocation과 85,000,000B backlog가 oracle과 일치 |
| AC-P0-07 | fixed-per-contact queue | session-start ready만 가능, completion은 session end |
| AC-P0-08 | overlapping contacts | candidate 440,000,000B, scheduled unique 400,000,000B |
| AC-P0-09 | endpoint-touch/zero tangent | endpoint-touch 비충돌, tangent 미집계 |
| AC-P0-10 | DB 삽입·입력 배열 순서 permutation | 선택 결과와 semantic hash 동일 |
| AC-P0-11 | 완전 동률 station | lexical station ID로 결정 |
| AC-P0-12 | deadline과 future session | horizon-aware objective가 mandatory on-time 가능성을 우선 |
| AC-P0-13 | atomic payload가 session에 안 들어감 | 전송 시작 안 함; 임의 partial 금지 |
| AC-P0-14 | dependency cycle | 해당 queue/schedule branch INVALID |
| AC-P0-15 | Storage OFF | queue 결과 계산, storage metric N/A; 0 또는 무한대로 표현 금지 |
| AC-P0-16 | HARD storage oracle | ORIGINAL whole-object reject, occupancy 55,000,000B |
| AC-P0-17 | SOFT storage oracle | reserve breach 15,000,000B, hard overflow 0B |
| AC-P0-18 | omitted/UNKNOWN/N/A/known 0/defaulted 0 | 서로 다른 canonical 상태와 올바른 branch 상태 |
| AC-P0-19 | NFC/NFD, key/unit/set permutation, byte >2^53 | 독립 구현과 production의 canonical bytes/hash 동일 |
| AC-P0-20 | persistence round trip | input/result canonical bytes와 hash 불변 |
| AC-P0-21 | 같은 semantic input 재실행 | input/result hash 동일, run ID/run hash는 달라도 됨 |
| AC-P0-22 | 비교 metric 정의 불일치 | 두 값은 표시 가능, delta/ratio는 null과 reason |
| AC-P0-23 | baseline 0 비교 | 절대 delta만 표시, 비율 null |
| AC-P0-24 | branch-local failure | run PARTIAL, 유효한 선행 결과 조회 가능 |
| AC-P0-25 | 공개 오류/로그 검사 | secret, SSH, DB URL, host absolute path 미노출 |

실제 궤도 출시 gate는 별도다. production orbit provider와 독립 oracle(NASA GMAT)의 AOS/LOS/max elevation 결과, tolerance와 provenance는 합성 `VIRTUAL_CIRCULAR`(`EVD-ORB-02`)에 대해 고정·교차검증됐고(gate PASS), `ORBIT_DERIVED` 제품 통합이 구현됐다. release 상태는 `P0_RELEASE_BLOCKED_ORBIT_INTEGRATION`이며 pushed commit에서 required GitHub Actions가 green이 되면 해제된다. frozen TLE(`EVD-ORB-01`)의 public 게시는 `Q-ORB-LICENSE-01` 해결까지 보류한다.

## 15. 비기능 요구사항

### 15.1 정확성과 결정성

- integer byte/rational arithmetic 사용; authoritative capacity에 float 금지
- 동일 입력의 결과가 OS, DB row order와 무관해야 함
- orbit float 계산은 adapter 경계에서 수행하고 canonical time/result로 양자화
- core test는 HTTP, ORM, DB, CUDA를 import하지 않아야 함

### 15.2 성능

- 기준: 1개 위성, 20개 지상국, 7일, payload 10,000개인 P0 분석을 일반 4-core CPU/16GB 환경에서 반복 실행 가능해야 한다.
- 초기 목표는 synthetic fixture 2초 이내, 위 기준 시나리오 60초 이내다. CI 측정 결과를 기록한 뒤 release 목표를 확정한다.
- 최적화는 profiling 후에만 한다. C++/CUDA를 선제 도입하지 않는다.

### 15.3 이식성

- Python CPU-first modular monolith
- PostgreSQL 16+
- Docker/Compose로 개발·배포 가능
- local file 또는 object storage adapter 교체 가능
- H100/CUDA, 특정 cloud, 특정 절대 경로에 의존하지 않음

### 15.4 보안과 공개 저장소

- `.env`, credentials, SSH key/config, 사설 IP/hostname, private TLE/mission data, DB dump, upload/export/log를 commit하지 않는다.
- public preset/fixture는 synthetic 또는 공개 출처·라이선스가 확인된 데이터만 사용한다.
- secret은 환경 변수 또는 secret manager로 주입한다.
- 입력 크기, 분석 기간, station/payload 개수에 상한을 두어 자원 고갈을 막는다.
- SQL은 parameterized query/ORM으로 실행한다.
- 원본 source artifact는 allowlist된 scheme/크기/type으로 저장하고 보고서에는 redaction을 적용한다.

## 16. 백엔드 Definition of Done

P0 백엔드는 다음을 모두 만족할 때 완료다.

1. framework 독립 domain core와 CLI/API adapter가 같은 application service를 호출한다.
2. schema migration이 빈 PostgreSQL 16 DB에 적용되고 rollback/restore 절차가 검증된다.
3. `PB-GOLDEN-CORE-01`이 DB 없이 CLI에서, DB를 사용한 API에서 동일 의미 결과를 낸다.
4. 25개 필수 수용 기준과 property test가 CI에서 통과한다.
5. frozen TLE와 virtual circular 독립 orbit fixture가 통과한다.
6. 독립 canonical reference implementation과 production hash가 vectors에서 일치한다.
7. terminal run의 snapshot/result/hash가 persistence round trip 후 바뀌지 않는다.
8. public repository secret scan과 dependency vulnerability 검사가 통과한다.
9. Docker image를 일반 CPU host와 H100 서버에서 CUDA 없이 실행할 수 있다.
10. README에 local 실행, test, migration, fixture 실행과 결과 해석 방법이 있다.

## 17. 권장 구현 순서

1. enum/unit/reason code registry와 executable domain types
2. canonicalization과 독립 test vectors
3. synthetic contact provider로 `PB-GOLDEN-CORE-01` DB 없는 vertical slice
4. PostgreSQL migration과 repository adapter round trip
5. snapshot/run lifecycle과 HTTP/CLI
6. `NETWORK_ONLY` overlap scheduler
7. `QUEUE_AWARE` allocation과 deadline/bundle
8. 선택적 storage ledger
9. `GP_TLE`/`VIRTUAL_CIRCULAR` provider와 독립 orbit fixtures
10. comparison/report, container, CI와 공개 저장소 보안 gate

프론트엔드는 P0 core의 골든 테스트와 첫 API vertical slice가 안정된 뒤 연결한다.

---

> **경로 안내 (2026-09-03 추가)** — 이 문서 본문의 `db/schema_v0_1.sql`은
> `db/postgresql/schema_v0_1.sql`로 이동했다. SQLite 전용 DDL은 `db/sqlite/schema_v1.sql`에
> 있다. 본문은 수정하지 않았으며, 이동 사유와 persistence tier 결정은
> `docs/architecture/ADR-0003-persistence-tiers.md`와
> `docs/specs/SPEC_CONFLICT_REGISTER.md`의 `CONFLICT-PERSIST-01`을 참조한다.
