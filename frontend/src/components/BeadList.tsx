// v0.15.0 ③ 비드 목록·도구(esl_bead_select.md §11.1): 비드마다 이름·단별 바닥 요소 수·공칭 D·[묶기], 사면(자동+편집)·W(최소–최대)·블렌딩, ⚠ 경고 배지(툴팁).
// 지금 고치는 비드만 펼친다(1920 에서도 세로로 짧게). 숫자(D·W·사면·경고)는 마지막 [사면·경계 자동](서버 derive) 결과.
import { warnText } from "../api/doe";
import type { DoeBeadDerived, DoeSettingsOut } from "../api/types";
import { counts } from "../view3d/select/layers";
import { RO_TIP, type BeadSelectCtrl } from "./BeadSelectCard";

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
              <button
                type="button"
                className="btn small ghost icon bs-del"
                aria-label={`${b.id.toUpperCase()} 삭제`}
                title={ro ? RO_TIP : "이 비드를 지웁니다(뒤 비드 번호를 당김 · 실행 취소 가능)"}
                disabled={ro}
                onClick={(e) => {
                  e.stopPropagation();
                  if (window.confirm(`비드 '${b.name}'(${b.id.toUpperCase()}) 를 지웁니다. 그 비드의 바닥·사면·묶음과 변수(${b.id.toUpperCase()}_D·_W)가 함께 빠지고, 뒤 비드 번호가 당겨집니다. 실행 취소(Ctrl+Z)로 되돌릴 수 있습니다.`)) ctrl.deleteBead(bi);
                }}
              >
                ✕
              </button>
            </header>
            {on && (
              <div className="bs-bead-body small">
                {c.tiers.map((n, i) => {
                  const k = i + 1;
                  const t = x?.tiers.find((y) => y.k === k);
                  const g = linkOf(k);
                  const cur = ctrl.layer?.kind === "tier" && ctrl.layer.bead === bi && ctrl.layer.k === k;
                  return (
                    <div key={k} className={`bs-row${cur ? " cur" : ""}`}>
                      <button type="button" className={`btn small ghost toggle bs-layer-pick${cur ? " on" : ""}`} aria-pressed={cur} aria-label={`${b.id.toUpperCase()} 단 ${k} 편집`} disabled={ro} title={ro ? RO_TIP : `단 ${k} 바닥 층을 고릅니다(3D 클릭·브러시로 더하기, 지우개·Alt 로 빼기)`} onClick={() => ctrl.setLayer({ kind: "tier", bead: bi, k })}>
                        편집
                      </button>
                      <span>
                        단{k} 바닥 <b className="mono">{n.toLocaleString()}</b>
                        {t && <span className="mono"> · D {f1(t.D_nom)}</span>}
                        {g && <span className="muted"> · 묶음 {g.map((v) => `D${v}`).join("+")}</span>}
                        {n === 0 && <span className="error-text"> · 비었음</span>}
                      </span>
                      {k > 1 && k === b.nTiers && (
                        <button type="button" className="btn small ghost" disabled={ro} onClick={() => ctrl.deleteTier(bi)} title={ro ? RO_TIP : "마지막 단을 지웁니다(바닥 요소·묶음에서 빠짐, 실행 취소 가능)"}>
                          단 {k} 삭제
                        </button>
                      )}
                      {k > 1 && (
                        <button type="button" className="btn small ghost" disabled={ro} onClick={() => ctrl.link(bi, k - 1, k)} title={`단 ${k - 1}·${k} 깊이를 같은 값으로 묶기/풀기`}>
                          {g && g.includes(k - 1) ? "묶음 풀기" : "묶기"}
                        </button>
                      )}
                    </div>
                  );
                })}
                <div className={`bs-row${ctrl.layer?.kind === "slope" && ctrl.layer.bead === bi ? " cur" : ""}`}>
                  <button type="button" className={`btn small ghost toggle bs-layer-pick${ctrl.layer?.kind === "slope" && ctrl.layer.bead === bi ? " on" : ""}`} aria-pressed={ctrl.layer?.kind === "slope" && ctrl.layer.bead === bi} aria-label={`${b.id.toUpperCase()} 사면 편집`} disabled={ro} title={ro ? RO_TIP : "사면 층을 고릅니다(자동 사면에 더하기·빼기)"} onClick={() => ctrl.setLayer({ kind: "slope", bead: bi })}>
                    편집
                  </button>
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
                <div className="inline-actions bs-bead-actions">
                  <button type="button" className="btn small ghost" disabled={ro || ctrl.deriving} onClick={ctrl.runDerive} title={ro ? RO_TIP : "사면·경계·공칭 치수를 다시 계산합니다(저장 안 함)"}>
                    {ctrl.deriving ? "계산 중…" : "사면 다시 계산"}
                  </button>
                  <button
                    type="button"
                    className="btn small ghost"
                    disabled={ro}
                    title={ro ? RO_TIP : "이 비드의 바닥·사면 선택을 비웁니다(이름·단 수 유지 · 실행 취소 가능)"}
                    onClick={() => ctrl.resetBead(bi)}
                  >
                    이 비드 초기화
                  </button>
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
        <button type="button" className="btn small" disabled={ro || s.beads.length >= ctrl.maxBeads} onClick={ctrl.addBead} title={ro ? RO_TIP : undefined}>
          + 비드
        </button>
        <button type="button" className="btn small" disabled={ro || !s.beads.length || (s.beads[ctrl.active]?.nTiers ?? 0) >= ctrl.maxTiers} onClick={ctrl.addTier} title={ro ? RO_TIP : "다단 비드: 다음 단 바닥을 고릅니다"}>
          + 단
        </button>
        <button type="button" className={`btn small ghost toggle${ctrl.layer?.kind === "fixed" ? " on" : ""}`} disabled={ro} onClick={() => ctrl.setLayer({ kind: "fixed" })} title={ro ? RO_TIP : "체결부(고정 노드)를 직접 칠합니다"}>
          고정 칠하기
        </button>
        <button
          type="button"
          className="btn small ghost"
          disabled={ro}
          title={ro ? RO_TIP : "모든 비드와 고정·제외 층을 비웁니다(실행 취소 가능 · 저장 전까지 서버는 그대로)"}
          onClick={() => window.confirm("모든 비드와 고정·제외 층을 비웁니다. [선택 저장] 전까지 서버의 저장 선택은 그대로이고, 실행 취소(Ctrl+Z)로 되돌릴 수 있습니다.") && ctrl.resetAll()}
        >
          전체 초기화
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
