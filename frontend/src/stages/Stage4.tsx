import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/endpoints";
import type { EslBforceSummary, EslFintSummary, EslPlasticSummary } from "../api/types";
import { warnText } from "../api/client";
import { history } from "../api/history";
import { PastFrame } from "../components/PastBadge";
import { Badge, Card, Empty, Stat } from "../components/ui";
import { CaseView3D } from "../view3d/CaseView3D";
import { isHiddenSource } from "../view3d/sources";
import { usePolling } from "../lib/usePolling";
import { METRIC_LABEL, fmtFixed, pct, sci, vec } from "../lib/format";
import { StageFrame, type StageProps } from "./StageFrame";
import { blockReason, eslPrereq, submitJob, useAction } from "./common";
import { dofText } from "../lib/format";
import { stepPath, stepState } from "../shell/StageStepper";

/** v0.24.5 설정으로 끈 노드 힘 출처의 요약 code → 문구(코어 esl/view3d_src.py REASON_TEXT 거울 — 시험이 같음 확인). 괄호 = 실제 원인
 *  설정 키(esl/pipeline.py: 경계력 = bforce.enabled, 내력 = bforce.enabled 와 bforce.fint.enabled 둘 다 true 여야 계산) */
export const SRC_DISABLED_TEXT: Readonly<Record<string, string>> = {
  BF_DISABLED: "설정에서 꺼짐(bforce.enabled)",
  FINT_DISABLED: "설정에서 꺼짐(bforce.enabled · bforce.fint.enabled)",
};
const disabledText = (code: string | null | undefined): string | null => (code ? SRC_DISABLED_TEXT[code] ?? null : null);

/** v0.24.0 경계력 ESL 요약 한 줄(esl_bforce.md §8) — 순수 문구(시험용) */
export function bforceLineText(b: EslBforceSummary): { text: string; warn: boolean } {
  // v0.24.5: 설정으로 끔(grade null + BF_DISABLED)은 "자료 없음 — 다시 추출" 이 아니라 꺼진 설정 키(아래 !grade 보다 먼저)
  const off = disabledText(b.code);
  if (off) return { text: `경계력 ESL: ${off}`, warn: false };
  // v0.24.2(esl_bforce_ondemand.md §6): 등급 none + code(BF_NO_DATA 제외) + reason → reason 그대로(BF_EXTRACT_* 등, code 목록은 화면에 두지 않음)
  if (b.grade === "none" && b.code && b.code !== "BF_NO_DATA" && b.reason)
    return { text: `경계력 ESL: 자료 없음 — ${b.reason}`, warn: false };
  if (!b.grade || b.grade === "none" || b.code === "BF_NO_DATA") {
    // 규칙: reason 이 있으면 reason(덤프 Case 등 다시 추출해도 소용없는 경우 포함), 없을 때만 옛 Case 하위 호환 문구
    if (b.reason) return { text: `경계력 ESL: 자료 없음 — ${b.reason}`, warn: false };
    return { text: "경계력 ESL: 자료 없음 — h3d 추출(v0.24.0 TCL)을 다시 실행하면 접촉력·가속도로 계산합니다", warn: false };
  }
  if (b.code === "BF_FAILED") return { text: `경계력 ESL: 계산 실패(${b.reason ?? "–"}) — 전 노드 ESL 결과는 그대로`, warn: true };
  const f = (v: number | null | undefined, d = 2) => (v == null ? "–" : v.toFixed(d));
  const lim = b.limit_text ?? b.limits ?? [];
  const parts = [
    `경계력 ESL: 등급 ${b.grade}`,
    `Σ|F| ${b.sum_abs == null ? "–" : b.sum_abs.toExponential(2)} N (전 노드 ESL 대비 ×${b.sum_abs_ratio_full == null ? "–" : b.sum_abs_ratio_full.toPrecision(2)})`,
    `관성 이완 ā = ${f(b.abar_g, 1)} g (보정 ${b.corr_rel == null ? "–" : `${(b.corr_rel * 100).toFixed(0)}%`})`,
    b.recon === "skipped" ? "재현 생략(메모리)" : `재현 MAC ${f(b.mac, 3)} · umax 오차 ${b.umax_err == null ? "–" : `${(b.umax_err * 100).toFixed(1)}%`}`,
    `반력 ${b.reaction_rel == null ? "–" : b.reaction_rel.toExponential(1)}`,
  ];
  return { text: parts.join(" · ") + (lim.length ? ` · ⚠ ${lim.join(" · ")}` : "") + (b.sign_suspect ? " · ⚠ CONT 부호 의심(설정 signs.cont 확인)" : ""), warn: lim.length > 0 || b.sign_suspect === true || b.recon === "poor" };
}

