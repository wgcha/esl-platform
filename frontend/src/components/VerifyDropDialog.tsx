// v0.12.0 검증 낙하 계획 대화상자(esl_scx_relay.md §10.2·SR-D-10·15). 안(best/ 가 남은 안만) · 씬 선택 라디오 2개
// [가장 나쁜 씬 N개 | 고른 ESL 전부] · 씬 표(POST /verify-drops/plan — 저장 안 함) · 제외된 누적 씬 경고 · 제출 건수·예상 시간·상한 ·
// 접힌 '고급'(Radioss 버전·ncpu) → 주 버튼 [검증 낙하 시작]. 상한·기본 N·예상 시간은 모두 서버 값.
import { useEffect, useState } from "react";
import { ApiError, errorText } from "../api/client";
import { VD_START, excludeLabel, hoursText, ratioText, verify } from "../api/verify";
import type { EntryOut, VerifyDesignOut, VerifyDropCreateOut, VerifyDropIn, VerifyMode, VerifyPlanOut } from "../api/types";

const HPC_VERSION = /^\d{2,4}(\.\d{1,3}){0,2}$/;

export function VerifyDropDialog({
  studyId, designs, initialDesign, initialPlan, entries, onClose, onCreated,
}: {
  studyId: string;
  designs: VerifyDesignOut[];
  initialDesign: string;
  /** 버튼 판정 때 받은 계획(같은 안·worst 기본) — 기본 N·고급 자리표시 */
  initialPlan: VerifyPlanOut | null;
  entries: EntryOut[];
  onClose: () => void;
  onCreated: (r: VerifyDropCreateOut) => void;
}) {
  const [design, setDesign] = useState(initialDesign);
  const [mode, setMode] = useState<VerifyMode>("worst");
  const [nText, setNText] = useState(String(initialPlan?.default_worst_n ?? initialPlan?.default_n ?? initialPlan?.n_submit ?? ""));
  const [version, setVersion] = useState("");
  const [ncpu, setNcpu] = useState("");
  const [plan, setPlan] = useState<VerifyPlanOut | null>(initialPlan);
  const [planError, setPlanError] = useState<string | null>(null);
  const [planning, setPlanning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const max = plan?.max_scenes ?? initialPlan?.max_scenes ?? null;
  const n = Number(nText);
  const nProblem = mode !== "worst" ? null : !nText.trim() || !Number.isInteger(n) || n < 1 ? "N 은 1 이상 정수입니다" : max !== null && n > max ? `N 은 최대 ${max}입니다` : null;
  const ncpuN = Number(ncpu);
  const hpcProblem = version.trim() && !HPC_VERSION.test(version.trim()) ? "Radioss 버전 형식이 올바르지 않습니다(예 26.1)" : ncpu.trim() && !(Number.isInteger(ncpuN) && ncpuN >= 1 && ncpuN <= 4096) ? "ncpu 는 1~4096 정수입니다" : null;

  const body = (): VerifyDropIn => ({
    bead_doe_id: studyId,
    design_id: design,
    mode,
    ...(mode === "worst" ? { n } : {}),
    ...(version.trim() || ncpu.trim() ? { hpc: { ...(version.trim() ? { version: version.trim() } : {}), ...(ncpu.trim() ? { ncpu: ncpuN } : {}) } } : {}),
  });

  // 씬 목록(저장 안 함): 안·방식·N 이 바뀌면 다시
  useEffect(() => {
    if (nProblem) {
      setPlan(null);
      setPlanError(null);
      return;
    }
    let alive = true;
    setPlanning(true);
    const t = setTimeout(() => {
      verify
        .plan({ bead_doe_id: studyId, design_id: design, mode, ...(mode === "worst" ? { n } : {}) })
        .then((p) => {
          if (!alive) return;
          setPlan(p);
          setPlanError(null);
        })
        .catch((e) => {
          if (!alive) return;
          setPlan(null);
          setPlanError(errorText(e));
        })
        .finally(() => alive && setPlanning(false));
    }, 250);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [studyId, design, mode, nText]); // eslint-disable-line react-hooks/exhaustive-deps

  const block = nProblem ?? hpcProblem ?? (planning ? "씬 목록 확인 중…" : planError ?? (!plan ? "씬 목록 확인 중…" : !plan.scenes.length ? "검증할 씬이 없습니다" : null));

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const r = await verify.create(body());
      onCreated(r);
    } catch (e) {
      setError(e instanceof ApiError ? errorText(e) : String(e));
      setBusy(false);
    }
  }

  const caseTitle = (caseId: string | null, entryId: string | null) =>
    entries.find((e) => e.id === entryId)?.case_title ?? entries.find((e) => e.case_id === caseId)?.case_title ?? caseId ?? entryId ?? "–";
  const excluded = plan?.excluded ?? [];

  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal vd-modal" role="dialog" aria-modal="true" aria-labelledby="vd-title">
        <h3 id="vd-title">검증 낙하 — Radioss(SCX)</h3>
        <div className="small muted">안의 모핑 좌표를 원 Case 입력 사본에 노드 ID 기준으로 넣어 씬마다 SCX 에서 낙하를 다시 돌립니다. 결과는 원 낙하와 나란히 비교만 합니다.</div>
        <div className="vd-row">
          <label className="field">
            <span className="field-label">안</span>
            <select aria-label="검증 안" value={design} onChange={(e) => setDesign(e.target.value)}>
              {designs.map((d) => (
                <option key={d.id} value={d.id}>
                  순위 {d.rank} · {d.id}
                </option>
              ))}
            </select>
          </label>
          <fieldset className="vd-mode">
            <legend className="field-label">씬</legend>
            <div className="checks" role="radiogroup" aria-label="씬 선택">
              <label className="check">
                <input type="radio" name="vd-mode" checked={mode === "worst"} onChange={() => setMode("worst")} />
                가장 나쁜 씬
                <input
                  className="mono vd-n"
                  inputMode="numeric"
                  aria-label="N"
                  value={nText}
                  disabled={mode !== "worst"}
                  aria-invalid={!!nProblem}
                  onChange={(e) => setNText(e.target.value)}
                />
                개
              </label>
              <label className="check">
                <input type="radio" name="vd-mode" checked={mode === "all"} onChange={() => setMode("all")} />
                고른 ESL 전부
              </label>
            </div>
          </fieldset>
        </div>
        <div className="small muted">나쁜 순 = 이 안의 ESL별 컴플라이언스 비 r(C안 / C베이스라인)이 큰 순(덜 개선·악화 먼저). 같은 Case 의 ESL 은 1개 씬으로 합칩니다.</div>
        <div className="table-wrap vd-scenes">
          <table className="table compact" aria-label="검증 씬">
            <thead>
              <tr>
                <th>씬(Case)</th>
                <th className="num" title="선형 예측 컴플라이언스 비">r(C)</th>
                <th className="num" title="선형 예측 최대 변위 비">r(u)</th>
                <th className="num" title="선형 예측 최대 변형률 비">r(ε)</th>
              </tr>
            </thead>
            <tbody>
              {(plan?.scenes ?? []).map((s) => (
                <tr key={s.case_id}>
                  <td className="small">{s.case_title ?? caseTitle(s.case_id, s.entry_id)}</td>
                  <td className="num mono small">{ratioText(s.r_c)}</td>
                  <td className="num mono small">{ratioText(s.r_umax)}</td>
                  <td className="num mono small">{ratioText(s.r_epsmax)}</td>
                </tr>
              ))}
              {!plan?.scenes.length && (
                <tr>
                  <td colSpan={4} className="small muted">
                    {planning ? "씬 목록 확인 중…" : planError ?? nProblem ?? "–"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {excluded.length > 0 && (
          <ul className="reasons small warn-text" aria-label="제외된 씬" data-testid="vd-excluded">
            {excluded.map((x) => (
              <li key={`${x.case_id ?? x.entry_id ?? ""}:${x.code}`} data-code={x.code}>
                {x.case_title ?? caseTitle(x.case_id, x.entry_id)} — {x.reason} <span className="muted">({excludeLabel(x.code)})</span>
              </li>
            ))}
          </ul>
        )}
        <div className="small" data-testid="vd-summary">
          {plan ? `제출 ${plan.n_submit}건 · 예상 씬당 약 ${hoursText(plan.est_hours)}시간 · 상한 ${plan.max_scenes}건` : max !== null ? `상한 ${max}건` : ""}
        </div>
        <details className="vd-adv">
          <summary className="small">고급 — Radioss 버전·ncpu</summary>
          <div className="vd-row">
            <label className="field">
              <span className="field-label">Radioss 버전</span>
              <input className="mono" aria-label="Radioss 버전" value={version} placeholder={plan?.hpc_default?.version ?? initialPlan?.hpc_default?.version ?? "설정값"} onChange={(e) => setVersion(e.target.value)} />
            </label>
            <label className="field">
              <span className="field-label">ncpu</span>
              <input className="mono" inputMode="numeric" aria-label="ncpu" value={ncpu} placeholder={String(plan?.hpc_default?.ncpu ?? initialPlan?.hpc_default?.ncpu ?? "설정값")} onChange={(e) => setNcpu(e.target.value)} />
            </label>
          </div>
          <div className="small muted">비우면 서버 설정값을 씁니다.</div>
        </details>
        <div className="small muted">SCX 실행은 씬마다 수 시간 걸릴 수 있습니다. 창을 닫아도 서버에서 계속됩니다.</div>
        {error && (
          <div className="error-text small" role="alert">
            {error}
          </div>
        )}
        <div className="actions modal-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            닫기
          </button>
          <span className="primary-wrap" title={block ?? undefined}>
            <button type="button" className="btn primary" data-primary="true" disabled={!!block || busy} onClick={() => void start()} data-testid="vd-start">
              {busy ? "처리 중…" : VD_START}
            </button>
          </span>
        </div>
      </div>
    </div>
  );
}
