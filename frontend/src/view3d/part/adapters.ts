// v0.17.3 PartView 어댑터(esl_view_unify.md §4): 시나리오·화면마다 가진 자료 → PartViewData. 없는 자료는 층을 빼고(숨김) 지어내지 않는다.
//   ①② 비드 직접 선택(select)  : selectViewData  — 평면도(plan-view select) + 3D(선택 보기 part.glb·요소 색), ② B 메시는 A 체결·하중·경계 경고까지
//   이전 방식 ①②③(same·mesh·step): legacyViewData — 평면도(plan-view) + 3D(결과 d000 형상, 실행 뒤에만)
//   미리보기 안 3D(select)     : designViewData  — 3D(안 변위·높이 색·고정 침범 빨간 점)
import type { DoePlanOut, DoeSettingsOut } from "../../api/types";
import type { BeadSelectCtrl } from "../../components/BeadSelectCard";
import { graphColors } from "../select/graph";
import { elemColors } from "../select/layers";
import type { Bbox } from "../viewFit";
import type { LayerKey, Part3DData, PartMesh, PartPlanData, PartViewData, PartWarnings, PlanVar } from "./types";

/** 평면도 자료가 가진 층 */
export function planLayers(p: PartPlanData | null): LayerKey[] {
  if (!p) return [];
  const out: LayerKey[] = [];
  if (p.outline.length || p.holes.length) out.push("boundary");
  if (p.points?.length) out.push("mesh");
  if (p.beads?.length) out.push("beads");
  if (p.fixed?.length) out.push("fixed");
  if (p.apoints?.length || p.links?.some((l) => l.kind !== "load" && l.warn && l.from_ab && l.to_ab)) out.push("apoints");
  if (p.loads?.length || p.links?.some((l) => l.kind === "load" && l.warn && l.from_ab && l.to_ab)) out.push("loads");
  if (p.nodes?.length) out.push("nodes");
  return out;
}

/** 이전 방식(same·mesh·step) plan-view → 평면도. showLinks(②③) 일 때만 A 체결·하중·경고선 */
export function legacyPlan(plan: DoePlanOut, showLinks: boolean): PartPlanData {
  return {
    ariaLabel: "비드·경계 평면도",
    style: "legacy",
    frame: plan.frame,
    outline: plan.outline,
    holes: plan.holes,
    points: plan.elems.points,
    beads: plan.beads.map((b) => ({ id: b.id, rings: [b.ring] })),
    fixed: plan.fixed,
    apoints: showLinks ? plan.a_points : null,
    loads: showLinks ? plan.load_points : null,
    links: showLinks ? plan.links : null,
  };
}

/** select plan-view → 평면도(단 색·라벨 칩·W 법선). ② B 메시 기준은 A 체결·하중·경고선(백엔드 v0.17.3 부터 넘김 — VU-D-7) */
export function selectPlan(plan: DoePlanOut, chips: Record<string, string>, meshBase: boolean): PartPlanData {
  return {
    ariaLabel: "비드 평면도",
    style: "select",
    frame: plan.frame,
    outline: plan.outline,
    holes: plan.holes,
    points: plan.elems.points,
    nodes: plan.nodes_ab ?? null,
    beads: plan.beads.map((b) => ({ id: b.id, rings: b.ring_ab ?? [b.ring], e: b.e_ab, tiers: b.tiers ?? [], label: b.label_ab, chip: chips[b.id] ?? null })),
    fixed: plan.fixed.map((f) => ({ a: f.a, b: f.b })),
    apoints: meshBase ? plan.a_points : null,
    loads: meshBase ? plan.load_points : null,
    links: meshBase ? plan.links : null,
  };
}

/** 경계 경고 표 자료(②③ 이전 방식, ② B 메시 select) */
export function boundaryWarnings(plan: DoePlanOut | null, st: DoeSettingsOut | null, nWarn: number | null | undefined): PartWarnings {
  return { links: plan?.links ?? [], nWarn: nWarn ?? null, st };
}

