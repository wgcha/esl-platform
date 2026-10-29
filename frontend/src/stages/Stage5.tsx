// ④ 검증(v0.10.0 재번호 — 옛 ⑤; 주 버튼 = 검증 실행 / 라이브러리에 등록, esl_menu_restructure.md §7.1)(v0.5.7, 계약 esl_disp_primary.md §9): 판정 = 변위 4지표. 위→아래:
//   판정 카드 → 변위 카드(컨투어·log 히스토그램·상위 노드·단면 차트) → 변형률 카드(참고, 판정 아님) → hotspot·제외 표 → 검증 이력.
import { useSearchParams } from "react-router-dom";
import { api } from "../api/endpoints";
import { history } from "../api/history";
import { PastFrame } from "../components/PastBadge";
import type { FieldSummary, StrainRef, ValidationOut } from "../api/types";
import { Badge, Card, Empty, Stat } from "../components/ui";
import { FieldOverlay } from "../components/FieldOverlay";
import { DispOverlay } from "../components/DispOverlay";
import { DispHistogram } from "../components/DispHistogram";
import { DispTopTable } from "../components/DispTopTable";
import { StatusBadge, statusOf, undeterminedText } from "../components/VerdictStatus";
import { SectionChart, useSectionCtl, type SectionCtl } from "../components/SectionChart";
import { ErrHistogram } from "../components/ErrHistogram";
import { ReportLink } from "../components/ReportLink";
import { LibraryRegister, REGISTER_LABEL, useRegistration } from "../components/LibraryRegister";
import { stepPath, stepState } from "../shell/StageStepper";
import { usePolling } from "../lib/usePolling";
import { dt, fmt, pct, pv, sci, spv } from "../lib/format";
import { StageFrame, type StageProps } from "./StageFrame";
import { blockReason, submitJob, useAction } from "./common";

/** 코어 validation fail_reasons 코드 → 설명 */
export const FAIL_REASON_LABEL: Record<string, string> = {
  DISP_RMS: "변위 RMS 오차가 기준 초과",
  DISP_MAX: "변위 최대 오차가 기준 초과",
  REACTION: "3-2-1 반력이 기준 초과(자기평형 아님)",
  DISP_NOISE: "변위 정밀도 잡음 바닥이 기준 초과",
  // 0.5.7 이전(LEGACY) 검증의 코드
  HOTSPOT_STRAIN: "hotspot 1위 ε_eq 오차가 기준 초과",
  NOISE_FLOOR: "변위 정밀도 잡음 바닥이 기준 초과",
  FIELD_MAX_ERR: "최대변형률 요소의 ESL 오차가 기준 초과",
  FIELD_P90_ERR: "전 요소 |오차| P90이 기준 초과",
};

const plasticOf = (r: StrainRef | null | undefined) => {
  if (!r) return null;
  if (r.plastic) return r.plastic;
  return r.n_plastic != null ? { n_plastic: r.n_plastic, frac_plastic: r.frac_plastic ?? 0, n_exceed_plastic: r.n_exceed_plastic ?? 0 } : null;
};