function BforceLine({ b }: { b: EslBforceSummary }) {
  const t = bforceLineText(b);
  return (
    <div className={`small${t.warn ? " warn-text" : " muted"}`} data-testid="esl-bforce-line" title={`질량 ${b.mass_source ?? "–"} · 불평형(힘) ${b.eq_force_rel == null ? "–" : b.eq_force_rel.toExponential(2)} · (모멘트) ${b.eq_moment_rel == null ? "–" : b.eq_moment_rel.toExponential(2)}`}>
      {t.text}
    </div>
  );
}

/** v0.24.0 보완 내력 ESL 요약 한 줄(esl_fint.md §8) — 순수 문구(시험용) */
export function fintLineText(b: EslFintSummary): { text: string; warn: boolean } {
  // v0.24.5: FINT_DISABLED(grade null) 분기는 !grade 보다 먼저 — 전에는 도달하지 못해 "/H3D/NODA/FINT 추가" 로 오안내
  const off = disabledText(b.code);
  if (off) return { text: `내력 ESL: ${off}`, warn: false };
  if (!b.grade || b.grade === "none" || b.code === "FINT_NO_DATA")
    return { text: `내력 ESL: 자료 없음 — ${b.reason ?? "내력 출력 없음 — 낙하 Engine 에 /H3D/NODA/FINT 추가"}`, warn: false };
  if (b.code === "FINT_FAILED") return { text: `내력 ESL: 계산 실패(${b.reason ?? "–"}) — 전 노드 ESL 결과는 그대로`, warn: true };
  const f = (v: number | null | undefined, d = 2) => (v == null ? "–" : v.toFixed(d));
  const e = (v: number | null | undefined) => (v == null ? "–" : v.toExponential(1));
  const lim = b.limit_text ?? b.limits ?? [];
  const sh = b.shared_status === "ok" ? `공유 노드 ${b.n_shared ?? 0}${(b.n_rot ?? 0) > 0 ? `(회전 연결 ${b.n_rot})` : ""}` : `공유 노드 ${b.shared_status === "failed" ? "확인 실패" : "–"}`;
  const parts = [
    `내력 ESL: F = ${b.sign != null && b.sign < 0 ? "−" : ""}FINT`,
    `Σ|F| ${b.sum_abs == null ? "–" : b.sum_abs.toExponential(2)} N (전 노드 ESL 대비 ×${b.sum_abs_ratio_full == null ? "–" : b.sum_abs_ratio_full.toPrecision(2)})`,
    `잔차 힘 ${e(b.res_force_rel)} · 모멘트 ${e(b.res_moment_rel)}${b.balance_applied === "inertia_relief" ? "(관성 이완 적용)" : ""}`,
    sh,
    b.recon === "skipped" ? "재현 생략(메모리)" : `재현 MAC ${f(b.mac, 3)} · umax 오차 ${b.umax_err == null ? "–" : `${(b.umax_err * 100).toFixed(1)}%`}`,
    `반력 ${e(b.reaction_rel)}`,
  ];
  const warn = b.unbalanced === true || (b.n_shared ?? 0) > 0 || b.recon === "poor";
  return { text: parts.join(" · ") + (b.unbalanced ? " · ⚠ 내력 합 불평형(공유 노드·추출 누락 의심)" : "") + (lim.length ? ` · ⚠ ${lim.join(" · ")}` : ""), warn };
}