/** 선택 보기 3D(①② select): 요소 색 = 그래프 세그먼트(켜짐) 또는 단·사면·섬 색 */
export function selectScene(ctrl: Pick<BeadSelectCtrl, "data" | "state" | "active" | "suggested" | "islandMask" | "graph" | "editV" | "colorMode" | "graphMode" | "beadSegSet">, mesh: PartMesh, selectionBbox: (() => Bbox | null) | null): Part3DData {
  return {
    key: `select:${ctrl.data?.manifest.n_elems ?? 0}`,
    mesh,
    selectionBbox,
    hostTestId: "pv-select-3d",
    ariaLabel: "비드 형상 3D",
    elemColors: (on) => {
      const s = ctrl.state;
      if (!s) return null;
      const gi = ctrl.graph;
      if (on("graph") && ctrl.graphMode && gi && ctrl.editV) {
        const ec = elemColors(s, ctrl.active, ctrl.suggested, null);
        const other = new Set<number>();
        s.beads.forEach((b, i) => b.src === "graph" && ctrl.beadSegSet(i).forEach((x) => other.add(x)));
        const elemsC = (e: number): [number, number, number] | null => (s.owner[e] >= 0 || s.fixed[e] || s.exclude[e] ? [ec[e * 4], ec[e * 4 + 1], ec[e * 4 + 2]] : null);
        return graphColors(gi, ctrl.editV, ctrl.colorMode, { active: new Set(), other, highlight: null }, elemsC);
      }
      return elemColors(s, -1, ctrl.suggested, on("islands") ? ctrl.islandMask : null);
    },
  };
}

/** 3D 자료가 가진 층 */
export function sceneLayers(ctrl: Pick<BeadSelectCtrl, "graphMode" | "graph" | "editV" | "islandMask"> | null): LayerKey[] {
  if (!ctrl) return [];
  const out: LayerKey[] = [];
  if (ctrl.graphMode && ctrl.graph && ctrl.editV) out.push("graph");
  if (ctrl.islandMask && ctrl.islandMask.some((x) => x >= 0)) out.push("islands");
  return out;
}

/** ①② select ⑤ 평면도·단면 */
export function selectViewData(o: {
  plan: DoePlanOut;
  chips: Record<string, string>;
  active: PlanVar | null;
  meshBase: boolean;
  st: DoeSettingsOut | null;
  nWarn: number | null | undefined;
  scene: Part3DData | null;
  sceneLayers: LayerKey[];
}): PartViewData {
  const plan = selectPlan(o.plan, o.chips, o.meshBase);
  return {
    plan,
    scene: o.scene,
    layers: [...planLayers(plan), ...(o.scene ? o.sceneLayers : [])],
    warnings: o.meshBase ? boundaryWarnings(o.plan, o.st, o.nWarn) : null,
    active: o.active,
    initialMode: "plan",
  };
}

/** 이전 방식 ①②③ 평면도(+ 실행 뒤 d000 3D) */
export function legacyViewData(o: { plan: DoePlanOut; showLinks: boolean; st: DoeSettingsOut | null; nWarn: number | null | undefined; mesh: PartMesh | null }): PartViewData {
  const plan = legacyPlan(o.plan, o.showLinks);
  return {
    plan,
    scene: o.mesh ? { key: "legacy-d000", mesh: o.mesh, hostTestId: "pv-legacy-3d", ariaLabel: "기준 형상 3D(d000)" } : null,
    layers: planLayers(plan),
    warnings: o.showLinks ? boundaryWarnings(o.plan, o.st, o.nWarn) : null,
    initialMode: "plan",
  };
}

/** 미리보기 안 3D(select): 안 변위·높이 색(공칭이면 u = null)·고정 침범 빨간 점 */
export function designViewData(o: {
  did: string;
  mesh: PartMesh;
  u: Float32Array | null;
  c: Float32Array;
  vmax: number;
  scale: number;
  markers: Float32Array | null;
  selectionBbox: () => Bbox | null;
}): PartViewData {
  return {
    plan: null,
    scene: {
      key: `design:${o.did}`,
      mesh: o.mesh,
      design: { u: o.u, c: o.c, vmax: o.vmax, scale: o.scale },
      markers: o.markers,
      selectionBbox: o.selectionBbox,
      colorMap: "diverging",
      hostTestId: "bs-design-host",
      ariaLabel: `안 ${o.did} 3D`,
    },
    layers: [],
    warnings: null,
    initialMode: "3d",
  };
}
