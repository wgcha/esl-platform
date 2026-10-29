// 비드 DOE ⑤ 순위표(esl_bead_doe.md §11·§12.2, BD-D-6): 순위·안·score·개선율·최악 ESL·umax·εmax·변수 값·경고 수,
// 순위 밖(스킵·실패) 안은 상태 배지로 아래에. 1920 폭에서는 변수 열을 접고 행 펼치기로 값을 본다(가로 스크롤 없음).
// v0.10.0 §11.4: ESL별 개선 지표 열 [전 씬 개선 ✓/✗][최소 개선율][개선/악화 씬][기하평균 개선율][Pareto ●], 열 머리 클릭 정렬(기본 score),
// ⓘ 지표 정의. 최악 절대 max(score)만으로는 한 씬의 문제가 다른 씬으로 옮겨가는 상황을 못 보기 때문.
import { Fragment, useState } from "react";
import { METRIC_DEFS, STATUS_NAME, isSkipped, pctText, sortRanking, type RankSortKey } from "../api/doe";
import type { DoeParam, DoeResultOut, EntryOut } from "../api/types";
import { entryKey } from "./ModeSelect";
import { shortName, valuesText } from "./DoeThumbGrid";
import { Empty } from "./ui";

export function DoeRanking({ result, params, entries, selected, onSelect, varNames }: {
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
  const cols = 14 + varNames.length;
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
    <div className="doe-metric-bar small">
      <span className="muted">정렬: {sortKey === "score" ? "score(최악 ESL 절대값)" : METRIC_DEFS.find((d) => d.key === sortKey)?.label}</span>
      <details className="doe-metric-help">
        <summary aria-label="지표 정의">ⓘ 지표 정의</summary>
        <ul data-testid="metric-defs">
          <li>score: max(C_안) / max(C_베이스라인) — 최악 ESL 절대 컴플라이언스(작을수록 좋음)</li>
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
            {sortTh("score", "score", "max_i C / C_ref(베이스라인 최악) — 작을수록 좋음")}
            <th className="num">개선율</th>
            <th>최악 ESL</th>
            <th className="num" title="최악 ESL 기준(전 ESL 최대는 툴팁)">umax</th>
            <th className="num" title="최악 ESL 기준 최대 등가 변형률(선형)">εmax</th>
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
            <td className="num mono">{b.score.toFixed(2)}</td>
            <td className="num">기준</td>
            <td className="small muted">공칭</td>
            <td className="num mono">{b.umax.toFixed(2)} mm</td>
            <td className="num mono">{(b.epsmax * 100).toFixed(2)} %</td>
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
              <span className="badge info">베이스라인</span>
            </td>
            <td className="doe-expand-col" />
          </tr>
          {rows.map((r) => (
            <Fragment key={r.id}>
              <tr className={`pickable${selected === r.id ? " hl" : ""}`} onClick={() => onSelect(r.id)} data-testid={`rank-${r.id}`}>
                <td className="num">{r.rank}</td>
                <td className="mono">{r.id}</td>
                <td className="num mono">{r.score.toFixed(2)}</td>
                <td className={`num ${r.improvement > 0 ? "ok-text" : "error-text"}`}>
                  {pctText(r.improvement)}
                  {r.noise && (
                    <span className="badge neutral" title={`③ 메시 잡음 바닥 ${pctText(result.noise_floor ?? null, 1)} 이내`}>
                      잡음 이내
                    </span>
                  )}
                </td>
                <td className="small">{esl(r.worst_entry_id)}</td>
                <td className="num mono" title={`전 ESL 최대 ${r.umax_all.toFixed(2)} mm`}>
                  {r.umax.toFixed(2)} mm
                </td>
                <td className="num mono" title={`전 ESL 최대 ${(r.epsmax_all * 100).toFixed(2)} %`}>
                  {(r.epsmax * 100).toFixed(2)} %
                </td>
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
                  {r.warnings_n > 0 && (
                    <span className="badge warn" title="안 경고(반력 잔차 등) — 보고서에 상세">
                      ⚠ {r.warnings_n}
                    </span>
                  )}
                </td>
                <td className="doe-expand-col">
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
              <td className="num muted">–</td>
              <td className="num muted">–</td>
              <td />
              <td />
              <td />
              <td />
              <td />
              <td />
              <td />
              <td />
              {varNames.map((n) => (
                <td key={n} className="num mono doe-vcol muted">
                  {x.values[n] ?? "–"}
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
