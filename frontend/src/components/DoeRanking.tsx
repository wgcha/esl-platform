// 비드 DOE ⑤ 순위표(esl_bead_doe.md §11·§12.2, BD-D-6): 순위·안·score·개선율·최악 ESL·umax·εmax·변수 값·경고 수,
// 순위 밖(스킵·실패) 안은 상태 배지로 아래에. 1920 폭에서는 변수 열을 접고 행 펼치기로 값을 본다(가로 스크롤 없음).
// v0.10.0 §11.4: ESL별 개선 지표 열 [전 씬 개선 ✓/✗][최소 개선율][개선/악화 씬][기하평균 개선율][Pareto ●], 열 머리 클릭 정렬(기본 score),
// ⓘ 지표 정의. 최악 절대 max(score)만으로는 한 씬의 문제가 다른 씬으로 옮겨가는 상황을 못 보기 때문.
// v0.14.0 ④ 형상 직접 비교: 변수 열 대신 '이름' 열(행 머리, shape.name), 베이스라인 = 기준 형상, 값 펼치기 없음.
// v0.16.1 경고 안(SR-D-11): 순위 그대로 + 상태 칸 ⚠ + 1위가 경고 안이면 "경고 없는 최상위" 1줄(Q1 = A).
// v0.16.0 이름 옆 짧은 '메시 방식' 배지(세분화·재메시·메시 입력 — CAD 는 생략), 툴팁 = 충실도·시도·수렴 δ.
import { Fragment, useState } from "react";
import { METRIC_DEFS, RANK_WARN_NAME, STATUS_NAME, isSkipped, pctText, sortRanking, type RankSortKey } from "../api/doe";
import type { DoeParam, DoeResultOut, EntryOut } from "../api/types";
import { entryKey } from "./ModeSelect";
import { shortName, valuesText } from "./DoeThumbGrid";
import { Empty } from "./ui";
import { SM_CODE_TEXT, isCrossMesh, isLinResult, rankThresholds, smFallbackText, smLinRangeText } from "../api/doe";
import { ShapeNameCell } from "./DoeInputs";

