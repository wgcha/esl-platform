import { useSearchParams } from "react-router-dom";
import { api } from "../api/endpoints";
import { history } from "../api/history";
import { PastFrame } from "../components/PastBadge";
import type { FieldSummary } from "../api/types";
import { Badge, Card, Empty, Stat } from "../components/ui";
import { FieldOverlay } from "../components/FieldOverlay";
import { SectionChart } from "../components/SectionChart";
import { ErrHistogram } from "../components/ErrHistogram";
import { ReportLink } from "../components/ReportLink";
import { LibraryRegister } from "../components/LibraryRegister";
import { usePolling } from "../lib/usePolling";
import { dt, fmt, pct, pv, sci, spv } from "../lib/format";
import { StageFrame, type StageProps } from "./StageFrame";
import { blockReason, submitJob, useAction } from "./common";

/** 코어 validation fail_reasons 코드 → 설명 */
export const FAIL_REASON_LABEL: Record<string, string> = {
  DISP_RMS: "변위 RMS 오차가 기준 초과",
  HOTSPOT_STRAIN: "hotspot 1위 ε_eq 오차가 기준 초과",
  REACTION: "3-2-1 반력이 기준 초과(자기평형 아님)",
  NOISE_FLOOR: "변위 정밀도 잡음 바닥이 기준 초과",
  FIELD_MAX_ERR: "최대변형률 요소의 ESL 오차가 기준 초과",
  FIELD_P90_ERR: "전 요소 |오차| P90이 기준 초과",
};


/** 최대변형률 비교 수치(계약 §7.2) */
function StrainCompare({ f }: { f: FieldSummary }) {
  const mx = f.max;
  const cr = f.criteria;
  const p90 = f.abs_err_pct?.p90;
  return (
    <div className="stats" data-testid="strain-compare">
      <Stat label="최대 ε (Radioss)" value={fmt(mx?.eps_rad, 4)} sub={mx ? `요소 ${mx.elem_id}` : "상승 요소 없음"} hint="t* 에서 상승 중인 요소 중 최대" />
      <Stat label="같은 요소 ε (ESL)" value={fmt(mx?.eps_esl, 4)} sub={mx ? `ESL 전체 최대 ${fmt(mx.eps_esl_max, 4)} (요소 ${mx.eps_esl_max_elem_id})` : undefined} />
      <Stat
        label="최대변형률 오차"
        value={spv(mx?.err_pct)}
        sub={cr ? `기준 ≤ ${cr.max_err_pct_max}%` : undefined}
        tone={mx && cr ? (mx.abs_err_pct > cr.max_err_pct_max ? "bad" : "ok") : undefined}
      />
      <Stat label="|오차| P90" value={pv(p90)} sub={cr ? `기준 ≤ ${cr.p90_err_max}%` : undefined} tone={p90 != null && cr ? (p90 > cr.p90_err_max ? "bad" : "ok") : undefined} />
      <Stat label="비교 요소" value={`${f.n_valid.toLocaleString()} / ${f.n_elems.toLocaleString()}`} sub={`상승 중 ${f.n_rising.toLocaleString()}`} />
    </div>
  );
}