/** 변형률 참고 지표(계약 §3.4·§9): 판정 아님 — 값과 참고 기준만 보인다(빨강 톤 없음) */
function StrainCompare({ f, v }: { f: FieldSummary; v: ValidationOut }) {
  const mx = f.max;
  const cr = f.criteria;
  const p90 = f.abs_err_pct?.p90;
  const sr = v.strain_ref;
  const pl = plasticOf(sr);
  const hsMax = num(v.criteria.hotspot_strain_rel_err_max);
  return (
    <div className="stats" data-testid="strain-compare">
      {sr && (
        <>
          <Stat
            label="기준 초과 요소"
            value={`${sr.n_exceed.toLocaleString()} / ${f.n_elems.toLocaleString()}`}
            sub={`${(sr.frac_exceed * 100).toFixed(2)}%${sr.frac_exceed_valid != null ? ` · valid 대비 ${(sr.frac_exceed_valid * 100).toFixed(2)}%` : ""}`}
            hint="valid 요소 중 |오차| 가 compare.max_err_pct_max 를 넘는 요소 수 / 전체 요소 수"
          />
          <Stat label="|오차| P99" value={pv(sr.p99_err_pct)} sub="valid 요소" />
        </>
      )}
      <Stat label="최대 ε (Radioss)" value={fmt(mx?.eps_rad, 4)} sub={mx ? `요소 ${mx.elem_id}` : "상승 요소 없음"} hint="t* 에서 상승 중인 요소 중 최대" />
      <Stat label="같은 요소 ε (ESL)" value={fmt(mx?.eps_esl, 4)} sub={mx ? `ESL 전체 최대 ${fmt(mx.eps_esl_max, 4)} (요소 ${mx.eps_esl_max_elem_id})` : undefined} />
      <Stat label="최대변형률 오차" value={spv(mx?.err_pct)} sub={cr ? `참고 기준 ≤ ${cr.max_err_pct_max}%` : undefined} />
      <Stat label="|오차| P90" value={pv(p90)} sub={cr ? `참고 기준 ≤ ${cr.p90_err_max}%` : undefined} />
      <Stat label="hotspot 1위 오차" value={v.hotspots.length ? pct(v.hotspots[0].rel_err) : "–"} sub={hsMax !== undefined ? `참고 기준 ≤ ${pct(hsMax)}` : undefined} />
      {sr && sr.basis === "increment" ? (
        <Stat
          label="소성 영역 요소"
          value={`누적 ${(sr.n_plastic_cum ?? 0).toLocaleString()} / 이번 ${(sr.n_plastic_inc ?? 0).toLocaleString()}`}
          sub={`최대 누적 ${fmt(sr.cum_max, 4)} · 이번 ${fmt(sr.inc_max, 4)}`}
          hint="누적 씬: t* 프레임 소성 변형률 누적(이전 + 이번) > 0 / 이번 낙하 증분 > 0 인 요소"
        />
      ) : (
        sr && (
          <Stat
            label="소성 영역 요소"
            value={pl ? pl.n_plastic.toLocaleString() : "–"}
            sub={pl ? `${(pl.frac_plastic * 100).toFixed(2)}% · 기준 초과와 겹침 ${pl.n_exceed_plastic.toLocaleString()}` : "epsp 없음"}
            hint="t* 프레임에서 epsp > 0 인 요소"
          />
        )
      )}
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
        {f.hist.n_clipped ? ` (범위 밖 ${f.hist.n_clipped}개는 끝 막대)` : ""}. 점선 = ±P90 참고 기준.
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

/** 판정 Stat 한 칸: 값 > 기준이면 bad, 이하이면 ok. 값이 없으면 사유에 따라 "생략"/"–" */
function JudgeStat({ label, value, crit, skipped, hint }: { label: string; value: number | null | undefined; crit: number | undefined; skipped?: boolean; hint?: string }) {
  const has = value !== null && value !== undefined;
  const bad = has && (!Number.isFinite(value) || (crit !== undefined && value > crit));
  return (
    <Stat
      label={label}
      value={has ? sci(value) : skipped ? "생략" : "–"}
      sub={crit !== undefined ? `기준 ≤ ${sci(crit)}` : undefined}
      tone={has && crit !== undefined ? (bad ? "bad" : "ok") : undefined}
      hint={has ? hint : skipped ? "전체 재해석 생략(validation.full_solve)" : hint}
    />
  );
}

function SectionCard({ ctl }: { ctl: SectionCtl }) {
  return (
    <div className="subblock" data-testid="section-card">
      <h4 className="sub-title">단면선 — 변형 형상 겹치기</h4>
      <SectionChart ctl={ctl} />
    </div>
  );
}

export { STATUS_LABEL, StatusBadge, statusOf, undeterminedText } from "../components/VerdictStatus";

export function Stage5({ c, reload, allowed }: StageProps) {
  const [sp] = useSearchParams();
  const pastVal = sp.get("val"); // 과거 실행 읽기 전용(?val=)
  const runId = pastVal ? null : c.current_esl_run_id;
  const st5 = stepState(c, 4);
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
  // 단면 위치·축·추천은 변위 컨투어, 겹쳐보기, 단면 차트가 함께 쓴다
  const sectionOn = !!v && !!v.field && !filesGone;
  const ctl = useSectionCtl(v?.id ?? null, sectionOn);

  const prereq = !runId ? "③ ESL을 먼저 계산하세요" : run.data?.stale ? "③ ESL을 다시 계산하세요(입력이 바뀜)" : null;
  // §7.1 주 버튼 1개: 최신 검증 PASS(현재 기준) ∧ 미등록 → '라이브러리에 등록', 그 외 '검증 실행'
  const reg = useRegistration(c.project_id, pastVal ? null : v ?? null, allowed);
  const registerMode = !pastVal && reg.canRegister && st5?.state !== "running";
  const crit = v?.criteria ?? {};
  const status = v ? statusOf(v) : null;
  const skipped = !!v && v.undetermined_reason === "NO_FULL_SOLVE";
  const hsMax = num(crit.hotspot_strain_rel_err_max);

  const content = (
    <>
      {!v ? (
        <Empty>{pastVal ? "불러오는 중…" : runId ? "아직 검증하지 않았습니다" : "③ ESL을 먼저 계산하세요"}</Empty>
      ) : (
        <div className="wide2">
          <Card
            title="판정"
            right={
              <span className="inline-actions">
                <StatusBadge v={v} />
                {!pastVal && <ReportLink url={api.caseReportUrl(c.id)} dep={`${v.id}:${st5?.state}`} />}
                {!pastVal && <LibraryRegister projectId={c.project_id} reg={reg} />}
              </span>
            }
          >
            <div className="stats" data-testid="judge-stats">
              <JudgeStat label="변위 RMS (상대)" value={v.disp_rms_rel} crit={num(crit.disp_rms_rel_max)} skipped={skipped} />
              <JudgeStat label="변위 최대 오차 (상대)" value={v.disp_max_rel} crit={num(crit.disp_max_rel_max)} skipped={skipped} />
              <JudgeStat label="반력 (상대)" value={v.reaction_rel} crit={num(crit.reaction_rel_max)} skipped={skipped} />
              <JudgeStat label="변위 잡음 바닥" value={v.disp_noise_rel} crit={num(crit.disp_noise_rel_max)} hint="저장 정밀도가 만드는 노드 변위 잡음 δ ÷ U" />
            </div>
            {status === "UNDETERMINED" && (
              <div className="small" role="status" data-testid="undetermined-reason">
                {undeterminedText(v)}
              </div>
            )}
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

          <Card title="변위 비교 (전 노드)">
            {v.disp ? (
              <>
                <div className="small muted">ESL 재해석 변위와 Radioss 변위의 차이 — 계산·경계조건·저장 정밀도의 수치 일관성을 봅니다(물리적 차이가 아닙니다).</div>
                {!filesGone && <DispOverlay vid={v.id} disp={v.disp} sec={ctl.map} />}
                <div className="grid2 disp-grid">
                  <div className="subblock">
                    <h4 className="sub-title">변위 오차 분포 (log10 e/U)</h4>
                    <DispHistogram hist={v.disp.hist} rmsCrit={num(crit.disp_rms_rel_max)} maxCrit={num(crit.disp_max_rel_max)} />
                  </div>
                  <div className="subblock">
                    <h4 className="sub-title">변위 오차 상위 노드</h4>
                    <DispTopTable top={v.disp.top} />
                  </div>
                </div>
                {!filesGone && <SectionCard ctl={ctl} />}
              </>
            ) : (
              <>
                <div className="small muted" role="status" data-testid="disp-note">
                  {status === "LEGACY" ? "이전 판정 체계 결과 — 다시 검증하면 변위 분석이 나옵니다" : "전체 재해석이 없어 변위 비교를 표시할 수 없습니다"}
                </div>
                {sectionOn && <SectionCard ctl={ctl} />}
              </>
            )}
          </Card>

          <Card
            title={v.strain_ref?.basis === "increment" ? "변형률 (참고 — 판정 아님) (이번 낙하 증분 기준)" : "변형률 (참고 — 판정 아님)"}
            right={v.strain_ref?.exceeded ? <Badge kind="warn">참고 초과</Badge> : undefined}
          >
            {v.field && <StrainCompare f={v.field} v={v} />}
            {v.field && !filesGone ? (
              <div className="subblock">
                <h4 className="sub-title">겹쳐보기 — 요소 변형률 (PCA 평면)</h4>
                <FieldOverlay vid={v.id} hotspots={v.hotspots} summary={v.field} strainRef={v.strain_ref} sec={ctl.map} />
              </div>
            ) : pastVal ? null : (
              <div className="warn-box" role="status">
                전 요소 비교 자료가 없는 예전 검증입니다 — ④ 검증을 다시 실행하면 겹쳐보기를 볼 수 있습니다.
              </div>
            )}
            {v.field && !filesGone && (
              <div className="subblock">
                <h4 className="sub-title">오차 분포 (valid 요소)</h4>
                <ErrDistribution f={v.field} />
              </div>
            )}
          </Card>
          {v.field && !filesGone && <TopTable f={v.field} />}
          <div className="grid2">
            <Card title="hotspot ε_eq 오차">
              <div className="table-wrap scroll">
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
                        <tr key={h.elem_id} className={over ? "ref-row" : undefined}>
                          <td>{h.elem_id}</td>
                          <td className="num">{fmt(h.eps_rad, 4)}</td>
                          <td className="num">{fmt(h.eps_val, 4)}</td>
                          <td className="num">{pct(h.rel_err)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
            <Card title="제외 요소">
              {v.excluded.length ? (
                <div className="table-wrap scroll">
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
                </div>
              ) : (
                <Empty>없음</Empty>
              )}
            </Card>
          </div>
          {vHistory.data && vHistory.data.length > 1 && (
            <Card title="검증 이력">
              <div className="table-wrap scroll">
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
                        <td data-testid="hist-status">
                          <StatusBadge v={h} />
                        </td>
                        <td className="mono small">{h.esl_run_id}</td>
                        <td>{h.stale ? <span className="muted">이전 입력</span> : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>
      )}
    </>
  );
  if (pastVal)
    return (
      <PastFrame title="④ 검증" review={review.data} error={val.error ?? review.error} currentHref={stepPath(c.project_id, c.id, 4)}>
        {content}
      </PastFrame>
    );
  return (
    <StageFrame
      title="④ 검증"
      status={st5}
      error={act.error ?? reg.error ?? run.error ?? val.error}
      onJobDone={() => void reload()}
      primary={
        registerMode
          ? { label: REGISTER_LABEL, onClick: () => void reg.register(), disabledReason: reg.permission, busy: reg.busy }
          : {
              label: "검증 실행",
              onClick: () => act.run(() => submitJob(c, "VALIDATE", { esl_run_id: runId })),
              disabledReason: blockReason(allowed, c, 4, prereq),
              busy: act.busy,
            }
      }
    >
      {content}
    </StageFrame>
  );
}
