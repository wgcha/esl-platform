// v0.17.0 세그먼트 트리(esl_beadgraph.md §6.2 — 새 화면 없이 ③ 목록 자리의 [트리] 보기): 바닥 위계(플랜지 → 고리 띠 → 플래토 → 채널·포켓) 아래
// 세그먼트(종류·변·D·W) · 접합 구역(회색, 변수 없음) · 섬·랜스(크기 mm) · 구멍 수. 행 클릭 = 3D 강조(3D 클릭도 이 행을 강조), 체크 = 지금 비드에 더하기/빼기,
// 우클릭 = [섬으로]/[비드로] · [인접과 병합] · [네트워크 전체로 묶기]. [대칭 묶기 제안] = derive sym_pairs 에서 골라 ties.
import { useEffect, useMemo, useRef, useState, type MouseEvent as RMouseEvent } from "react";
import type { BgIsland, BgSegment } from "../api/types";
import { adjacentSegs, buildTree, repOf, segColor, segLabel, targetKey, SEG_TYPE_NAME, type GraphTarget, type TreeFloor } from "../view3d/select/graph";
import { RO_TIP, type BeadSelectCtrl } from "./BeadSelectCard";

const f1 = (v: number | null | undefined) => (v == null ? "–" : v.toFixed(1));
const sw = (c: [number, number, number]) => `rgb(${c[0]},${c[1]},${c[2]})`;

interface Menu {
  x: number;
  y: number;
  t: GraphTarget;
}