function ErrDistribution({ f }: { f: FieldSummary }) {
  const q = f.abs_err_pct;
  const fw = f.frac_within;
  return (
    <>
      <table className="table compact" aria-label="오차 분위수">
        <thead>
          <tr>
            {["평균", "P50", "P90", "P95", "최대", "≤5%", "≤10%", "≤20%"].map((h) => (
              <th key={h} className="num">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            {[q?.mean, q?.p50, q?.p90, q?.p95, q?.max].map((v, i) => (
              <td key={i} className="num">
                {pv(v)}
              </td>
            ))}
            {["5", "10", "20"].map((k) => (
              <td key={k} className="num">
                {fw ? pct(fw[k]) : "–"}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
      <ErrHistogram hist={f.hist} crit={f.criteria?.p90_err_max} />
      <div className="small muted">
        valid 요소 {f.hist.n.toLocaleString()}개의 부호 있는 오차, 범위 ±{f.hist.range_pct ?? "–"}%
        {f.hist.n_clipped ? ` (범위 밖 ${f.hist.n_clipped}개는 끝 막대)` : ""}. 점선 = ±P90 기준.
      </div>
    </>
  );
}

function TopTable({ f }: { f: FieldSummary }) {
  if (!f.top.length) return null;
  return (
    <details className="card">
      <summary>ε_rad 상위 {f.top.length}개 요소 (Radioss·ESL·오차)</summary>
      <div className="table-wrap scroll">
        <table className="table compact">
          <thead>
            <tr>
              <th className="num">#</th>
              <th>요소</th>
              <th className="num">ε (Radioss)</th>
              <th className="num">ε (ESL)</th>
              <th className="num">오차</th>
            </tr>
          </thead>
          <tbody>
            {f.top.map((r, i) => (
              <tr key={r.elem_id}>
                <td className="num">{i + 1}</td>
                <td>{r.elem_id}</td>
                <td className="num">{fmt(r.eps_rad, 4)}</td>
                <td className="num">{fmt(r.eps_esl, 4)}</td>
                <td className="num">{spv(r.err_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

const num = (x: unknown) => (typeof x === "number" ? x : undefined);
const critText = (x: unknown) => (typeof x === "number" ? String(x) : Array.isArray(x) ? x.join(",") : x == null ? "–" : String(x));

export function Stage5({ c, reload, allowed }: StageProps) {
  const [sp] = useSearchParams();
  const pastVal = sp.get("val"); // 과거 실행 읽기 전용(?val=)
  const runId = pastVal ? null : c.current_esl_run_id;
  const st5 = c.stage_status?.["5"];
  // 검증 완료는 Case version 을 바꾸지 않으므로 ⑤ 상태(job_id·state)가 바뀌면 다시 읽는다
  const run = usePolling(() => (runId ? api.eslRun(runId) : Promise.resolve(null)), 0, [runId, c.version, st5?.state, st5?.job_id]);
  const vid = pastVal ?? run.data?.latest_validation_id ?? null;
  const val = usePolling(() => (vid ? api.validation(vid) : Promise.resolve(null)), 0, [vid]);
  const vHistory = usePolling(() => (pastVal ? Promise.resolve(null) : api.validations(c.id)), 0, [c.id, vid, c.version, st5?.state]);
  const act = useAction(reload);
  const v = val.data;
  const pastJobId = pastVal ? v?.job_id ?? null : null;
  const review = usePolling(() => (pastJobId ? history.review(pastJobId) : Promise.resolve(null)), 0, [pastJobId]);
  const filesGone = !!pastVal && review.data?.result.availability !== "full";

  const prereq = !runId ? "④ ESL을 먼저 계산하세요" : run.data?.stale ? "④ ESL을 다시 계산하세요(입력이 바뀜)" : null;
  const crit = v?.criteria ?? {};
  const hsMax = num(crit.hotspot_strain_rel_err_max);
  const dispMax = num(crit.disp_rms_rel_max);
  const reacMax = num(crit.reaction_rel_max);

  const content = (
    <>
      {!v ? (
        <Empty>{pastVal ? "불러오는 중…" : runId ? "아직 검증하지 않았습니다" : "④ ESL을 먼저 계산하세요"}</Empty>
      ) : (
        <>
          <Card
            title="판정"
            right={
              <span className="inline-actions">
                {v.verdict === "PASS" ? <Badge kind="ok">PASS</Badge> : <Badge kind="bad">FAIL</Badge>}
                {!pastVal && <ReportLink url={api.caseReportUrl(c.id)} dep={`${v.id}:${c.stage_status?.["5"]?.state}`} />}
                {!pastVal && <LibraryRegister projectId={c.project_id} v={v} allowed={allowed} failLabels={FAIL_REASON_LABEL} />}
              </span>
            }
          >
            <div className="stats">
              <Stat
                label="변위 RMS (상대)"
                value={v.disp_rms_rel === null ? "생략" : sci(v.disp_rms_rel)}
                hint={v.disp_rms_rel === null ? "전체 재해석 생략(validation.full_solve)" : dispMax !== undefined ? `기준 ≤ ${sci(dispMax)}` : undefined}
              />
              <Stat label="반력 (상대)" value={v.reaction_rel === null ? "생략" : sci(v.reaction_rel)} hint={reacMax !== undefined ? `기준 ≤ ${sci(reacMax)}` : undefined} />
              <Stat
                label="hotspot 1위 오차"
                value={v.hotspots.length ? pct(v.hotspots[0].rel_err) : "–"}
                hint={hsMax !== undefined ? `기준 ≤ ${pct(hsMax)}` : undefined}
              />
            </div>
            {Object.keys(crit).length > 0 && (
              <div className="small muted">
                기준:{" "}
                {Object.entries(crit)
                  .map(([k, x]) => `${k} = ${critText(x)}`)
                  .join(" · ")}
              </div>
            )}
            {v.field && <StrainCompare f={v.field} />}
            {v.fail_reasons.length > 0 && (
              <ul className="reasons">
                {v.fail_reasons.map((f) => (
                  <li key={f} className="error-text">
                    {f}
                    {FAIL_REASON_LABEL[f] ? ` — ${FAIL_REASON_LABEL[f]}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          {v.field && !filesGone ? (
            <>
              <Card title="겹쳐보기 — 요소 변형률 (PCA 평면)">
                <FieldOverlay vid={v.id} hotspots={v.hotspots} summary={v.field} />
              </Card>
              <div className="grid2">
                <Card title="단면선 — 변형 형상 겹치기">
                  <SectionChart vid={v.id} />
                </Card>
                <Card title="오차 분포 (valid 요소)">
                  <ErrDistribution f={v.field} />
                </Card>
              </div>
              <TopTable f={v.field} />
            </>
          ) : pastVal ? null : (
            <div className="warn-box" role="status">
              전 요소 비교 자료가 없는 예전 검증입니다 — ⑤ 검증을 다시 실행하면 겹쳐보기를 볼 수 있습니다.
            </div>
          )}
          <div className="grid2">
            <Card title="hotspot ε_eq 오차">
              <table className="table compact">
                <thead>
                  <tr>
                    <th>요소</th>
                    <th className="num">ε (Radioss)</th>
                    <th className="num">ε (검증)</th>
                    <th className="num">오차</th>
                  </tr>
                </thead>
                <tbody>
                  {v.hotspots.map((h) => {
                    const over = hsMax !== undefined && h.rel_err > hsMax;
                    return (
                      <tr key={h.elem_id} className={over ? "bad-row" : undefined}>
                        <td>{h.elem_id}</td>
                        <td className="num">{fmt(h.eps_rad, 4)}</td>
                        <td className="num">{fmt(h.eps_val, 4)}</td>
                        <td className="num">{pct(h.rel_err)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Card>
            <Card title="제외 요소">
              {v.excluded.length ? (
                <table className="table compact">
                  <thead>
                    <tr>
                      <th>요소</th>
                      <th>사유</th>
                    </tr>
                  </thead>
                  <tbody>
                    {v.excluded.map((x) => (
                      <tr key={x.elem_id}>
                        <td>{x.elem_id}</td>
                        <td>{x.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <Empty>없음</Empty>
              )}
            </Card>
          </div>
          {vHistory.data && vHistory.data.length > 1 && (
            <Card title="검증 이력">
              <table className="table compact">
                <thead>
                  <tr>
                    <th className="num">시각</th>
                    <th>판정</th>
                    <th>ESL 결과</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {vHistory.data.map((h) => (
                    <tr key={h.id} className={h.id === v.id ? "hl" : undefined}>
                      <td className="num">{dt(h.created_at)}</td>
                      <td>{h.verdict}</td>
                      <td className="mono small">{h.esl_run_id}</td>
                      <td>{h.stale ? <span className="muted">이전 입력</span> : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </>
      )}
    </>
  );
  if (pastVal)
    return (
      <PastFrame title="⑤ 검증" review={review.data} error={val.error ?? review.error} currentHref={`/p/${c.project_id}/c/${c.id}/stage/5`}>
        {content}
      </PastFrame>
    );
  return (
    <StageFrame
      title="⑤ 검증"
      status={c.stage_status?.["5"]}
      error={act.error ?? run.error ?? val.error}
      onJobDone={() => void reload()}
      primary={{
        label: "검증 실행",
        onClick: () => act.run(() => submitJob(c, "VALIDATE", { esl_run_id: runId })),
        disabledReason: blockReason(allowed, c, 5, prereq),
        busy: act.busy,
      }}
    >
      {content}
    </StageFrame>
  );
}
