// v0.15.0 ③ 비드 목록·도구(esl_bead_select.md §11.1): 비드마다 이름·단별 바닥 요소 수·공칭 D·[묶기], 사면(자동+편집)·W(최소–최대)·블렌딩, ⚠ 경고 배지(툴팁).
// 지금 고치는 비드만 펼친다(1920 에서도 세로로 짧게). 숫자(D·W·사면·경고)는 마지막 [사면·경계 자동](서버 derive) 결과.
import { warnText } from "../api/doe";
import type { DoeBeadDerived, DoeSettingsOut } from "../api/types";
import { counts } from "../view3d/select/layers";
import type { BeadSelectCtrl } from "./BeadSelectCard";

const FIXED_SRC: Record<string, string> = { scan: "fixed-scan", user: "사용자 칠함", "scan+user": "fixed-scan + 사용자", none: "없음" };
const f1 = (v: number | null | undefined) => (v == null ? "–" : v.toFixed(1));

export function BeadList({ ctrl, editable, st }: { ctrl: BeadSelectCtrl; editable: boolean; st: DoeSettingsOut | null }) {
  const s = ctrl.state;
  const d = ctrl.derive;
  void st;
  if (!s) return <div className="small muted">{ctrl.error ?? "불러오는 중…"}</div>;
  const der = (id: string): DoeBeadDerived | null => d?.beads.find((x) => x.id === id) ?? null;
  const ro = !editable;
  return (
    <div className="bs-list">
      {s.beads.length === 0 && <div className="small muted">비드가 없습니다 — [+ 비드] 후 3D 에서 바닥을 클릭하세요.</div>}
      {s.beads.map((b, bi) => {
        const c = counts(s, bi);
        const x = der(b.id);
        const warns = x?.warnings ?? [];
        const on = bi === ctrl.active;
        const linkOf = (k: number) => b.links.find((g) => g.includes(k));
        return (
          <section key={b.id} className={`bs-bead${on ? " on" : ""}`} data-testid={`bead-${b.id}`} aria-current={on || undefined}>
            <header className="bs-bead-head" onClick={() => !on && ctrl.setActive(bi)}>
              <span className="mono small">{b.id.toUpperCase()}</span>
              <input className="bs-name" aria-label={`${b.id.toUpperCase()} 이름`} value={b.name} maxLength={32} disabled={ro} onChange={(e) => ctrl.rename(bi, e.target.value)} onFocus={() => !on && ctrl.setActive(bi)} />
              {warns.length > 0 && (
                <span className="badge warn" title={warns.map((w) => warnText(w)).join("\n")} data-testid={`bead-warn-${b.id}`}>
                  ⚠{warns.length}
                </span>
              )}
              {!on && <span className="small muted">바닥 {c.tiers.reduce((a, v) => a + v, 0).toLocaleString()} · 단 {b.nTiers}</span>}
            </header>
            {on && (
              <div className="bs-bead-body small">
                {c.tiers.map((n, i) => {
                  const k = i + 1;
                  const t = x?.tiers.find((y) => y.k === k);
                  const g = linkOf(k);
                  return (
                    <div key={k} className="bs-row">
                      <span>
                        단{k} 바닥 <b className="mono">{n.toLocaleString()}</b>
                        {t && <span className="mono"> · D {f1(t.D_nom)}</span>}
                        {g && <span className="muted"> · 묶음 {g.map((v) => `D${v}`).join("+")}</span>}
                        {n === 0 && <span className="error-text"> · 비었음</span>}
                      </span>
                      {k > 1 && (
                        <button type="button" className="btn small ghost" disabled={ro} onClick={() => ctrl.link(bi, k - 1, k)} title={`단 ${k - 1}·${k} 깊이를 같은 값으로 묶기/풀기`}>
                          {g && g.includes(k - 1) ? "묶음 풀기" : "묶기"}
                        </button>
                      )}
                    </div>
                  );
                })}
                <div className="bs-row">
                  <span>
                    사면 <b className="mono">{(x?.slope.n_elems ?? c.slopeAdd).toLocaleString()}</b>
                    <span className="muted">
                      {" "}
                      ({x ? `자동 ${x.slope.suggested_n.toLocaleString()}` : "자동 계산 전"}
                      {c.slopeAdd || c.slopeRemove ? ` · 편집 +${c.slopeAdd}/−${c.slopeRemove}` : ""})
                    </span>
                  </span>
                </div>
                <div className="bs-row">
                  <span>
                    W <b className="mono">{f1(x?.W_nom)}</b> <span className="muted mono">({f1(x?.W_min)}–{f1(x?.W_max)})</span> · 블렌딩 {b.blend === "auto" ? "auto" : "직접"} <span className="mono">{x ? `${f1(x.blend_mm)} mm` : ""}</span>
                    {x?.blend_clipped && <span className="badge warn" title="체결부 앞에서 줄임">잘림</span>}
                  </span>
                </div>
                {warns.length > 0 && (
                  <ul className="reasons warn-text">
                    {warns.map((w, i) => (
                      <li key={i}>{warnText(w)}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </section>
        );
      })}
      <div className="inline-actions bs-list-actions">
        <button type="button" className="btn small" disabled={ro || s.beads.length >= ctrl.maxBeads} onClick={ctrl.addBead}>
          + 비드
        </button>
        <button type="button" className="btn small" disabled={ro || !s.beads.length || (s.beads[ctrl.active]?.nTiers ?? 0) >= ctrl.maxTiers} onClick={ctrl.addTier} title="다단 비드: 다음 단 바닥을 고릅니다">
          + 단
        </button>
        <button type="button" className={`btn small ghost toggle${ctrl.layer?.kind === "fixed" ? " on" : ""}`} disabled={ro} onClick={() => ctrl.setLayer({ kind: "fixed" })} title="체결부(고정 노드)를 직접 칠합니다">
          고정 칠하기
        </button>
      </div>
      {d && (
        <div className="small muted" data-testid="bs-fixed">
          고정: {FIXED_SRC[d.fixed.source] ?? d.fixed.source} · 스캔 {d.fixed.scan_n} · 사용자 {d.fixed.user_n} 노드
        </div>
      )}
      {ctrl.dirty && <div className="small warn-text" data-testid="bs-dirty">저장 안 한 변경이 있습니다 — [선택 저장]</div>}
    </div>
  );
}