/** v0.24.5 ③ 결과 카드 노드 힘 출처 요약 줄 표(esl_validate_tiers.md §11): key = 출처 표 키(view3d/sources.ts) = 요약 필드 이름
 *  (forces.<key>). 숨긴 출처(설정 ui.hidden_sources)의 줄은 그리지 않는다 — 계산·API·저장은 그대로. 거르는 곳 = visibleSummaryLines 한 곳 */
type SummaryForces = { bforce?: EslBforceSummary | null; fint?: EslFintSummary | null };
interface SummaryLine {
  key: string;
  text: (f: SummaryForces) => { text: string; warn: boolean } | null;
  el: (f: SummaryForces) => ReactNode;
}
const SUMMARY_LINES: readonly SummaryLine[] = [
  { key: "bforce", text: (f) => (f.bforce ? bforceLineText(f.bforce) : null), el: (f) => (f.bforce ? <BforceLine key="bforce" b={f.bforce} /> : null) },
  { key: "fint", text: (f) => (f.fint ? fintLineText(f.fint) : null), el: (f) => (f.fint ? <FintLine key="fint" b={f.fint} /> : null) },
];
const visibleSummaryLines = (): readonly SummaryLine[] => SUMMARY_LINES.filter((l) => !isHiddenSource(l.key));

/** 화면에 그릴 요약 줄(순수 — 시험용): 요약이 있고 숨기지 않은 출처만, 표 순서 */
export function summaryLinesOf(f: SummaryForces | null | undefined): { key: string; text: string; warn: boolean }[] {
  if (!f) return [];
  return visibleSummaryLines().flatMap((l) => {
    const t = l.text(f);
    return t ? [{ key: l.key, ...t }] : [];
  });
}

/** v0.24.0 소성 진단 한 줄(esl_fint.md §4) — 순수 문구 */
export function plasticLineText(p: EslPlasticSummary): string {
  if (p.status !== "ok") return `소성(t*): 없음${p.status === "failed" ? `(읽기 실패 ${p.reason ?? ""})` : "(소성 변형률 결과 없음)"}`;
  return `소성(t*): 면적 ${((p.frac ?? 0) * 100).toFixed(1)}%(εᵖ > ${p.eps_min ?? "–"}, 요소 ${p.n ?? 0}/${p.n_total ?? "–"}) · 최대 εᵖ ${p.max == null ? "–" : p.max.toFixed(4)} — 선형 ESL 은 소성 영역을 재현하지 못함`;
}

function FintLine({ b }: { b: EslFintSummary }) {
  const t = fintLineText(b);
  return (
    <div className={`small${t.warn ? " warn-text" : " muted"}`} data-testid="esl-fint-line" title={`부호 ${b.sign ?? "–"} · 균형 ${b.balance_applied ?? "–"} · 기준 형상 불평형(힘) ${b.eq_force_rel == null ? "–" : b.eq_force_rel.toExponential(2)} · (모멘트) ${b.eq_moment_rel == null ? "–" : b.eq_moment_rel.toExponential(2)} — 노드 모멘트 미사용(병진 내력만)`}>
      {t.text}
    </div>
  );
}