export function SegmentTree({ ctrl, editable }: { ctrl: BeadSelectCtrl; editable: boolean }) {
  const gi = ctrl.graph;
  const s = ctrl.state;
  const tree = useMemo(() => (gi ? buildTree(gi) : null), [gi]);
  const [closed, setClosed] = useState<Set<number>>(new Set());
  const [openIsl, setOpenIsl] = useState<Set<number>>(new Set());
  const [menu, setMenu] = useState<Menu | null>(null);
  const [symOpen, setSymOpen] = useState(false);
  const [editsOpen, setEditsOpen] = useState(false);
  const host = useRef<HTMLDivElement>(null);
  const ro = !editable;
  const hk = targetKey(ctrl.highlight);

  // 3D → 트리: 강조 대상이 바뀌면 그 행을 펼치고 보이게
  useEffect(() => {
    const h = ctrl.highlight;
    if (!h || !gi) return;
    if (h.kind === "island") {
      const il = gi.islandById.get(h.id);
      const fl = il ? (il.parent === gi.graph.root || gi.graph.root_group.includes(il.parent) ? gi.graph.root : il.parent) : null;
      if (fl != null) setOpenIsl((o) => (o.has(fl) ? o : new Set([...o, fl])));
    }
    const el = host.current?.querySelector(`[data-key="${hk}"]`) as HTMLElement | null;
    el?.scrollIntoView?.({ block: "nearest" });
  }, [hk, gi, ctrl.highlight]);
  useEffect(() => {
    if (!menu) return;
    const close = (e: KeyboardEvent | globalThis.MouseEvent) => (e instanceof KeyboardEvent ? e.key === "Escape" && setMenu(null) : setMenu(null));
    window.addEventListener("keydown", close);
    window.addEventListener("click", close);
    return () => {
      window.removeEventListener("keydown", close);
      window.removeEventListener("click", close);
    };
  }, [menu]);

  if (!gi || !tree || !s || !ctrl.editV) return <div className="small muted">{ctrl.graphPhase === "loading" ? "분류 결과 불러오는 중…" : "분류 결과가 없습니다"}</div>;
  const v = ctrl.editV;
  const dg = ctrl.derive?.graph ?? null;
  const dOf = (sg: BgSegment) => dg?.segments.find((x) => x.anchor === sg.anchor)?.D ?? sg.D;
  const canCheck = !ro && ctrl.activeIsGraph;
  const activeName = s.beads[ctrl.active]?.name ?? "";

  const openMenu = (e: RMouseEvent, t: GraphTarget) => {
    e.preventDefault();
    if (ro) return;
    const r = host.current!.getBoundingClientRect();
    setMenu({ x: e.clientX - r.left, y: e.clientY - r.top, t });
  };

  const segRow = (sg: BgSegment) => {
    const t: GraphTarget = { kind: "seg", id: sg.id };
    const owner = ctrl.segOwner(sg.id);
    const asIsl = v.segAsIsland.has(sg.id);
    const merged = v.group.has(sg.id);
    const nSplit = v.splits.get(sg.id) ?? 0;
    const mine = owner === ctrl.active && owner >= 0;
    const base = sg.type === "base";
    const other = owner >= 0 && !mine;
    const tip = ro ? RO_TIP : base ? "플랜지(뿌리)는 변수가 없습니다" : asIsl ? "섬으로 바꾼 세그먼트 — 우클릭 [비드로]" : other ? `${s.beads[owner].name} 에 들어 있습니다` : !ctrl.activeIsGraph ? "그래프 비드를 고르거나 [+ 비드]로 만드세요" : `체크 = ${activeName} 에 ${mine ? "빼기" : "더하기"}`;
    return (
      <div
        key={`s${sg.id}`}
        role="treeitem"
        aria-selected={hk === targetKey(t)}
        data-key={targetKey(t)}
        data-testid={`sg-seg-${sg.id}`}
        className={`sg-row sg-seg${hk === targetKey(t) ? " hl" : ""}${mine ? " mine" : ""}`}
        onClick={() => ctrl.setHighlight(t)}
        onContextMenu={(e) => !base && openMenu(e, t)}
      >
        <input type="checkbox" aria-label={`${segLabel(sg)} ${sg.id} 를 지금 비드에`} checked={owner >= 0} disabled={!canCheck || base || asIsl || other} title={tip} onClick={(e) => e.stopPropagation()} onChange={() => ctrl.toggleSeg(sg.id)} />
        <i className="sg-sw" style={{ background: base ? "var(--line-strong)" : sw(segColor(repOf(v, sg.id))) }} aria-hidden="true" />
        <span className="sg-name">{segLabel(sg)}</span>
        <span className="mono small muted">
          {base ? "" : `D ${f1(dOf(sg))}${sg.entry_width != null && !["plateau", "area"].includes(sg.type) ? ` · W ${f1(sg.entry_width)}` : ""}${sg.length != null ? ` · L ${Math.round(sg.length)}` : ""}`}
        </span>
        {other && <span className="badge">{s.beads[owner].id.toUpperCase()}</span>}
        {merged && <span className="badge info" title="병합한 세그먼트(한 변수)">병합</span>}
        {nSplit > 0 && <span className="badge info" title="분할 점(변수 없는 분할 구역)">분할 {nSplit}</span>}
        {asIsl && <span className="badge warn">섬으로</span>}
      </div>
    );
  };

  const islRow = (il: BgIsland) => {
    const t: GraphTarget = { kind: "island", id: il.id };
    const asBead = v.islandAsBead.has(il.id);
    const owner = asBead ? ctrl.islandOwner(il.id) : -1;
    return (
      <div key={`i${il.id}`} role="treeitem" aria-selected={hk === targetKey(t)} data-key={targetKey(t)} data-testid={`sg-isl-${il.id}`} className={`sg-row sg-isl${hk === targetKey(t) ? " hl" : ""}`} onClick={() => ctrl.setHighlight(t)} onContextMenu={(e) => openMenu(e, t)}>
        {asBead ? (
          <input type="checkbox" aria-label={`섬 ${il.id} 을 지금 비드에`} checked={owner >= 0} disabled={!canCheck || (owner >= 0 && owner !== ctrl.active)} onClick={(e) => e.stopPropagation()} onChange={() => ctrl.toggleIslandRef(il.id)} />
        ) : (
          <span className="sg-icon" aria-hidden="true">{il.lance ? "⌒" : "◇"}</span>
        )}
        <span className="sg-name">{il.lance ? "랜스" : asBead ? "섬 → 비드" : "섬"}</span>
        <span className="mono small muted">{f1(il.size_mm)} mm</span>
        {il.straddle && <span className="badge" title="벽에 걸친 보스 — 채널을 따라감(D6)">걸침</span>}
        {il.fixed && <span className="badge" title="고정 노드가 있음">고정</span>}
      </div>
    );
  };

  const floorNode = (f: TreeFloor, depth: number) => {
    const open = !closed.has(f.floor);
    const t: GraphTarget = { kind: "floor", id: f.floor };
    const nIsl = f.islands.filter((i) => !i.lance).length;
    const nLance = f.islands.length - nIsl;
    const islOpen = openIsl.has(f.floor);
    return (
      <div key={`f${f.floor}`} role="group" className="sg-floor" style={{ marginLeft: depth ? "0.9rem" : 0 }}>
        <div role="treeitem" aria-expanded={open} aria-selected={hk === targetKey(t)} data-key={targetKey(t)} data-testid={`sg-floor-${f.floor}`} className={`sg-row sg-fhead${hk === targetKey(t) ? " hl" : ""}`} onClick={() => ctrl.setHighlight(t)}>
          <button type="button" className="btn small ghost icon sg-caret" aria-label={open ? "접기" : "펼치기"} onClick={(e) => {
            e.stopPropagation();
            setClosed((c) => {
              const n = new Set(c);
              if (n.has(f.floor)) n.delete(f.floor);
              else n.add(f.floor);
              return n;
            });
          }}>
            {open ? "▾" : "▸"}
          </button>
          <b>{f.name}</b>
          <span className="small muted">tier {f.tier}</span>
          {f.holes > 0 && <span className="small muted">· 구멍 {f.holes}</span>}
        </div>
        {open && (
          <div className="sg-kids">
            {f.segs.map(segRow)}
            {f.zones.map((z) => (
              <div key={`z${z.id}`} role="treeitem" aria-selected={hk === `zone:${z.id}`} data-key={`zone:${z.id}`} data-testid={`sg-zone-${z.id}`} className={`sg-row sg-zone${hk === `zone:${z.id}` ? " hl" : ""}`} onClick={() => ctrl.setHighlight({ kind: "zone", id: z.id })}>
                <i className="sg-sw zone" aria-hidden="true" />
                <span className="sg-name">{z.label}</span>
                <span className="small muted">변수 없음</span>
              </div>
            ))}
            {f.islands.length > 0 && (
              <>
                <button type="button" className="btn small ghost sg-islgrp" aria-expanded={islOpen} onClick={() => setOpenIsl((o) => {
                  const n = new Set(o);
                  if (n.has(f.floor)) n.delete(f.floor);
                  else n.add(f.floor);
                  return n;
                })} data-testid={`sg-islgrp-${f.floor}`}>
                  {islOpen ? "▾" : "▸"} 섬 {nIsl}{nLance ? ` · 랜스 ${nLance}` : ""}
                </button>
                {islOpen && f.islands.map(islRow)}
              </>
            )}
            {f.children.map((c) => floorNode(c, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  // ---- 우클릭 메뉴
  const menuItems = (t: GraphTarget): { label: string; on: () => void; testId: string }[] => {
    if (t.kind === "seg") {
      const sg = gi.segById.get(t.id)!;
      const items = [
        v.segAsIsland.has(t.id) ? { label: "비드로", on: () => ctrl.convert(t, "bead"), testId: "sg-menu-bead" } : { label: "섬으로", on: () => ctrl.convert(t, "island"), testId: "sg-menu-island" },
        ...adjacentSegs(gi, t.id)
          .filter((o) => repOf(v, o) !== repOf(v, t.id))
          .map((o) => ({ label: `인접과 병합: ${segLabel(gi.segById.get(o)!)} ${o}`, on: () => ctrl.merge(t.id, o), testId: `sg-menu-merge-${o}` })),
      ];
      if (sg.network >= 0) items.push({ label: "네트워크 전체로 묶기", on: () => ctrl.groupNetwork(t.id), testId: "sg-menu-network" });
      return items;
    }
    if (t.kind === "island") return [v.islandAsBead.has(t.id) ? { label: "섬으로", on: () => ctrl.convert(t, "island"), testId: "sg-menu-island" } : { label: "비드로", on: () => ctrl.convert(t, "bead"), testId: "sg-menu-bead" }];
    return [];
  };

  // ---- 대칭 묶기 제안(sym_pairs → 비드 쌍)
  const ties = s.ties ?? [];
  const tied = (a: string, b: string) => ties.some((g) => g.includes(a) && g.includes(b));
  const sym = ctrl.symPairs.map(([a1, a2]) => {
    const s1 = gi.segByAnchor.get(a1);
    const s2 = gi.segByAnchor.get(a2);
    const o1 = s1 != null ? ctrl.segOwner(s1) : -1;
    const o2 = s2 != null ? ctrl.segOwner(s2) : -1;
    const type = s1 != null ? SEG_TYPE_NAME[gi.segById.get(s1)!.type] : "?";
    return { a1, a2, s1, s2, o1, o2, type };
  });
  const ed = s.edits;
  const nEdits = ed ? ed.toggle.length + ed.merge.length + ed.split.length : 0;

  return (
    <div className="sg-tree" ref={host} data-testid="sg-tree">
      <div className="sg-bar">
        <button type="button" className="btn small ghost" aria-expanded={symOpen} onClick={() => setSymOpen((x) => !x)} disabled={ro} title={ro ? RO_TIP : "같은 tier·종류의 거울 위치 세그먼트 쌍 — 골라서 D·W 를 한 변수로"} data-testid="sg-sym">
          대칭 묶기 제안{sym.length ? ` (${sym.length})` : ""}
        </button>
        {nEdits > 0 && (
          <button type="button" className="btn small ghost" aria-expanded={editsOpen} onClick={() => setEditsOpen((x) => !x)} data-testid="sg-edits">
            편집 {ed!.toggle.length ? `전환 ${ed!.toggle.length} ` : ""}{ed!.merge.length ? `병합 ${ed!.merge.length} ` : ""}{ed!.split.length ? `분할 ${ed!.split.length}` : ""}
          </button>
        )}
        <span className="small muted">세그먼트 {gi.graph.segments.length} · 접합 구역 {gi.graph.junction_zones.length} · 섬 {gi.graph.islands.length}</span>
      </div>
      {symOpen && (
        <div className="sg-pop" data-testid="sg-sym-list">
          {!sym.length && <div className="small muted">제안이 없습니다 — [다시 계산] 뒤 다시 보세요</div>}
          {sym.map((p, i) => {
            const ok = p.o1 >= 0 && p.o2 >= 0 && p.o1 !== p.o2;
            const b1 = ok ? s.beads[p.o1] : null;
            const b2 = ok ? s.beads[p.o2] : null;
            const on = !!b1 && !!b2 && tied(b1.id, b2.id);
            return (
              <label key={i} className="check-field sg-sym-row" title={ok ? "D·W 를 한 변수로 묶기(BG-D-21)" : "두 세그먼트가 각각 다른 비드에 있어야 묶을 수 있습니다"}>
                <input type="checkbox" checked={on} disabled={!ok || ro} onChange={() => b1 && b2 && ctrl.toggleTie([b1.id, b2.id])} data-testid={`sg-sym-${i}`} />
                <span>
                  {p.type} {p.s1 ?? "?"} ↔ {p.s2 ?? "?"}
                  {ok ? <span className="mono"> · {b1!.id.toUpperCase()} = {b2!.id.toUpperCase()}</span> : <span className="muted"> · 각각 비드로 먼저</span>}
                </span>
              </label>
            );
          })}
        </div>
      )}
      {editsOpen && ed && (
        <ul className="sg-pop sg-edit-list small" data-testid="sg-edit-list">
          {ed.toggle.map((x, i) => (
            <li key={`t${i}`}>
              {x.as === "bead" ? "섬 → 비드" : "비드 → 섬"} (앵커 {x.anchor}) <button type="button" className="btn small ghost icon" aria-label="전환 취소" disabled={ro} onClick={() => ctrl.removeEdit("toggle", i)}>✕</button>
            </li>
          ))}
          {ed.merge.map((g, i) => (
            <li key={`m${i}`}>
              병합 {g.map((r) => gi.segByAnchor.get(r.anchor) ?? `#${r.anchor}`).join(" + ")} <button type="button" className="btn small ghost icon" aria-label="병합 취소" disabled={ro} onClick={() => ctrl.removeEdit("merge", i)}>✕</button>
            </li>
          ))}
          {ed.split.map((x, i) => (
            <li key={`p${i}`}>
              분할 {gi.segByAnchor.get(x.anchor) ?? `#${x.anchor}`} @ ({x.at[0].toFixed(0)}, {x.at[1].toFixed(0)}) <button type="button" className="btn small ghost icon" aria-label="분할 취소" disabled={ro} onClick={() => ctrl.removeEdit("split", i)}>✕</button>
            </li>
          ))}
        </ul>
      )}
      <div role="tree" aria-label="세그먼트 트리" className="sg-body">
        {floorNode(tree, 0)}
      </div>
      {menu && (
        <div className="sg-menu" role="menu" style={{ left: menu.x, top: menu.y }} data-testid="sg-menu" onClick={(e) => e.stopPropagation()}>
          {menuItems(menu.t).map((m) => (
            <button key={m.testId} type="button" role="menuitem" className="btn small ghost" data-testid={m.testId} onClick={() => {
              m.on();
              setMenu(null);
            }}>
              {m.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
