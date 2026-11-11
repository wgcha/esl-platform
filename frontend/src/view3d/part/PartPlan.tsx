// v0.17.3 공통 평면도(esl_view_unify.md VU-D-2·3): v0.15 SelectPlan(① 비드 직접 선택) + v0.9 BoundaryPlan(이전 방식 ①②③ 경계 매핑)을 하나로.
// 층(메시 점·외곽·구멍·비드·고정·A 체결·연결·하중 집중·노드)은 자료가 있고 켜진 것만 그린다. 휠 = 확대(커서 기준), 끌기 = 이동,
// 오른쪽 위 시점 툴바(3D 와 같은 자리·모양) = 꽉 차게 · 선택 맞춤(고른 비드, 없으면 모든 비드). 단축키 F = 꽉 차게.
import { useEffect, useMemo, useRef, useState, type MouseEvent as RMouseEvent } from "react";
import type { XY } from "../../api/types";
import { tierColor } from "../select/layers";
import { FitIcon, FitSelIcon } from "../ViewToolbar";
import { clientToBox, fitBox, offsetRing, planGeom, vbText, zoomBox, type PlanBox } from "./planGeom";
import type { LayerKey, PartPlanData, PlanVar } from "./types";

const rgb = (c: [number, number, number]) => `rgb(${c.join(",")})`;

