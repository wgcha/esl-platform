// v0.15.0 ③ 비드 목록·도구(esl_bead_select.md §11.1): 비드마다 이름·단별 바닥 요소 수·공칭 D·[묶기], 사면(자동+편집)·W(최소–최대)·블렌딩, ⚠ 경고 배지(툴팁).
// 지금 고치는 비드만 펼친다(1920 에서도 세로로 짧게). 숫자(D·W·사면·경고)는 마지막 [사면·경계 자동](서버 derive) 결과.
// v0.17.0(esl_beadgraph.md §6.2): 그래프 스터디는 목록 위 [목록 | 트리] 토글. 그래프 비드 행 = ⑂ + 구성 세그먼트 수(칠하기 비드는 그대로).
import { useState } from "react";
import { isInfoWarn, warnText } from "../api/doe";
import type { DoeBeadDerived, DoeSettingsOut } from "../api/types";
import { segColor, segLabel, repOf } from "../view3d/select/graph";
import { counts, islandCount, type BeadMeta } from "../view3d/select/layers";
import { RO_TIP, unknownRefs, type BeadSelectCtrl } from "./BeadSelectCard";
import { SegmentTree } from "./SegmentTree";

const FIXED_SRC: Record<string, string> = { scan: "fixed-scan", user: "사용자 칠함", "scan+user": "fixed-scan + 사용자", none: "없음" };
const f1 = (v: number | null | undefined) => (v == null ? "–" : v.toFixed(1));

/** v0.16.1 "섬 n · 구멍 m"(derive 결과 — 편집 뒤 derive 전이면 브라우저 섬 수, 구멍은 서버만). 없으면 null */
export function islandHoleText(x: DoeBeadDerived | null, localIslands: number | null): string | null {
  const isl = localIslands ?? x?.islands?.length ?? null;
  const holes = x?.holes?.n ?? null;
  if (isl == null && holes == null) return null;
  if (!isl && !holes) return null;
  return [`섬 ${isl ?? 0}`, holes != null ? `구멍 ${holes}` : null].filter(Boolean).join(" · ");
}

export type ListView = "list" | "tree";

