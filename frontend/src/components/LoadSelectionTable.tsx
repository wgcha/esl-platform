// 하중 선정 표(esl_opt_run.md §7.4·§10.4): 후보 전체 행 — 상태·라벨·씬·C⁰·umax·모드·비고(병합 대상·MAC·반대 방향·군집).
import type { LoadSelection, LoadSelectionRow } from "../api/types";
import { MODE_LABEL, NORM_NAME, ROW_STATUS_LABEL, SELECTED_STATUS, STRATEGY_NAME, sci } from "../api/opt";
import { Badge } from "./ui";

export function selectionSummary(s: LoadSelection): string {
  const n = (st: LoadSelectionRow["status"]) => s.rows.filter((r) => r.status === st).length;
  const norm = s.objective_norm === "abs" ? `목표 절대(C_ref ${sci(s.C_ref)})` : "목표 상대(C/C⁰)";
  let tail = "";
  if (s.strategy === "A") tail = `병합 ${n("merged")}, ${s.clusters.length ? `군집 ${s.clusters.length}` : "군집 없음"}`;
  else if (s.strategy === "B") tail = s.excluded_modes.length ? `제외 모드 ${s.excluded_modes.map((m) => MODE_LABEL[m]).join("·")}` : "세 모드 모두";
  else tail = `군집 ${s.clusters.length}${s.k != null ? ` (k ${s.k})` : ""}`;
  return `전략 ${STRATEGY_NAME[s.strategy]} · ${norm} · ESL ${s.n_selected_esl} → 케이스 ${s.n_cases} (${tail})`;
}

function note(r: LoadSelectionRow, byId: Map<string, LoadSelectionRow>): string {
  if (r.status === "merged") {
    const t = r.merged_into ? byId.get(r.merged_into) : undefined;
    const parts = [r.mac_to_target != null ? `MAC ${r.mac_to_target.toFixed(2)}` : null, r.sign === -1 ? "반대 방향" : null].filter(Boolean);
    return `→ ${t?.label ?? r.merged_into ?? "?"}${parts.length ? ` (${parts.join(", ")})` : ""}`;
  }
  if (r.status === "cluster_rep") return `군집 ${r.cluster ?? "?"} 대표`;
  if (r.status === "clustered") {
    const rep = [...byId.values()].find((x) => x.cluster === r.cluster && x.status === "cluster_rep");
    return `군집 ${r.cluster ?? "?"}${rep?.label ? ` → ${rep.label}` : ""}`;
  }
  if (r.status === "mode_rep") return `${r.mode ? MODE_LABEL[r.mode] : "?"} 최악`;
  return "";
}

export function LoadSelectionTable({ sel }: { sel: LoadSelection }) {
  const byId = new Map(sel.rows.map((r) => [r.entry_id, r]));
  return (
    <div className="table-wrap scroll">
      <table className="table compact" aria-label="하중 선정">
        <thead>
          <tr>
            <th>상태</th>
            <th>씬</th>
            <th className="num">C⁰</th>
            {sel.objective_norm === "rel" && <th className="num">POS</th>}
            <th className="num">umax</th>
            <th>모드</th>
            <th>비고</th>
          </tr>
        </thead>
        <tbody>
          {sel.rows.map((r) => {
            const on = SELECTED_STATUS.includes(r.status);
            return (
              <tr key={r.entry_id} className={on ? undefined : "dim-row"} data-status={r.status}>
                <td>
                  {on ? <Badge kind="ok">{ROW_STATUS_LABEL[r.status]}</Badge> : <span className="badge neutral">{ROW_STATUS_LABEL[r.status]}</span>} {r.label && <b className="mono">{r.label}</b>}
                </td>
                <td>{r.scene}</td>
                <td className="num mono">{sci(r.C0)}</td>
                {sel.objective_norm === "rel" && <td className="num mono">{on ? sci(r.pos) : "–"}</td>}
                <td className="num">{r.umax.toFixed(1)} mm</td>
                <td>{r.mode ? MODE_LABEL[r.mode] : <span className="muted">분류 불가</span>}</td>
                <td className="small">{note(r, byId)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="small muted">
        목표 {NORM_NAME[sel.objective_norm]}: {sel.objective_norm === "abs" ? "모든 케이스를 같은 C_ref 로 나눔(큰 하중 비중 유지)" : "케이스마다 자기 C⁰ 로 나눔"} · 자료 {sel.sources_ref}
      </div>
    </div>
  );
}