export function PartPlan({ plan, on, active }: { plan: PartPlanData; on: (k: LayerKey) => boolean; active: PlanVar | null }) {
  const g = useMemo(() => planGeom(plan.frame), [plan.frame]);
  const { S, Lx, Hy, pad, X, Y, poly } = g;
  const sel = plan.style === "select";
  const [box, setBox] = useState<PlanBox | null>(null);
  const view = box ?? g.vb;
  const host = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const viewRef = useRef(view);
  viewRef.current = view;
  const drag = useRef<{ x: number; y: number; box: PlanBox } | null>(null);
  // 형상이 바뀌면 전체 보기로
  useEffect(() => setBox(null), [g]);

  /** 선택 맞춤 대상: 고른 비드, 없으면 모든 비드 */
  const beads = plan.beads ?? [];
  const target = active ? beads.filter((b) => b.id === active.bead) : beads;
  const targetPts: [number, number][] = target.flatMap((b) => b.rings.flat().map(([a, bb]) => [X(a), Y(bb)] as [number, number]));
  const fitAll = () => setBox(null);
  const fitSel = () => {
    const b = fitBox(targetPts, g.vb);
    if (b) setBox(b);
  };
  const fitRef = useRef(fitAll);
  fitRef.current = fitAll;

  // 휠 확대(페이지 스크롤 막음 — 3D 칸과 같은 조작)
  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      const p = clientToBox(el.getBoundingClientRect(), viewRef.current, e.clientX, e.clientY);
      if (!p) return;
      e.preventDefault();
      const nb = zoomBox(viewRef.current, g.vb, p, e.deltaY > 0 ? 1.2 : 1 / 1.2);
      setBox(nb.w >= g.vb.w - 1e-9 ? null : nb);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [g]);
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "f" || e.key === "F") {
        e.preventDefault();
        fitRef.current();
      }
    };
    el.addEventListener("keydown", onKey);
    return () => el.removeEventListener("keydown", onKey);
  }, []);
  const down = (e: RMouseEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    drag.current = { x: e.clientX, y: e.clientY, box: viewRef.current };
  };
  const move = (e: RMouseEvent<SVGSVGElement>) => {
    const d = drag.current;
    const el = svg.current;
    if (!d || !el) return;
    const r = el.getBoundingClientRect();
    const s = Math.min(r.width / d.box.w, r.height / d.box.h);
    if (!(s > 0)) return;
    const dx = (e.clientX - d.x) / s;
    const dy = (e.clientY - d.y) / s;
    if (Math.abs(dx) + Math.abs(dy) < 1e-9) return;
    setBox({ ...d.box, x: d.box.x - dx, y: d.box.y - dy });
  };
  const up = () => (drag.current = null);

  const fs = sel ? S / 60 : S / 55;
  const xs = S / 120;
  const fixed = plan.fixed ?? [];
  const links = (plan.links ?? []).filter((l) => l.warn && l.from_ab && l.to_ab && (l.kind === "load" ? on("loads") : on("apoints")));
  const zoomed = !!box;
  return (
    <div className="v3d-stage pv-plan" ref={host} tabIndex={0} aria-label={`${plan.ariaLabel} 칸`}>
      <svg
        ref={svg}
        className={`keepout-svg doe-plan bs-plan${zoomed ? " zoomed" : ""}`}
        viewBox={vbText(view)}
        role="img"
        aria-label={plan.ariaLabel}
        data-testid="pv-plan"
        onMouseDown={down}
        onMouseMove={move}
        onMouseUp={up}
        onMouseLeave={up}
        onDoubleClick={fitAll}
      >
        {on("boundary") && <path d={poly(plan.outline)} className="ko-outline" />}
        {on("mesh") && (plan.points?.length ?? 0) > 0 && (
          <g className={`ko-points${sel ? " bs-dim" : ""}`} aria-hidden="true" opacity={sel ? 0.25 : undefined} data-testid="plan-points">
            {plan.points!.map(([a, b, pid], i) => (
              <circle key={i} cx={X(a)} cy={Y(b)} r={sel ? S / 650 : S / 700} className={sel || !(pid % 2) ? "p2" : "p1"} />
            ))}
          </g>
        )}
        {on("nodes") && (
          <g className="bs-nodes" aria-hidden="true" data-testid="plan-nodes">
            {(plan.nodes ?? []).map(([a, b], i) => (
              <circle key={i} cx={X(a)} cy={Y(b)} r={S / 1100} />
            ))}
          </g>
        )}
        {on("boundary") && plan.holes.map((h, i) => <path key={i} d={poly(h)} className="ko-hole" />)}
        {on("beads") &&
          beads.map((b) => {
            if (!b.tiers) {
              // 이전 방식 비드: 주황 칠 + 번호
              const ring = b.rings[0] ?? [];
              const [ca, cb] = centroid(ring);
              return (
                <g key={b.id} className={`doe-bead${active && active.bead !== b.id ? " dim" : ""}`} data-testid={`plan-bead-${b.id}`}>
                  {b.rings.map((r, i) => (
                    <path key={i} d={poly(r)} />
                  ))}
                  <text x={X(ca)} y={Y(cb)} textAnchor="middle" dominantBaseline="middle" fontSize={fs}>
                    {b.id}
                  </text>
                </g>
              );
            }
            const isOn = !active || active.bead === b.id;
            const wv = active && active.bead === b.id && active.type === "W" ? active : null;
            return (
              <g key={b.id} className={`bs-plan-bead${isOn ? " on" : ""}`} data-testid={`plan-bead-${b.id}`}>
                {b.rings.map((r, i) => (
                  <path key={i} d={poly(r)} className="bs-ring" strokeWidth={S / 420} />
                ))}
                {b.tiers.map((t) => t.ring_ab.map((r, i) => <path key={`${t.k}-${i}`} d={poly(r)} fill={rgb(tierColor(t.k))} fillOpacity={isOn ? 0.55 : 0.2} stroke="none" />))}
                {wv &&
                  b.rings.map((r, i) => (
                    <g key={`w${i}`} data-testid={`plan-w-range-${b.id}`}>
                      <path d={poly(offsetRing(r, b.e?.[i] ?? [], (wv.lo - wv.nominal) / 2))} className="bs-ring-range" strokeWidth={S / 500} strokeDasharray={`${S / 120} ${S / 200}`} />
                      <path d={poly(offsetRing(r, b.e?.[i] ?? [], (wv.hi - wv.nominal) / 2))} className="bs-ring-range" strokeWidth={S / 500} strokeDasharray={`${S / 120} ${S / 200}`} />
                    </g>
                  ))}
              </g>
            );
          })}
        {on("fixed") &&
          fixed.map((p, i) =>
            p.label ? (
              <circle key={p.label ?? i} cx={X(p.a)} cy={Y(p.b)} r={S / 160} className="doe-fixed">
                <title>{`${p.label} (${p.kind ?? "fixed"})`}</title>
              </circle>
            ) : (
              <circle key={i} cx={X(p.a)} cy={Y(p.b)} r={S / 360} className="doe-fixed" />
            ),
          )}
        {links.map((l, i) => (
          <line key={i} x1={X(l.from_ab![0])} y1={Y(l.from_ab![1])} x2={X(l.to_ab![0])} y2={Y(l.to_ab![1])} className="doe-link warn" data-testid="plan-warn-link" strokeWidth={S / 500} strokeDasharray={`${S / 120} ${S / 200}`} />
        ))}
        {on("loads") &&
          (plan.loads ?? []).map((p, i) => (
            <circle key={i} cx={X(p.a)} cy={Y(p.b)} r={(S / 60) * Math.sqrt(Math.max(0.05, p.share))} className="doe-load" data-testid="plan-load">
              <title>{`하중 집중 ${p.entry_id} · ${Math.round(p.share * 100)}%`}</title>
            </circle>
          ))}
        {on("apoints") &&
          (plan.apoints ?? []).map((p) => (
            <g key={p.label} className="doe-apt" data-testid="plan-apt">
              <path d={`M${X(p.a) - xs},${Y(p.b) - xs}L${X(p.a) + xs},${Y(p.b) + xs}M${X(p.a) - xs},${Y(p.b) + xs}L${X(p.a) + xs},${Y(p.b) - xs}`} strokeWidth={S / 450} />
              <title>{`A ${p.label}`}</title>
            </g>
          ))}
        {on("beads") &&
          beads.map((b) => {
            const t = b.chip;
            if (!t) return null;
            const at = b.label ?? b.rings[0]?.[0] ?? ([0, 0] as XY);
            const w = t.length * fs * 0.62 + fs;
            return (
              <g key={`chip-${b.id}`} className="bs-chip" data-testid={`plan-chip-${b.id}`}>
                <rect x={X(at[0]) - w / 2} y={Y(at[1]) - fs * 0.85} width={w} height={fs * 1.6} rx={fs * 0.4} />
                <text x={X(at[0])} y={Y(at[1])} textAnchor="middle" dominantBaseline="middle" fontSize={fs}>
                  {t}
                </text>
              </g>
            );
          })}
        <g className="ko-axis" fontSize={S / 75}>
          <text x={0} y={Hy + pad * 0.9} textAnchor="start">
            0
          </text>
          <text x={Lx} y={Hy + pad * 0.9} textAnchor="end">
            {Math.round(Lx)} mm (ξ)
          </text>
          <text x={-pad * 0.15} y={0} textAnchor="end" dominantBaseline="hanging">
            {Math.round(Hy)}
          </text>
          <text x={-pad * 0.15} y={Hy} textAnchor="end">
            0 (η)
          </text>
        </g>
      </svg>
      <div className="v3d-view-bar" role="toolbar" aria-label="평면도 시점" data-testid="pv-plan-bar">
        <button type="button" className="btn small ghost icon v3d-vbtn" aria-label="평면도 꽉 차게" title="평면도 전체가 꽉 차게 (단축키 F · 더블클릭) — 휠 = 확대, 끌기 = 이동" disabled={!zoomed} onClick={fitAll}>
          <FitIcon />
        </button>
        {beads.length > 0 && (
          <button type="button" className="btn small ghost icon v3d-vbtn" aria-label="평면도 선택 맞춤" title={active ? `${active.bead.toUpperCase()} 비드가 꽉 차게` : "비드 영역이 꽉 차게"} disabled={!targetPts.length} onClick={fitSel}>
            <FitSelIcon />
          </button>
        )}
      </div>
    </div>
  );
}

function centroid(pts: XY[]): XY {
  if (!pts.length) return [0, 0];
  return [pts.reduce((s, p) => s + p[0], 0) / pts.length, pts.reduce((s, p) => s + p[1], 0) / pts.length];
}