export function BeadList({ ctrl, editable, st, hideDirty }: { ctrl: BeadSelectCtrl; editable: boolean; st: DoeSettingsOut | null; hideDirty?: boolean }) {
  const s = ctrl.state;
  const d = ctrl.derive;
  const [view, setView] = useState<ListView>("list");
  void st;
  if (!s) return <div className="small muted">{ctrl.error ?? "불러오는 중…"}</div>;
  const der = (id: string): DoeBeadDerived | null => d?.beads.find((x) => x.id === id) ?? null;
  const ro = !editable;
  const graphOn = ctrl.graphMode;
  const tree = graphOn && view === "tree";
  return (
    <div className="bs-list">
      {graphOn && (
        <div className="bs-view-row">
          <span className="seg" role="radiogroup" aria-label="보기">
            {(["list", "tree"] as ListView[]).map((k) => (
              <button key={k} type="button" role="radio" aria-checked={view === k} className={`btn small ghost toggle${view === k ? " on" : ""}`} onClick={() => setView(k)} data-testid={`bs-view-${k}`}>
                {k === "list" ? "목록" : "트리"}
              </button>
            ))}
          </span>
          {tree && s.beads[ctrl.active] && (
            <span className="small muted" data-testid="bs-tree-target">
              체크 대상: <b>{s.beads[ctrl.active].name}</b>
              {!ctrl.activeIsGraph && " (칠하기 비드 — 체크 불가)"}
            </span>
          )}
        </div>
      )}
      {tree && <SegmentTree ctrl={ctrl} editable={editable} />}
      {!tree && s.beads.length === 0 && <div className="small muted">{graphOn ? "비드가 없습니다 — [+ 비드] 후 3D 에서 세그먼트를 클릭하거나 [트리]에서 체크하세요." : "비드가 없습니다 — [+ 비드] 후 3D 에서 바닥을 클릭하세요."}</div>}
      {!tree && s.beads.map((b, bi) => {
        if (b.src === "graph") return <GraphBeadRow key={b.id} ctrl={ctrl} b={b} bi={bi} ro={ro} />;
        const c = counts(s, bi);
        const x = der(b.id);
        const allw = x?.warnings ?? [];
        const warns = allw.filter((w) => !isInfoWarn(w));
        const infos = allw.filter((w) => isInfoWarn(w));
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
              {infos.length > 0 && (
                <span className="badge" title={infos.map((w) => warnText(w)).join("\n")} data-testid={`bead-info-${b.id}`}>
                  ⓘ{infos.length}
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
                {(() => {
                  const ih = islandHoleText(x, ctrl.localIslands ? islandCount(ctrl.localIslands, bi) : null);
                  return ih ? (
                    <div className="bs-row muted" data-testid={`bead-islands-${b.id}`} title="섬(딤플·버링) = 바닥과 같이 이동 · 관통 구멍 = 둘레가 바닥과 같이 이동(경계 아님). 섬을 빼려면 '제외' 층으로 칠하세요">
                      {ih}
                    </div>
                  ) : null;
                })()}
                <div className="bs-row">
                  <span>
                    W <b className="mono">{f1(x?.W_nom)}</b> <span className="muted mono">({f1(x?.W_min)}–{f1(x?.W_max)})</span> · 블렌딩 {b.blend === "auto" ? "auto" : "직접"} <span className="mono">{x ? `${f1(x.blend_mm)} mm` : ""}</span>
                    {x?.blend_clipped && <span className="badge warn" title="체결부 앞에서 줄임">잘림</span>}
                  </span>
                </div>
                {(() => {
                  const nFix = x ? x.fixed_in_bead_n + x.fixed_in_blend_n : 0;
                  const can = !ro && (b.holdFixed === 1 || nFix > 0);
                  const tip = ro
                    ? RO_TIP
                    : nFix > 0 || b.holdFixed
                      ? `체결 구멍 둘레를 제자리에 두고 바깥을 블렌딩해 보스처럼 남깁니다 — 링 ${ctrl.hold.ring_mm} mm 제자리 · ${ctrl.hold.blend_mm} mm 블렌딩`
                      : x
                        ? "이 비드 안·블렌딩 안에 고정 노드가 없습니다"
                        : "[사면 다시 계산] 후 고정 노드가 있으면 켤 수 있습니다";
                  return (
                    <label className="check-field bs-row" title={tip}>
                      <input type="checkbox" checked={b.holdFixed === 1} disabled={!can} onChange={(e) => ctrl.setHold(bi, e.target.checked ? 1 : 0)} data-testid={`bead-hold-${b.id}`} />
                      <span>체결 구멍 둘레 고정</span>
                    </label>
                  );
                })()}
                <div className="inline-actions bs-bead-actions">
                  <button type="button" className="btn small ghost" disabled={ro || ctrl.deriving} onClick={ctrl.runDerive} title={ro ? RO_TIP : "사면·경계·공칭 치수를 다시 계산합니다(저장 안 함)"}>
                    {ctrl.deriving ? "계산 중…" : "사면 다시 계산"}
                  </button>
                  <button
                    type="button"
                    className="btn small ghost"
                    disabled={ro}
                    title={ro ? RO_TIP : ctrl.hasSeed ? "이 비드를 자동 탐지 결과로 되돌립니다(이름 유지 · 실행 취소 가능)" : "이 비드의 바닥·사면 선택을 비웁니다(이름·단 수 유지 · 실행 취소 가능)"}
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
                {infos.length > 0 && (
                  <ul className="reasons small muted" data-testid={`bead-infos-${b.id}`}>
                    {infos.map((w, i) => (
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
        <button type="button" className="btn small" disabled={ro || s.beads.length >= ctrl.maxBeads} onClick={graphOn ? ctrl.addGraphBead : ctrl.addBead} title={ro ? RO_TIP : graphOn ? "세그먼트로 만드는 비드(트리 체크·3D 클릭)" : undefined} data-testid="bs-add-bead">
          + 비드
        </button>
        {graphOn && (
          <button type="button" className="btn small ghost" disabled={ro || s.beads.length >= ctrl.maxBeads} onClick={ctrl.addBead} title={ro ? RO_TIP : "분류가 못 잡은 곳(곡면 바닥 등)을 요소로 칠하는 비드"} data-testid="bs-add-elems">
            + 칠하기 비드
          </button>
        )}
        {(!graphOn || (s.beads[ctrl.active] && !ctrl.activeIsGraph)) && (
          <button type="button" className="btn small" disabled={ro || !s.beads.length || ctrl.activeIsGraph || (s.beads[ctrl.active]?.nTiers ?? 0) >= ctrl.maxTiers} onClick={ctrl.addTier} title={ro ? RO_TIP : "다단 비드: 다음 단 바닥을 고릅니다"}>
            + 단
          </button>
        )}
        <button type="button" className={`btn small ghost toggle${ctrl.layer?.kind === "fixed" ? " on" : ""}`} disabled={ro} onClick={() => ctrl.setLayer({ kind: "fixed" })} title={ro ? RO_TIP : "체결부(고정 노드)를 직접 칠합니다"}>
          고정 칠하기
        </button>
        <button
          type="button"
          className="btn small ghost"
          disabled={ro}
          title={ro ? RO_TIP : ctrl.hasSeed ? "모든 비드·고정·제외 층을 자동 탐지 결과로 되돌립니다(실행 취소 가능 · 저장 전까지 서버는 그대로)" : "모든 비드와 고정·제외 층을 비웁니다(실행 취소 가능 · 저장 전까지 서버는 그대로)"}
          onClick={() =>
            window.confirm(
              ctrl.hasSeed
                ? "모든 비드와 고정·제외 층을 자동 탐지 결과로 되돌립니다. [선택 저장] 전까지 서버의 저장 선택은 그대로이고, 실행 취소(Ctrl+Z)로 되돌릴 수 있습니다."
                : "모든 비드와 고정·제외 층을 비웁니다. [선택 저장] 전까지 서버의 저장 선택은 그대로이고, 실행 취소(Ctrl+Z)로 되돌릴 수 있습니다.",
            ) && ctrl.resetAll()
          }
        >
          전체 초기화
        </button>
      </div>
      {d && (
        <div className="small muted" data-testid="bs-fixed">
          고정: {FIXED_SRC[d.fixed.source] ?? d.fixed.source} · 스캔 {d.fixed.scan_n} · 사용자 {d.fixed.user_n} 노드
        </div>
      )}
      {(s.ties?.length ?? 0) > 0 && (
        <div className="small" data-testid="bs-ties">
          대칭 묶기:{" "}
          {s.ties!.map((g, i) => (
            <span key={i} className="chip">
              {g.map((x) => x.toUpperCase()).join(" = ")}{" "}
              <button type="button" className="btn small ghost icon" aria-label={`묶기 ${g.join("=")} 풀기`} disabled={ro} onClick={() => ctrl.toggleTie(g)}>
                ✕
              </button>
            </span>
          ))}
        </div>
      )}
      {ctrl.dirty && !hideDirty && <div className="small warn-text" data-testid="bs-dirty">저장 안 한 변경이 있습니다 — [선택 저장]</div>}
    </div>
  );
}

/** v0.17.0 그래프 비드 행: ⑂ · 이름 · 세그먼트 n · D/W 공칭(derive) — 펼치면 구성 세그먼트(✕ 빼기)·체결 고정·초기화 */
function GraphBeadRow({ ctrl, b, bi, ro }: { ctrl: BeadSelectCtrl; b: BeadMeta; bi: number; ro: boolean }) {
  const on = bi === ctrl.active;
  const gi = ctrl.graph;
  const segs = [...ctrl.beadSegSet(bi)].sort((x, y) => x - y);
  const v = ctrl.editV;
  const reps = v ? [...new Set(segs.map((x) => repOf(v, x)))] : segs;
  const islands = (b.segs ?? []).filter((r) => "anchor" in r && gi && gi.labels.island[r.anchor] >= 0).length;
  const db = ctrl.derive?.graph?.beads.find((x) => x.id === b.id) ?? null;
  const allw = [...(ctrl.derive?.beads.find((x) => x.id === b.id)?.warnings ?? []), ...(ctrl.derive?.warnings ?? []).filter((w) => w.bead === b.id)];
  const warns = allw.filter((w) => !isInfoWarn(w));
  const infos = allw.filter((w) => isInfoWarn(w));
  const unknown = unknownRefs(gi, (b.segs ?? []).filter((r): r is { anchor: number } => "anchor" in r));
  const nets = (b.segs ?? []).filter((r) => "network" in r).length;
  return (
    <section className={`bs-bead${on ? " on" : ""}`} data-testid={`bead-${b.id}`} aria-current={on || undefined}>
      <header className="bs-bead-head" onClick={() => !on && ctrl.setActive(bi)}>
        <span className="mono small" title="그래프 비드(세그먼트 묶음)">⑂ {b.id.toUpperCase()}</span>
        <input className="bs-name" aria-label={`${b.id.toUpperCase()} 이름`} value={b.name} maxLength={32} disabled={ro} onChange={(e) => ctrl.rename(bi, e.target.value)} onFocus={() => !on && ctrl.setActive(bi)} />
        {warns.length > 0 && (
          <span className="badge warn" title={warns.map((w) => warnText(w)).join("\n")} data-testid={`bead-warn-${b.id}`}>
            ⚠{warns.length}
          </span>
        )}
        {infos.length > 0 && (
          <span className="badge" title={infos.map((w) => warnText(w)).join("\n")} data-testid={`bead-info-${b.id}`}>
            ⓘ{infos.length}
          </span>
        )}
        <span className="small muted" data-testid={`bead-nseg-${b.id}`}>
          세그먼트 {reps.length + islands}
          {nets ? " · 네트워크" : ""}
          {db?.D_nom != null ? ` · D ${f1(db.D_nom)}` : ""}
          {db?.W_nom != null ? ` · W ${f1(db.W_nom)}` : ""}
        </span>
        <button
          type="button"
          className="btn small ghost icon bs-del"
          aria-label={`${b.id.toUpperCase()} 삭제`}
          title={ro ? RO_TIP : "이 비드를 지웁니다(뒤 비드 번호를 당김 · 실행 취소 가능)"}
          disabled={ro}
          onClick={(e) => {
            e.stopPropagation();
            if (window.confirm(`비드 '${b.name}'(${b.id.toUpperCase()}) 를 지웁니다. 변수(${b.id.toUpperCase()}_D·_W)와 대칭 묶기가 함께 빠지고, 뒤 비드 번호가 당겨집니다. 실행 취소(Ctrl+Z)로 되돌릴 수 있습니다.`)) ctrl.deleteBead(bi);
          }}
        >
          ✕
        </button>
      </header>
      {on && (
        <div className="bs-bead-body small">
          <div className="bs-seg-chips" data-testid={`bead-segs-${b.id}`}>
            {!segs.length && !islands && <span className="muted">세그먼트 없음 — 3D 클릭 또는 [트리] 체크</span>}
            {reps.map((id) => {
              const sg = gi?.segById.get(id);
              if (!sg) return null;
              const n = v ? segs.filter((x) => repOf(v, x) === id).length : 1;
              return (
                <span key={id} className="chip sg-chip" onClick={() => ctrl.setHighlight({ kind: "seg", id })}>
                  <i className="sg-sw" style={{ background: `rgb(${segColor(id).join(",")})` }} aria-hidden="true" />
                  {segLabel(sg)} {id}
                  {n > 1 ? ` (+${n - 1})` : ""}
                  <button type="button" className="btn small ghost icon" aria-label={`${segLabel(sg)} ${id} 빼기`} disabled={ro} onClick={(e) => {
                    e.stopPropagation();
                    ctrl.toggleSeg(id);
                  }}>
                    ✕
                  </button>
                </span>
              );
            })}
            {unknown.map((a) => (
              <span key={`u${a}`} className="chip bad" title="분류 결과에서 찾지 못한 세그먼트(BG_SEG_UNKNOWN)">
                ? 앵커 {a}
              </span>
            ))}
          </div>
          <label className="check-field bs-row" title={ro ? RO_TIP : `체결 구멍 둘레를 제자리에 두고 블렌딩(그래프 비드 기본 켜짐) — 링 ${ctrl.hold.ring_mm} mm · ${ctrl.hold.blend_mm} mm 블렌딩`}>
            <input type="checkbox" checked={b.holdFixed === 1} disabled={ro} onChange={(e) => ctrl.setHold(bi, e.target.checked ? 1 : 0)} data-testid={`bead-hold-${b.id}`} />
            <span>체결 구멍 둘레 고정</span>
          </label>
          <div className="inline-actions bs-bead-actions">
            <button
              type="button"
              className="btn small ghost"
              disabled={ro}
              title={ro ? RO_TIP : ctrl.hasSeed ? "이 비드를 자동 탐지 결과로 되돌립니다(이름 유지 · 실행 취소 가능)" : "이 비드의 세그먼트를 비웁니다(이름 유지 · 실행 취소 가능)"}
              onClick={() => ctrl.resetBead(bi)}
              data-testid={`bead-reset-${b.id}`}
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
          {infos.length > 0 && (
            <ul className="reasons small muted" data-testid={`bead-infos-${b.id}`}>
              {infos.map((w, i) => (
                <li key={i}>{warnText(w)}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