export function DoeRanking({ result, params, entries, selected, onSelect, varNames, rankCfg }: {
  /** settings.rank — 결과 스냅샷에 임계값이 없을 때만 쓰는 대체 출처 */
  rankCfg?: { rank?: { lin_valid?: number | null; imbalance_warn?: number | null } | null } | null;
  result: DoeResultOut;
  params: DoeParam[];
  entries: EntryOut[];
  selected: string | null;
  onSelect: (id: string) => void;
  /** 표에 보일 변수(포함 변수) */
  varNames: string[];
}) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const byId = new Map(entries.map((e) => [e.id, e]));
  const esl = (id: string) => (byId.get(id) ? entryKey(byId.get(id)!) : id);
  const toggle = (id: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const [sortKey, setSortKey] = useState<RankSortKey>("score");
  /** v0.20.0 새 지표(lin): 주 열 교체 · umax·εmax 는 보조 열(토글)로 이동 */
  const lin = isLinResult(result);
  /** 결정 A: 다른 메시 비교 — 주 열 = 재풀이 C, umax = 강체 제거 값(있으면), 지표 보조 열 없음 */
  const cross = !lin && isCrossMesh(result);
  /** SM-11: 새 스냅샷의 주 열 = result.rank.metric_effective(기본 solve = 재풀이 C). 1차 지표 값이 있으면 보조 열로(값 유무만 봄) */
  const solveNew = !lin && (result.rank?.metric_effective ?? result.metric_effective) === "solve";
  const auxLin = solveNew && result.ranking.some((r) => r.score_lin != null);
  const um = (r: { umax: number; umax_def?: number | null }) => (solveNew && r.umax_def != null ? r.umax_def : r.umax);
  const [aux, setAux] = useState(false);
  const th = rankThresholds(result, rankCfg);
  const fade = (r: { imbalance_max?: number | null }) => (lin || auxLin) && th.imbalanceWarn != null && (r.imbalance_max ?? 0) > th.imbalanceWarn;
  const rhoOut = (r: { rho_min?: number | null; rho_max?: number | null }) =>
    th.linValid != null && r.rho_min != null && (Math.abs(r.rho_min - 1) > th.linValid || Math.abs((r.rho_max ?? 1) - 1) > th.linValid);
  /** ④ 형상 비교(이름 열) */
  const named = result.scenario === "compare" || result.ranking.some((r) => !!r.shape);
  const cols = 14 + varNames.length + (named ? 1 : 0) + (lin ? (aux ? 3 : -2) : auxLin && aux ? 3 : 0);
  const b = result.baseline;
  if (!result.ranking.length && !(result.excluded ?? []).length) return <Empty>순위가 없습니다</Empty>;
  const rows = sortRanking(result.ranking, sortKey);
  const def = (k: string) => METRIC_DEFS.find((d) => d.key === k)?.text;
  /** 정렬 가능한 열 머리(버튼 — 현재 정렬 열은 aria-sort) */
  const sortTh = (k: RankSortKey, label: string, title?: string) => (
    <th className="num" aria-sort={sortKey === k ? "ascending" : "none"} title={title}>
      <button type="button" className="th-sort" onClick={() => setSortKey(k)} aria-label={`${label} 기준 정렬`}>
        {label}
      </button>
    </th>
  );
  return (
    <>
    {(() => {
      // Q1 = A: 1위가 경고 안이면 순위는 그대로 두고 "경고 없는 최상위" 1줄
      const top = result.ranking.find((r) => r.rank === 1) ?? result.ranking[0];
      if (!top?.warn?.length) return null;
      const clean = result.summary?.best_clean ?? result.ranking.filter((r) => !r.warn?.length).sort((a, c) => a.rank - c.rank)[0]?.id ?? null;
      return (
        <div className="small warn-text" data-testid="best-clean">
          ⚠ 1위가 경고 안입니다({top.warn.map((w) => RANK_WARN_NAME[w] ?? w).join(" · ")}) — 경고 없는 최상위: {clean ? <b className="mono">{clean}</b> : "없음"}
        </div>
      );
    })()}
    <div className="doe-metric-bar small">
      <span className="muted">정렬: {sortKey === "score" ? (lin ? "score(1차 강성 지표)" : cross ? "score(재풀이 C — 다른 메시 비교)" : solveNew ? "score(재풀이 C)" : "score(최악 ESL 절대값)") : METRIC_DEFS.find((d) => d.key === sortKey)?.label}</span>
      {(lin || auxLin) && (
        <label className="check" title={lin ? "재풀이 C 비·불평형·ρ·강체 제거 umax·εmax — 순위에 쓰지 않는 값" : "1차 강성 지표 비·불평형·ρ — 순위에 쓰지 않는 값"}>
          <input type="checkbox" data-testid="rank-aux-toggle" aria-label="보조 열 보기" checked={aux} onChange={(e) => setAux(e.target.checked)} /> 보조 열 보기
        </label>
      )}
      <details className="doe-metric-help">
        <summary aria-label="지표 정의">ⓘ 지표 정의</summary>
        <ul data-testid="metric-defs">
          <li>
            {lin
              ? `score: max(C_안) / max(C_베이스라인) — C = 재풀이 없는 1차 강성 지표(${result.lin_form === "taylor" ? "C_ref(2−ρ)" : "C_ref/ρ"}, ρ = 변형에너지 비). 작을수록 좋음`
              : cross
                ? "score: max(C_안) / max(C_기준) — C = 형상마다 work 하중을 옮겨 재풀이한 컴플라이언스(다른 메시 비교 — 1차 강성 지표 미적용, 정밀도 낮음)"
                : solveNew
                  ? "score: max(C_안) / max(C_베이스라인) — C = 안마다 재풀이한 컴플라이언스(기본, 작을수록 좋음). 1차 강성 지표(ritz·taylor)는 보조 열"
                  : "score: max(C_안) / max(C_베이스라인) — 최악 ESL 절대 컴플라이언스(작을수록 좋음)"}
          </li>
          {auxLin && <li>강성 지표 비: 재풀이 없는 1차 지표({result.lin_form === "taylor" ? "C_ref(2−ρ)" : "C_ref/ρ"}, ρ = 변형에너지 비) — 큰 형상 변화에서 개선을 과장할 수 있어 순위에 쓰지 않음</li>}
          {lin && <li>재풀이 C 비: 같은 식에 안마다 해석한 컴플라이언스(고정 하중이라 불평형·무른 모드의 영향을 받음)</li>}
          {lin && <li>umax·εmax: 순위에 쓰지 않는 해석값 — umax 는 강체 6자유도를 뺀 값(불평형이 만든 굽힘은 남음)</li>}
          {METRIC_DEFS.map((d) => (
            <li key={d.key}>
              {d.label}: {d.text}
            </li>
          ))}
          {result.ratio_tol != null && <li>허용치 {result.ratio_tol.toExponential(1)}(③ 은 메시 잡음 바닥 반영)</li>}
        </ul>
      </details>
    </div>
    <div className="table-wrap scroll doe-rank-wrap">
      <table className="table compact doe-rank" aria-label="순위표">
        <thead>
          <tr>
            <th className="num">순위</th>
            <th>안</th>
            {named && <th className="doe-name-col">이름</th>}
            {sortTh("score", lin ? "강성 지표" : solveNew ? "재풀이 C" : "score", lin ? "max_i C_lin / M_ref(베이스라인 최악) — 재풀이 없는 1차 섭동 지표, 작을수록 좋음" : cross ? `max_i C / C_ref — 다른 메시 비교: ${SM_CODE_TEXT.SM_CROSS_MESH}` : solveNew ? "max_i C / C_ref — 안마다 재풀이한 컴플라이언스(기본), 작을수록 좋음" : "max_i C / C_ref(베이스라인 최악) — 작을수록 좋음")}
            <th className="num">개선율</th>
            <th>최악 ESL</th>
            {!lin && <th className="num" title={solveNew ? "최악 ESL 기준, 강체 6자유도 제거" : "최악 ESL 기준(전 ESL 최대는 툴팁)"}>umax</th>}
            {!lin && <th className="num" title="최악 ESL 기준 최대 등가 변형률(선형)">εmax</th>}
            {lin && aux && <th className="num" title="안마다 재풀이한 C 로 같은 식(최악 ESL 비) — 보조">재풀이 C 비</th>}
            {auxLin && aux && <th className="num" title="재풀이 없는 1차 강성 지표로 같은 식(최악 ESL 비) — 보조">강성 지표 비</th>}
            {(lin || auxLin) && aux && <th className="num" title="max_i |F − K·u| / Σ|F| — 클수록 재풀이 값이 무른 모드에 오염">불평형</th>}
            {(lin || auxLin) && aux && <th className="num" title="변형에너지 비 ρ 범위(1 에서 멀수록 1차 근사 밖)">ρ</th>}
            {lin && aux && <th className="num" title="최악 ESL, 강체 6자유도 제거 · 해석값(순위와 무관)">umax(강체 제거)</th>}
            {lin && aux && <th className="num" title="최악 ESL 기준 최대 등가 변형률(선형) — 순위와 무관">εmax</th>}
            <th title={def("all_improved")}>전 씬 개선</th>
            {sortTh("min_improvement", "최소 개선율", def("min_improvement"))}
            {sortTh("n_worsened", "개선/악화", def("n_worsened"))}
            {sortTh("geo_mean_improvement", "기하평균", def("geo_mean_improvement"))}
            {sortTh("pareto", "Pareto", def("pareto"))}
            {varNames.map((n) => (
              <th key={n} className="num doe-vcol">
                {shortName(params, n)}
              </th>
            ))}
            <th>상태 · 경고</th>
            <th className="doe-expand-col" />
          </tr>
        </thead>
        <tbody>
          <tr className="doe-base-row">
            <td className="num">–</td>
            <td className="mono">d000</td>
            {named && (
              <th scope="row" className="doe-name-col" title={b.shape?.file_name ?? undefined}>
                <ShapeNameCell name={b.shape?.name ?? "기준"} shape={b.shape} testId="rank-method-d000" />
              </th>
            )}
            <td className="num mono">{b.score.toFixed(2)}</td>
            <td className="num">기준</td>
            <td className="small muted">{named ? "기준 형상" : "공칭"}</td>
            {!lin && <td className="num mono">{um(b).toFixed(2)} mm</td>}
            {!lin && <td className="num mono">{(b.epsmax * 100).toFixed(2)} %</td>}
            {(lin || auxLin) && aux && <td className="num mono">1.00</td>}
            {(lin || auxLin) && aux && <td className="num muted">–</td>}
            {(lin || auxLin) && aux && <td className="num muted">–</td>}
            {lin && aux && <td className="num mono muted">{b.umax_def != null ? `${b.umax_def.toFixed(2)} mm` : "–"}</td>}
            {lin && aux && <td className="num mono muted">{(b.epsmax * 100).toFixed(2)} %</td>}
            <td />
            <td className="num muted">기준</td>
            <td />
            <td />
            <td />
            {varNames.map((n) => (
              <td key={n} className="num mono doe-vcol">
                {params.find((p) => p.name === n)?.nominal ?? "–"}
              </td>
            ))}
            <td>
              <span className="badge info">{named ? "기준" : "베이스라인"}</span>
            </td>
            <td className="doe-expand-col" />
          </tr>
          {rows.map((r) => (
            <Fragment key={r.id}>
              <tr className={`pickable${selected === r.id ? " hl" : ""}${fade(r) ? " sm-faded" : ""}`} style={fade(r) ? { opacity: 0.8 } : undefined} onClick={() => onSelect(r.id)} data-testid={`rank-${r.id}`}>
                <td className="num">{r.rank}</td>
                <td className="mono">{r.id}</td>
                {named && (
                  <th scope="row" className="doe-name-col" title={r.shape?.file_name ?? undefined}>
                    <ShapeNameCell name={r.shape?.name ?? "–"} shape={r.shape} testId={`rank-method-${r.id}`} />
                  </th>
                )}
                <td className="num mono">
                  {r.score.toFixed(2)}
                  {lin && r.basis === "solve" && (
                    <span className="badge neutral small" data-testid={`basis-solve-${r.id}`} title={smFallbackText(th.linValid)}>
                      재풀이
                    </span>
                  )}
                </td>
                <td className={`num ${r.improvement > 0 ? "ok-text" : "error-text"}`}>
                  {pctText(r.improvement)}
                  {r.noise && (
                    <span className="badge neutral" title={`③ 메시 잡음 바닥 ${pctText(result.noise_floor ?? null, 1)} 이내`}>
                      잡음 이내
                    </span>
                  )}
                </td>
                <td className="small">{esl(r.worst_entry_id)}</td>
                {!lin && (
                  <td className="num mono" title={`전 ESL 최대 ${r.umax_all.toFixed(2)} mm`}>
                    {um(r).toFixed(2)} mm
                  </td>
                )}
                {!lin && (
                  <td className="num mono" title={`전 ESL 최대 ${(r.epsmax_all * 100).toFixed(2)} %`}>
                    {(r.epsmax * 100).toFixed(2)} %
                  </td>
                )}
                {lin && aux && <td className="num mono" data-testid={`aux-solve-${r.id}`}>{r.score_solve != null ? r.score_solve.toFixed(2) : "–"}</td>}
                {auxLin && aux && <td className="num mono" data-testid={`aux-lin-${r.id}`}>{r.score_lin != null ? r.score_lin.toFixed(2) : "–"}</td>}
                {(lin || auxLin) && aux && (
                  <td className={`num mono ${fade(r) ? "warn-text" : ""}`} data-testid={`aux-imb-${r.id}`} title={fade(r) ? SM_CODE_TEXT.SM_IMBALANCE : undefined}>
                    {r.imbalance_max != null ? `${(r.imbalance_max * 100).toFixed(1)} %` : "–"}
                    {fade(r) ? " ⚠" : ""}
                  </td>
                )}
                {(lin || auxLin) && aux && (
                  <td className="num mono" data-testid={`aux-rho-${r.id}`} title={rhoOut(r) ? smLinRangeText(th.linValid) : undefined}>
                    {r.rho_min != null && r.rho_max != null ? `${r.rho_min.toFixed(2)}~${r.rho_max.toFixed(2)}` : "–"}
                    {rhoOut(r) ? " ⚠" : ""}
                  </td>
                )}
                {lin && aux && <td className="num mono muted" title="강체 6자유도 제거 · 해석값(순위와 무관)">{r.umax_def != null ? `${r.umax_def.toFixed(2)} mm` : "–"}</td>}
                {lin && aux && <td className="num mono muted">{(r.epsmax * 100).toFixed(2)} %</td>}
                <td data-testid={`allimp-${r.id}`}>
                  {r.all_improved == null ? (
                    <span className="muted">–</span>
                  ) : r.all_improved ? (
                    <span className="badge ok" title="모든 ESL 에서 개선">✓</span>
                  ) : (
                    <span className="badge bad" title="악화(또는 변화 없음)된 ESL 이 있음 — ESL별 개선율 표 참고">✗</span>
                  )}
                </td>
                <td className={`num ${(r.min_improvement ?? 0) > 0 ? "ok-text" : r.min_improvement == null ? "" : "error-text"}`}>
                  {pctText(r.min_improvement, 1)}
                </td>
                <td className="num mono" title={r.n_unchanged ? `변화 없음 ${r.n_unchanged}` : undefined}>
                  {r.n_improved == null ? "–" : `${r.n_improved} / ${r.n_worsened ?? 0}`}
                </td>
                <td className="num">{pctText(r.geo_mean_improvement, 1)}</td>
                <td className="num" data-testid={`pareto-${r.id}`}>
                  {r.pareto ? <span title="Pareto(다른 안에 모든 ESL 에서 지배당하지 않음)">●</span> : ""}
                </td>
                {varNames.map((n) => (
                  <td key={n} className="num mono doe-vcol">
                    {r.values[n] ?? "–"}
                  </td>
                ))}
                <td>
                  <span className="badge ok">OK</span>
                  {!!r.warn?.length && (
                    <span className="badge warn" title={r.warn.map((w) => RANK_WARN_NAME[w] ?? w).join(" · ")} data-testid={`rank-warn-${r.id}`}>
                      ⚠
                    </span>
                  )}
                  {r.warnings_n > 0 && (
                    <span className="badge warn" title="안 경고(반력 잔차 등) — 보고서에 상세">
                      ⚠ {r.warnings_n}
                    </span>
                  )}
                </td>
                <td className="doe-expand-col">
                  {!named && (
                  <button
                    type="button"
                    className="btn small ghost"
                    aria-expanded={open.has(r.id)}
                    aria-label={`${r.id} 값 펼치기`}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggle(r.id);
                    }}
                  >
                    {open.has(r.id) ? "▾" : "▸"}
                  </button>
                  )}
                </td>
              </tr>
              {open.has(r.id) && (
                <tr className="doe-values-row">
                  <td colSpan={cols} className="small mono">
                    {valuesText(params, r.values)}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
          {(result.excluded ?? []).map((x) => (
            <tr key={x.id} className="doe-excluded" data-testid={`excluded-${x.id}`}>
              <td className="num">–</td>
              <td className="mono">{x.id}</td>
              {named && (
                <th scope="row" className="doe-name-col" title={x.shape?.file_name ?? undefined}>
                  <ShapeNameCell name={x.shape?.name ?? "–"} shape={x.shape} />
                </th>
              )}
              <td className="num muted">–</td>
              <td className="num muted">–</td>
              {Array.from({ length: lin ? (aux ? 11 : 6) : 8 }, (_, k) => <td key={k} />)}
              {varNames.map((n) => (
                <td key={n} className="num mono doe-vcol muted">
                  {x.values?.[n] ?? "–"}
                </td>
              ))}
              <td>
                <span className={`badge ${isSkipped(x.status) ? "neutral" : "bad"}`} title={x.code ?? undefined}>
                  {isSkipped(x.status) ? "스킵" : "실패"} · {STATUS_NAME[x.status]}
                </span>
              </td>
              <td className="doe-expand-col" />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </>
  );
}
