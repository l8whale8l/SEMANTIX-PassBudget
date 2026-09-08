/**
 * In-app help (spec §7): FAQ, glossary, how the numbers are computed, and the general limitations —
 * the long always-on "가정과 한계" list and internal warning codes were moved out of the sidebar to
 * here (general) and to “이번 실행 계산 근거” (per-run) and the report (safety text). Core explanations
 * live in the app, not only behind external links.
 */
export function HelpPanel() {
  return (
    <div className="help">
      <section className="help__section">
        <h4>PassBudget은 무엇인가요?</h4>
        <p>
          위성·지상국·통신 가정에 따른 <strong>전송 예산</strong>을 계산하고, 제한된 예산에서 어떤 출력물을
          먼저 보낼지 비교하는 <strong>의사결정 도구</strong>입니다. 실시간 위성 관제·안테나 제어·실제 수신
          확인 시스템이 아니며, 지구본과 타임라인은 계산 결과를 이해하기 위한 수단입니다.
        </p>
      </section>

      <section className="help__section">
        <h4>용어</h4>
        <dl className="help__terms">
          <dt>전송 예산 (선택 전송 예산)</dt>
          <dd>충돌을 해결한 뒤 선택된 세션들의 고유 용량 합. 이 도구의 기본 KPI입니다.</dd>
          <dt>후보 접촉 용량</dt>
          <dd>겹침을 포함할 수 있는 상한이라 예산으로 그대로 쓰면 안 됩니다.</dd>
          <dt>패스 / 접촉창</dt>
          <dd>위성이 지상국에서 보이는 시간 구간(AOS→LOS). 선택 세션 수와 기하 접촉 수는 다릅니다.</dd>
          <dt>분석 모드</dt>
          <dd>‘출력 배분 포함(QUEUE_AWARE)’은 출력물을 세션에 배분까지, ‘전송 예산만(NETWORK_ONLY)’은 접촉·용량만 계산합니다.</dd>
          <dt>분할 방식</dt>
          <dd>‘통째로 전송(ATOMIC_OBJECT)’은 한 세션에서 전체를, ‘나눠 전송(FIXED_CHUNK)’은 조각 단위로 여러 세션에 걸쳐 전송합니다. 조각 크기는 ‘패스당 한도’가 아니라 조각 하나의 크기입니다.</dd>
          <dt>단위</dt>
          <dd>MB는 1,000,000바이트(십진)이며 MiB(1,048,576)와 다릅니다. 작은 값은 B·KB, 큰 값은 MB·GB로 표시합니다.</dd>
        </dl>
      </section>

      <section className="help__section">
        <h4>계산 방법(요약)</h4>
        <ul className="help__list">
          <li>궤도는 2체 요소(또는 TLE)로 전파하고, 최소 앙각 이상 구간을 접촉창으로 봅니다.</li>
          <li>각 접촉창의 용량은 지상국 속도·유효율과 지속시간으로 계산합니다.</li>
          <li>충돌(동시 접촉)을 해결해 세션을 선택하고, 그 고유 용량 합이 전송 예산입니다.</li>
          <li>QUEUE_AWARE에서는 서비스 등급·마감·우선순위 기반 큐로 출력물을 세션에 배분합니다.</li>
          <li>모든 수치는 백엔드가 정수(바이트·마이크로초)로 계산하며, 화면은 표시만 합니다.</li>
        </ul>
      </section>

      <section className="help__section">
        <h4>일반적인 한계</h4>
        <ul className="help__list">
          <li>결과는 <strong>가정 입력에 기반한 모델 추정</strong>이며, 실제 지상 수신·운용 승인·비행 성능 인증이 아닙니다.</li>
          <li>합성 기준 궤도·합성 지상국을 사용합니다. 실측 성능이 아닙니다.</li>
          <li>근사(BOUNDED_APPROXIMATE) 실행은 전역 최적을 증명하지 않습니다.</li>
          <li>이번 실행에 적용된 구체적 가정·경고는 좌측 사이드바의 <em>‘이번 실행 계산 근거’</em>와 보고서에서 확인하세요.</li>
        </ul>
      </section>

      <section className="help__section">
        <h4>안내</h4>
        <p className="hint">
          설치, 실행, 결과 해석과 공개 기여 원칙은 저장소의 <span className="mono">README.md</span>에서
          확인할 수 있습니다.
        </p>
      </section>
    </div>
  )
}