export function Stage4({ c, reload, allowed }: StageProps) {
  const [sp] = useSearchParams();
  const pastRunId = sp.get("run"); // 과거 실행 읽기 전용(?run=)
  const runId = pastRunId ?? c.current_esl_run_id;
  const run = usePolling(() => (runId ? api.eslRun(runId) : Promise.resolve(null)), 0, [runId, c.version]);
  const sets = usePolling(() => (c.current_support_set_id ? api.supportSets(c.id) : Promise.resolve([])), 0, [c.current_support_set_id]);
  const support = sets.data?.find((s) => s.id === c.current_support_set_id);
  const act = useAction(reload);
  const r = run.data;
  const pastJobId = pastRunId ? r?.job_id ?? null : null;
  const review = usePolling(() => (pastJobId ? history.review(pastJobId) : Promise.resolve(null)), 0, [pastJobId]);

  // 3D 하중 보기 + 상위 표(과거 실행은 availability = full 일 때만)
  const showLoad = !!r && !(pastRunId && review.data?.result.availability !== "full");

  const prereq = eslPrereq(c);

  const content = (
    <>
      {!pastRunId && (
      <Card title="입력 요약">
        <div className="stats">
          <Stat
            label="t*"
            value={c.tstar ? `${c.tstar.time.toFixed(3)} s (프레임 ${c.tstar.frame_index})` : "–"}
            hint={c.tstar ? `${METRIC_LABEL[c.tstar.metric]} · 요소 ${c.tstar.elem_id}` : undefined}
          />
          <Stat label="지표" value={c.tstar ? METRIC_LABEL[c.tstar.metric] : "–"} />
          <Stat label="지지 노드" value={support ? support.node_ids.join(", ") : "–"} />
          <Stat label="dof" value={support ? support.dofs.map(dofText).join(" / ") : "–"} />
        </div>
        {r && (r.frame_index !== c.tstar?.frame_index || r.support_set_id !== c.current_support_set_id) && (
          <div className="small warn-text">
            아래 결과는 이전 입력(프레임 {r.frame_index}) 기준입니다.
          </div>
        )}
      </Card>
      )}
      {!runId ? (
        <Empty>아직 ESL을 계산하지 않았습니다</Empty>
      ) : !r ? (
        <Empty>불러오는 중…</Empty>
      ) : (
        <>
          <Card title="결과" right={r.status === "READY" ? <Badge kind="ok">READY</Badge> : <Badge kind="bad">FAILED</Badge>}>
            <div className="stats">
              <Stat label="강체 회전각" value={`${fmtFixed(r.kabsch?.rot_deg, 2)}°`} />
              <Stat label="변형 RMS / max" value={`${fmtFixed(r.kabsch?.rms_def, 3)} / ${fmtFixed(r.kabsch?.max_def, 3)}`} hint="강체 제거 후 상대 변위(mm)" />
              <Stat label="ΣF" value={<span className="mono small">{vec(r.forces?.sum_f ?? undefined)}</span>} />
              <Stat label="ΣM" value={<span className="mono small">{vec(r.forces?.sum_m ?? undefined)}</span>} />
              <Stat label="평형 오차" value={sci(r.forces?.equilibrium_rel)} hint={r.forces?.moment_rel != null ? `모멘트 ${sci(r.forces.moment_rel)}` : undefined} />
              <Stat label="잡음 (힘)" value={pct(r.forces?.noise.force_rel, 2)} hint={r.forces?.noise.disp_precision ?? undefined} />
              <Stat label="잡음 (hotspot 변형률)" value={pct(r.forces?.noise.hotspot_strain_rel, 2)} />
              <Stat label="하중 노드 수" value={r.forces?.n_nodes_loaded?.toLocaleString() ?? "–"} />
            </div>
            {r.forces && visibleSummaryLines().map((l) => l.el(r.forces!))}
            {r.forces?.plastic && (
              <div className={`small${r.forces.plastic.status === "ok" && (r.forces.plastic.frac ?? 0) > 0 ? " warn-text" : " muted"}`} data-testid="esl-plastic-line">
                {plasticLineText(r.forces.plastic)}
              </div>
            )}
            {r.warnings.length > 0 && (
              <ul className="reasons">
                {r.warnings.map((w) => (
                  <li key={w} className="small warn-text">
                    {warnText(w)}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          {showLoad && runId && (
            <CaseView3D
              runId={runId}
              enabled={showLoad}
              note={
                c.extract_summary?.cumulative ? (
                  <div className="small muted" data-testid="v3d-state-note">
                    형상: 이전 런 변형 상태
                  </div>
                ) : null
              }
            />
          )}
        </>
      )}
    </>
  );
  if (pastRunId)
    return (
      <PastFrame title="③ ESL" review={review.data} error={run.error ?? review.error} currentHref={stepPath(c.project_id, c.id, 3)}>
        {content}
      </PastFrame>
    );
  return (
    <StageFrame
      title="③ ESL"
      status={stepState(c, 3)}
      error={act.error ?? run.error}
      onJobDone={() => void reload()}
      primary={{ label: "ESL 계산", onClick: () => act.run(() => submitJob(c, "ESL_SOLVE")), disabledReason: blockReason(allowed, c, 3, prereq), busy: act.busy }}
    >
      {content}
    </StageFrame>
  );
}
