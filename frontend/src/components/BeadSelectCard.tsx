// v0.15.0 비드 직접 선택 카드(esl_bead_select.md §3-3·§11): ② 3D 요소 선택(클릭+확장·브러시·사각·올가미, 보이는 면만) + ③ 비드 목록·도구(BeadList).
// 상태(층·실행 취소·derive)는 useBeadSelect 가 갖고, 페이지(DoeStudy)가 [선택 저장](주 버튼)·변수 표 블렌딩 편집에 같은 컨트롤러를 쓴다.
// 3D 는 기존 장면(scene.ts — TrackballControls 회전 그대로)에 요소 모드만 더한다. 그리기 도구 중 왼쪽 끌기 = 도구, Ctrl+끌기 = 회전, 오른쪽 = 이동, 휠 = 확대.
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { doe, warnText } from "../api/doe";
import { errorText } from "../api/client";
import type { DoeFixedViol, DoeBasisMeta, DoeDeriveOut, DoeElemSet, DoeSelectionIn, DoeSelectionOut, DoeSelectViewManifest, DoeSettingsOut } from "../api/types";
import { fetchBinary } from "../view3d/fetchFiles";
import { parseGlb, type ParsedGlb } from "../view3d/glb";
import { loadScene } from "../view3d/loadThree";
import type { SceneApi } from "../view3d/sceneApi";
import { hasWebGL } from "../view3d/webgl";
import { DIVERGING_GRADIENT } from "../view3d/colors";
import { boundaryEdges, buildTopo, ringStep, type MeshTopo } from "../view3d/select/adjacency";
import { grow } from "../view3d/select/grow";
import { History, type Patch } from "../view3d/select/history";
import { centroidsInMask, idsInMask, inCircle, pointInPolygon, polyBounds, rectOf, type Pt } from "../view3d/select/lasso";
import {
  addBead, addTier, applyPatch, clearLayer, deleteBead, deleteLastTier, resetAll, resetBead, effectiveSlope, elemColors, emptyState, enclosedIslands, fromSelectionIn, ownerBead, ownerCode, paint, toSelectionIn, toggleLink,
  type Layer, type LayerName, type SelIslands, type SelState,
} from "../view3d/select/layers";
import { elemIndex, fromElemSet, type ElemIndex } from "../view3d/select/ranges";
import { parseSelectBin, type SelectBin } from "../view3d/select/view";
import { heightChange, maxAbs, morph, parseBasis, type BasisVar } from "../view3d/select/basis";
import { ViewToolbar } from "../view3d/ViewToolbar";
import { elemsBbox, positionsBbox } from "../view3d/viewFit";
import { BeadList } from "./BeadList";
import { FixedViolNote } from "./FixedViol";
import { Card, ErrorLine } from "./ui";

export const NO_3D = "이 브라우저에서 3D 보기를 쓸 수 없습니다";
/** 편집 불가(실행 후·권한 없음) 버튼 툴팁 */
export const RO_TIP = "실행 후에는 이 스터디의 선택을 바꿀 수 없습니다 — 복제해서 편집";
const BACKGROUND = "#dfe3e8";

export interface SelectData {
  manifest: DoeSelectViewManifest;
  glb: ParsedGlb;
  bin: SelectBin;
  topo: MeshTopo;
  idx: ElemIndex;
}

/** 선택 보기 자료(part.glb · select.bin · manifest) — 준비 후 1회 */
function useSelectData(studyId: string, on: boolean) {
  const [data, setData] = useState<SelectData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setData(null);
    setError(null);
    if (!on) return;
    let alive = true;
    void (async () => {
      try {
        const manifest = await doe.selectManifest(studyId);
        const [g, b] = await Promise.all([fetchBinary(doe.selectViewUrl(studyId, "part.glb")), fetchBinary(doe.selectViewUrl(studyId, "select.bin"))]);
        const glb = parseGlb(g);
        if (glb.positions.length / 3 !== manifest.n_nodes) throw new Error("3D 형상의 노드 수가 manifest 와 다릅니다");
        const bin = parseSelectBin(b, manifest);
        const topo = buildTopo(glb.positions, glb.indices, bin.tri2elem, manifest.n_elems);
        if (alive) setData({ manifest, glb, bin, topo, idx: elemIndex(bin.elemId, bin.elemType) });
      } catch (e) {
        if (alive) setError(errorText(e));
      }
    })();
    return () => {
      alive = false;
    };
  }, [studyId, on]);
  return { data, error };
}

export type Tool = "click" | "brush" | "rect" | "lasso";

export interface BeadSelectCtrl {
  data: SelectData | null;
  error: string | null;
  state: SelState | null;
  tick: number;
  active: number;
  setActive: (b: number) => void;
  layer: Layer | null;
  setLayer: (l: Layer) => void;
  featureAngle: number;
  setFeatureAngle: (v: number) => void;
  derive: DoeDeriveOut | null;
  deriving: boolean;
  deriveError: string | null;
  runDerive: () => void;
  /** 저장본과 다름(또는 미저장) */
  dirty: boolean;
  /** 저장 전 화면 검사(빈 단·비드 없음·이름) — null = 통과 */
  problem: string | null;
  input: () => DoeSelectionIn | null;
  suggested: (b: number) => Uint8Array | null;
  paintElems: (elems: number[], layer: Layer, mode: "add" | "remove", merge?: boolean) => void;
  endStroke: () => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  addBead: () => void;
  addTier: () => void;
  link: (bead: number, a: number, c: number) => void;
  rename: (bead: number, name: string) => void;
  setBlend: (beadId: string, v: "auto" | number) => void;
  blendOf: (beadId: string) => "auto" | number | null;
  ring: (dir: 1 | -1) => void;
  /** v0.15.1 지우기: 지금 층 비우기 · 비드 삭제(번호 정리) · 마지막 단 삭제 — 모두 실행 취소 가능 */
  clearLayer: () => void;
  deleteBead: (bead: number) => void;
  deleteTier: (bead: number) => void;
  /** 이 비드 초기화(요소·그 비드 derive 결과, 이름 유지) · 전체 초기화(비드·고정·제외 모두) — 실행 취소 가능, 서버는 [선택 저장] 전까지 그대로 */
  resetBead: (bead: number) => void;
  resetAll: () => void;
  maxBeads: number;
  maxTiers: number;
  /** v0.16.1 섬(SR-D-14): 요소별 섬 주인 코드(표시 전용) — 편집 직후 = 브라우저 계산, derive 뒤 = 서버 islands */
  islandMask: Int32Array | null;
  /** 브라우저 계산 섬(편집 뒤 derive 전까지) — 비드별 수 표시용 */
  localIslands: SelIslands | null;
  /** v0.16.1 체결 구멍 둘레 고정(SR-D-9) */
  setHold: (bead: number, v: 0 | 1) => void;
  hold: { ring_mm: number; blend_mm: number };
}

/** 섬 크기 상한 기본값(설정 select.island.max_mm 거울 — 서버가 settings 에 주면 그 값) */
export const ISLAND_MAX_MM = 40;

/** derive 응답 → 요소별 섬 주인 코드(beads[].islands 의 k, 없으면 islands_suggested 를 단 1 로). 섬이 없으면 null */
export function serverIslandMask(d: DoeDeriveOut | null, s: SelState | null, idx: ElemIndex | null, nElems: number): Int32Array | null {
  if (!d || !s || !idx) return null;
  const out = new Int32Array(nElems).fill(-1);
  let any = false;
  s.beads.forEach((b, bi) => {
    const x = d.beads.find((y) => y.id === b.id);
    if (x?.islands?.length) {
      for (const il of x.islands)
        for (const e of fromElemSet(il.elems, idx).elems) {
          out[e] = ownerCode(bi, Math.max(1, il.k));
          any = true;
        }
    } else if (d.islands_suggested?.[b.id]) {
      for (const e of fromElemSet(d.islands_suggested[b.id], idx).elems) {
        out[e] = ownerCode(bi, 1);
        any = true;
      }
    }
  });
  return any ? out : null;
}

const json = (x: unknown) => JSON.stringify(x);

/** [이 비드 초기화] 뒤 derive 에서 그 비드 결과(비드 행·사면 제안·그 비드 경고)만 뺌 — 다른 비드 결과는 그대로. 남는 비드가 없으면 null */
export function withoutBeadDerive(d: DoeDeriveOut | null, id: string): DoeDeriveOut | null {
  if (!d) return d;
  const beads = d.beads.filter((b) => b.id !== id);
  const sug = d.slope_suggested ? Object.fromEntries(Object.entries(d.slope_suggested).filter(([k]) => k !== id)) : d.slope_suggested;
  const warnings = d.warnings?.filter((w) => w.bead !== id && w.bead_id !== id);
  if (!beads.length) return null;
  return { ...d, beads, slope_suggested: sug, ...(warnings ? { warnings } : {}) };
}
// eslint-disable-next-line no-control-regex
const CTRL = /[\u0000-\u001f\u007f]/;

/** 선택 편집 상태(층·실행 취소·derive·저장본 비교) */
export function useBeadSelect(studyId: string, on: boolean, saved: DoeSelectionOut | null, st: DoeSettingsOut | null): BeadSelectCtrl {
  const { data, error } = useSelectData(studyId, on);
  const stRef = useRef<SelState | null>(null);
  const hist = useRef(new History<LayerName>());
  const stroke = useRef<Patch<LayerName> | null>(null);
  const [tick, setTick] = useState(0);
  const bump = useCallback(() => setTick((t) => t + 1), []);
  const [active, setActive] = useState(0);
  const [layer, setLayer] = useState<Layer | null>(null);
  const [featureAngle, setFeatureAngle] = useState<number>(st?.select?.feature_angle_deg ?? 15);
  const [derive, setDerive] = useState<DoeDeriveOut | null>(null);
  const [deriving, setDeriving] = useState(false);
  const [deriveError, setDeriveError] = useState<string | null>(null);
  const [baseJson, setBaseJson] = useState<string | null>(null);
  const loadedSha = useRef<string | null | undefined>(undefined);
  const maxBeads = st?.select?.max_beads ?? 20;
  const maxTiers = st?.select?.max_tiers ?? 6;
  const islandMax = (st?.select as { island?: { max_mm?: number } } | null | undefined)?.island?.max_mm ?? ISLAND_MAX_MM;
  const hold = st?.select?.hold ?? { ring_mm: 3, blend_mm: 8 };
  const [localIslands, setLocalIslands] = useState<SelIslands | null>(null);
  /** 편집 뒤 섬 다시 계산(브라우저 — 표시만) */
  const refreshIslands = useCallback(() => {
    const s = stRef.current;
    if (!s || !data) return;
    setLocalIslands(s.beads.length ? enclosedIslands(data.topo, s, data.glb.positions, islandMax) : null);
  }, [data, islandMax]);

  const input = useCallback((): DoeSelectionIn | null => {
    const s = stRef.current;
    if (!s || !data) return null;
    return toSelectionIn(s, data.bin.elemId, data.bin.elemType, featureAngle);
  }, [data, featureAngle]);

  const doDerive = useCallback(
    (sel: DoeSelectionIn | null) => {
      if (!sel || !sel.beads.length) return;
      setDeriving(true);
      setDeriveError(null);
      doe
        .derive(studyId, sel)
        .then((d) => {
          setDerive(d);
          setLocalIslands(null); // 서버 islands 가 표시를 대체(SR-D-14)
        })
        .catch((e) => setDeriveError(errorText(e)))
        .finally(() => setDeriving(false));
    },
    [studyId],
  );

  // 저장본 → 화면 상태: 처음 1회 불러옴. 저장 직후(화면 = 새 저장본)는 기준만 바꾸고, 저장 안 한 편집이 있으면 덮지 않는다
  useEffect(() => {
    if (!data) return;
    const sha = saved?.sha256 ?? null;
    if (loadedSha.current === sha) return;
    loadedSha.current = sha;
    const n = data.manifest.n_elems;
    const fromSaved = saved ? fromSelectionIn(saved.input, data.idx, n).state : null;
    const savedIn = fromSaved && saved ? toSelectionIn(fromSaved, data.bin.elemId, data.bin.elemType, saved.input.feature_angle_deg) : null;
    const savedJson = savedIn ? json(savedIn) : null;
    const cur = stRef.current ? input() : null;
    const curJ = cur ? json(cur) : null;
    if (stRef.current && (curJ === savedJson || (baseJson !== null && curJ !== baseJson))) {
      setBaseJson(savedJson);
      bump();
      return;
    }
    stRef.current = fromSaved ?? emptyState(n);
    if (saved) setFeatureAngle(saved.input.feature_angle_deg);
    setBaseJson(savedJson);
    setDerive(null);
    setLocalIslands(null);
    hist.current.clear();
    if (savedIn) doDerive(savedIn);
    setActive(0);
    setLayer(stRef.current.beads.length ? { kind: "tier", bead: 0, k: 1 } : null);
    bump();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, saved?.sha256]);

  const curJson = useMemo(() => {
    const x = input();
    return x ? json(x) : null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input, tick]);
  const dirty = !!curJson && curJson !== baseJson;

  const problem = useMemo((): string | null => {
    const s = stRef.current;
    if (!s) return data ? null : error ? `선택 자료를 불러오지 못했습니다 — ${error}` : "선택 자료 불러오는 중…";
    if (!s.beads.length) return "[+ 비드] 로 비드를 만들고 바닥을 고르세요";
    const x = input();
    for (const b of x?.beads ?? []) {
      const nm = b.name.trim();
      if (!nm || nm.length > 32 || CTRL.test(nm)) return `${b.id.toUpperCase()}: 이름은 1~32자, 제어문자 없이`;
      const empty = b.tiers.find((t) => !t.floor.q.length && !t.floor.t.length);
      if (empty) return `${nm}: 단 ${empty.k} 바닥이 비었습니다 — 바닥 요소를 고르세요`;
    }
    return null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, data, error, input]);

  const sugMasks = useMemo(() => {
    const out = new Map<string, Uint8Array>();
    if (!derive || !data) return out;
    for (const [id, set] of Object.entries(derive.slope_suggested ?? {})) {
      const m = new Uint8Array(data.manifest.n_elems);
      for (const e of fromElemSet(set as DoeElemSet, data.idx).elems) m[e] = 1;
      out.set(id, m);
    }
    return out;
  }, [derive, data]);
  const suggested = useCallback((b: number) => {
    const id = stRef.current?.beads[b]?.id;
    return id ? sugMasks.get(id) ?? null : null;
  }, [sugMasks]);

  const paintElems = useCallback(
    (elems: number[], l: Layer, mode: "add" | "remove", merge = false) => {
      const s = stRef.current;
      if (!s || !elems.length) return;
      const p = paint(s, elems, l, mode, suggested);
      if (merge) {
        const cur = stroke.current ?? { changes: [] };
        cur.changes.push(...p.changes);
        stroke.current = cur;
      } else {
        hist.current.push(p);
        if (p.changes.length) refreshIslands();
      }
      bump();
    },
    [suggested, bump, refreshIslands],
  );
  const endStroke = useCallback(() => {
    if (stroke.current) {
      hist.current.push(stroke.current);
      if (stroke.current.changes.length) refreshIslands();
    }
    stroke.current = null;
    bump();
  }, [bump, refreshIslands]);
  /** 비드 목록이 바뀐 뒤(삭제·되돌리기): 지금 비드·층을 범위 안으로, derive(비드 id 기준)는 다시 계산하도록 비움 */
  const afterMeta = useCallback((pref?: number) => {
    const s = stRef.current;
    if (!s) return;
    setDerive(null);
    const n = s.beads.length;
    const a = n ? Math.min(Math.max(0, pref ?? 0), n - 1) : 0;
    setActive(a);
    setLayer((l) => {
      if (!n) return l && (l.kind === "fixed" || l.kind === "exclude") ? l : null;
      if (!l || l.kind === "fixed" || l.kind === "exclude") return l ?? { kind: "tier", bead: a, k: 1 };
      if (l.bead >= n) return { kind: "tier", bead: a, k: 1 };
      if (l.kind === "tier" && l.k > s.beads[l.bead].nTiers) return { kind: "tier", bead: l.bead, k: s.beads[l.bead].nTiers };
      return l;
    });
  }, []);
  const undo = useCallback(() => {
    const s = stRef.current;
    const p = hist.current.undo();
    if (s && p) {
      // 한 획 안 같은 요소가 여러 번 바뀌었으면 뒤에서부터 되돌린다
      applyPatch(s, { ...p, changes: [...p.changes].reverse() }, "undo");
      if (p.meta) afterMeta(active);
      refreshIslands();
      bump();
    }
  }, [bump, afterMeta, active, refreshIslands]);
  const redo = useCallback(() => {
    const s = stRef.current;
    const p = hist.current.redo();
    if (s && p) {
      applyPatch(s, p, "redo");
      if (p.meta) afterMeta(active);
      refreshIslands();
      bump();
    }
  }, [bump, afterMeta, active, refreshIslands]);

  const serverMask = useMemo(
    () => serverIslandMask(derive, stRef.current, data?.idx ?? null, data?.manifest.n_elems ?? 0),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [derive, data],
  );
  const ctrl: BeadSelectCtrl = {
    data,
    error,
    state: stRef.current,
    tick,
    active,
    setActive: (b) => {
      setActive(b);
      setLayer({ kind: "tier", bead: b, k: 1 });
    },
    layer,
    setLayer,
    featureAngle,
    setFeatureAngle: (v) => {
      setFeatureAngle(v);
      bump();
    },
    derive,
    deriving,
    deriveError,
    runDerive: () => doDerive(input()),
    dirty,
    problem,
    input,
    suggested,
    paintElems,
    endStroke,
    undo,
    redo,
    canUndo: hist.current.canUndo,
    canRedo: hist.current.canRedo,
    addBead: () => {
      const s = stRef.current;
      if (!s) return;
      const b = addBead(s, maxBeads, 1); // Q1 = A: 폭 변경 시 바닥도 따라감(floor_follow 1)
      if (b === null) return;
      setActive(b);
      setLayer({ kind: "tier", bead: b, k: 1 });
      bump();
    },
    addTier: () => {
      const s = stRef.current;
      if (!s) return;
      const k = addTier(s, active, maxTiers);
      if (k === null) return;
      setLayer({ kind: "tier", bead: active, k });
      bump();
    },
    link: (b, a, c) => {
      const s = stRef.current;
      if (!s?.beads[b]) return;
      toggleLink(s.beads[b], a, c);
      bump();
    },
    rename: (b, name) => {
      const s = stRef.current;
      if (!s?.beads[b]) return;
      s.beads[b].name = name;
      bump();
    },
    setBlend: (id, v) => {
      const b = stRef.current?.beads.find((x) => x.id === id);
      if (!b) return;
      b.blend = v;
      bump();
    },
    blendOf: (id) => stRef.current?.beads.find((x) => x.id === id)?.blend ?? null,
    ring: (dir) => {
      const s = stRef.current;
      if (!s || !data) return;
      const sug = suggested(active);
      const slope = effectiveSlope(s, active, sug);
      const inB = (e: number) => ownerBead(s.owner[e]) === active || !!slope[e];
      // +1 = 비드 밖(다른 비드 아님) 요소를 사면에 더함, −1 = 경계에 닿은 사면 요소를 뺌(바닥은 그대로)
      const cand = dir === 1 ? (e: number) => s.owner[e] < 0 : (e: number) => !!slope[e] && (s.owner[e] < 0 || s.owner[e] === active * 16);
      const elems = ringStep(data.topo, inB, dir, cand);
      if (!elems.length) return;
      paintElems(elems, { kind: "slope", bead: active }, dir === 1 ? "add" : "remove");
    },
    clearLayer: () => {
      const s = stRef.current;
      if (!s || !layer) return;
      hist.current.push(clearLayer(s, layer, suggested));
      refreshIslands();
      bump();
    },
    deleteBead: (b) => {
      const s = stRef.current;
      if (!s) return;
      const p = deleteBead(s, b);
      if (!p) return;
      hist.current.push(p);
      afterMeta(b > 0 ? b - 1 : 0);
      refreshIslands();
      bump();
    },
    deleteTier: (b) => {
      const s = stRef.current;
      if (!s) return;
      const p = deleteLastTier(s, b);
      if (!p) return;
      hist.current.push(p);
      afterMeta(b);
      refreshIslands();
      bump();
    },
    resetBead: (b) => {
      const s = stRef.current;
      if (!s) return;
      const p = resetBead(s, b);
      if (!p) return;
      hist.current.push(p);
      const id = s.beads[b]?.id;
      if (id) setDerive((d) => withoutBeadDerive(d, id));   // 그 비드의 사면 제안·D·W 도 비움(다시 계산 전까지)
      refreshIslands();
      bump();
    },
    resetAll: () => {
      const s = stRef.current;
      if (!s) return;
      hist.current.push(resetAll(s));
      afterMeta(0);
      setLocalIslands(null);
      bump();
    },
    maxBeads,
    maxTiers,
    islandMask: localIslands ? localIslands.owner : serverMask,
    localIslands,
    setHold: (bi, v) => {
      const b = stRef.current?.beads[bi];
      if (!b) return;
      b.holdFixed = v;
      bump();
    },
    hold,
  };
  return ctrl;
}

// ================================================================ ② 3D 선택
const TOOL_NAME: Record<Tool, string> = { click: "클릭+확장", brush: "브러시", rect: "사각", lasso: "올가미" };

export function layerLabel(s: SelState, l: Layer): string {
  if (l.kind === "fixed") return "고정";
  if (l.kind === "exclude") return "제외(사면 자동에서 뺌)";
  const b = s.beads[l.bead];
  const n = b?.name ?? `B${l.bead + 1}`;
  return l.kind === "tier" ? `${n} · 단 ${l.k} 바닥` : `${n} · 사면`;
}
const layerKey = (l: Layer | null) => (!l ? "" : l.kind === "tier" ? `t:${l.bead}:${l.k}` : l.kind === "slope" ? `s:${l.bead}` : l.kind);
function parseLayer(k: string): Layer | null {
  const [a, b, c] = k.split(":");
  if (a === "t") return { kind: "tier", bead: Number(b), k: Number(c) };
  if (a === "s") return { kind: "slope", bead: Number(b) };
  if (a === "fixed" || a === "exclude") return { kind: a };
  return null;
}

function Select3D({ ctrl, editable, tool, brushPx, visibleOnly, eraser }: { ctrl: BeadSelectCtrl; editable: boolean; tool: Tool; brushPx: number; visibleOnly: boolean; eraser: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const overlay = useRef<HTMLCanvasElement>(null);
  const sceneRef = useRef<SceneApi | null>(null);
  const [phase, setPhase] = useState<"idle" | "loading" | "ready" | "nowebgl" | "error">("idle");
  const [msg, setMsg] = useState<string | null>(null);
  const data = ctrl.data;
  const modelBbox = useMemo(() => (data ? positionsBbox(data.glb.positions) : null), [data]);
  /** 선택 맞춤: 지금 비드(바닥 + 사면) 요소, 없으면 고른 모든 비드 요소 */
  const selectionBbox = () => {
    const st = ctrl.state;
    if (!st || !data) return null;
    const { positions, indices } = data.glb;
    const t2e = data.bin.tri2elem;
    if (st.beads[ctrl.active]) {
      const slope = effectiveSlope(st, ctrl.active, ctrl.suggested(ctrl.active));
      const b = elemsBbox(positions, indices, t2e, (e) => ownerBead(st.owner[e]) === ctrl.active || !!slope[e]);
      if (b) return b;
    }
    return elemsBbox(positions, indices, t2e, (e) => st.owner[e] >= 0);
  };

  useEffect(() => {
    if (!data) return;
    if (!hasWebGL()) {
      setPhase("nowebgl");
      return;
    }
    let cancelled = false;
    let scene: SceneApi | null = null;
    let canvas: HTMLCanvasElement | null = null;
    setPhase("loading");
    void (async () => {
      try {
        const mod = await loadScene();
        if (cancelled || !host.current) return;
        canvas = document.createElement("canvas");
        canvas.className = "v3d-canvas";
        host.current.insertBefore(canvas, host.current.firstChild);
        const { min: mn, max: mx } = modelBbox!;
        const diag = Math.hypot(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]) || 1;
        scene = mod.createScene(canvas, { background: BACKGROUND, diag, bbox: { min: mn, max: mx }, projection: "ortho" });
        if (!scene.setElements) throw new Error(NO_3D);
        scene.setGeometry({ positions: data.glb.positions, indices: data.glb.indices, src: null }, null);
        scene.setElements(data.bin.tri2elem, data.manifest.n_elems);
        sceneRef.current = scene;
        setPhase("ready");
      } catch (e) {
        if (!cancelled) {
          setPhase("error");
          setMsg(e instanceof Error && e.message === NO_3D ? NO_3D : errorText(e));
        }
      }
    })();
    return () => {
      cancelled = true;
      sceneRef.current = null;
      scene?.dispose();
      canvas?.remove();
    };
  }, [data]);

  // 요소 색·경계선(상태가 바뀔 때마다)
  const s = ctrl.state;
  useEffect(() => {
    const sc = sceneRef.current;
    if (!sc || !s || !data || phase !== "ready") return;
    sc.setElemColors?.(elemColors(s, ctrl.active, ctrl.suggested, ctrl.islandMask));
    if (s.beads[ctrl.active]) {
      const slope = effectiveSlope(s, ctrl.active, ctrl.suggested(ctrl.active));
      const pairs = boundaryEdges(data.topo, (e) => ownerBead(s.owner[e]) === ctrl.active || !!slope[e]);
      const pos = data.glb.positions;
      const segs = new Float32Array(pairs.length * 3);
      for (let i = 0; i < pairs.length; i++) for (let c = 0; c < 3; c++) segs[i * 3 + c] = pos[pairs[i] * 3 + c];
      sc.setOverlayLines?.(segs);
    } else sc.setOverlayLines?.(null);
  }, [ctrl.tick, ctrl.active, ctrl.suggested, ctrl.islandMask, phase, s, data]);

  // ---- 입력: 그리기 도구(왼쪽 끌기) · 클릭+확장 · 더블클릭 중심
  const strokeRef = useRef<{ mode: "add" | "remove"; start: Pt; pts: Pt[]; centroids: Float32Array | null } | null>(null);
  const downRef = useRef<{ x: number; y: number } | null>(null);
  const local = (e: { clientX: number; clientY: number }): Pt => {
    const r = host.current!.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };
  const drawOverlay = (kind: "brush" | "rect" | "lasso" | "none", pts: Pt[], at?: Pt) => {
    const cv = overlay.current;
    if (!cv || !host.current) return;
    const w = host.current.clientWidth;
    const h = host.current.clientHeight;
    if (cv.width !== w || cv.height !== h) {
      cv.width = w;
      cv.height = h;
    }
    const g = cv.getContext("2d");
    if (!g) return;
    g.clearRect(0, 0, w, h);
    g.strokeStyle = "#111";
    g.fillStyle = "rgba(29,91,191,0.12)";
    g.lineWidth = 1.5;
    g.setLineDash(kind === "brush" ? [] : [5, 4]);
    if (kind === "brush" && at) {
      g.beginPath();
      g.arc(at[0], at[1], brushPx, 0, Math.PI * 2);
      g.fill();
      g.stroke();
    } else if (kind === "rect" && pts.length === 2) {
      const r = rectOf(pts[0], pts[1]);
      g.fillRect(r.x, r.y, r.w, r.h);
      g.strokeRect(r.x, r.y, r.w, r.h);
    } else if (kind === "lasso" && pts.length > 1) {
      g.beginPath();
      g.moveTo(pts[0][0], pts[0][1]);
      for (const p of pts) g.lineTo(p[0], p[1]);
      g.closePath();
      g.fill();
      g.stroke();
    }
  };
  /** 판정 함수 · bbox → 요소(보이는 면만 = ID 버퍼, 아니면 중심 투영) */
  const elemsIn = (test: (x: number, y: number) => boolean, bbox: { x: number; y: number; w: number; h: number }) => {
    const sc = sceneRef.current;
    if (!sc || !data) return [];
    if (visibleOnly) return sc.idBuffer ? idsInMask(sc.idBuffer(bbox), test) : [];
    const st = strokeRef.current;
    const c = st?.centroids ?? sc.projectCentroids?.(data.topo.centroids) ?? null;
    if (st && !st.centroids) st.centroids = c;
    return c ? centroidsInMask(c, test) : [];
  };
  const brushAt = (p: Pt, mode: "add" | "remove") => {
    if (!ctrl.layer) return;
    const r = brushPx;
    const elems = elemsIn((x, y) => inCircle(x, y, p[0], p[1], r), { x: p[0] - r, y: p[1] - r, w: 2 * r + 1, h: 2 * r + 1 });
    ctrl.paintElems(elems, ctrl.layer, mode, true);
  };
  const canDraw = editable && phase === "ready" && !!ctrl.layer;
  const onDownCapture = (e: RPointerEvent<HTMLDivElement>) => {
    downRef.current = { x: e.clientX, y: e.clientY };
    if (!canDraw || tool === "click" || e.button !== 0 || e.ctrlKey || e.metaKey) return;
    // 그리기: Trackball 이 받지 않도록 캡처 단계에서 멈춤
    e.stopPropagation();
    e.preventDefault();
    host.current?.setPointerCapture?.(e.pointerId);
    const p = local(e);
    strokeRef.current = { mode: e.altKey || eraser ? "remove" : "add", start: p, pts: [p], centroids: null };
    if (tool === "brush") {
      brushAt(p, strokeRef.current.mode);
      drawOverlay("brush", [], p);
    }
  };
  const onMove = (e: RPointerEvent<HTMLDivElement>) => {
    const p = local(e);
    const st = strokeRef.current;
    if (!st) {
      if (canDraw && tool === "brush") drawOverlay("brush", [], p);
      return;
    }
    if (tool === "brush") {
      brushAt(p, st.mode);
      drawOverlay("brush", [], p);
    } else if (tool === "rect") drawOverlay("rect", [st.start, p]);
    else {
      st.pts.push(p);
      drawOverlay("lasso", st.pts);
    }
  };
  const onUp = (e: RPointerEvent<HTMLDivElement>) => {
    const st = strokeRef.current;
    const down = downRef.current;
    downRef.current = null;
    if (st) {
      strokeRef.current = null;
      const p = local(e);
      if (ctrl.layer && tool === "rect") {
        const r = rectOf(st.start, p);
        if (r.w > 1 && r.h > 1) ctrl.paintElems(elemsIn((x, y) => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h, r), ctrl.layer, st.mode, true);
      } else if (ctrl.layer && tool === "lasso" && st.pts.length > 2) {
        const poly = st.pts;
        ctrl.paintElems(elemsIn((x, y) => pointInPolygon(x, y, poly), polyBounds(poly)), ctrl.layer, st.mode, true);
      }
      ctrl.endStroke();
      drawOverlay(tool === "brush" ? "brush" : "none", [], p);
      return;
    }
    // 클릭+확장: 끌지 않은 왼쪽 클릭
    if (!canDraw || tool !== "click" || e.button !== 0 || !down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4) return;
    const sc = sceneRef.current;
    const hit = sc?.pickElem?.(e.clientX, e.clientY);
    if (!hit || !ctrl.state || !data || !ctrl.layer) return;
    const l = ctrl.layer;
    const s2 = ctrl.state;
    const own = l.kind === "tier" || l.kind === "slope" ? l.bead : -1;
    const elems = grow(data.topo, hit.elem, ctrl.featureAngle, own >= 0 ? (x) => s2.owner[x] >= 0 && ownerBead(s2.owner[x]) !== own : undefined);
    ctrl.paintElems(elems, l, e.altKey || eraser ? "remove" : "add");
  };
  const onDouble = (e: React.MouseEvent<HTMLDivElement>) => {
    const sc = sceneRef.current;
    const hit = sc?.pickElem?.(e.clientX, e.clientY);
    if (hit) sc!.focus(hit.point);
  };
  const onKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    if (e.key === "z" || e.key === "Z") {
      e.preventDefault();
      if (e.shiftKey) ctrl.redo();
      else ctrl.undo();
    } else if (e.key === "y" || e.key === "Y") {
      e.preventDefault();
      ctrl.redo();
    }
  };

  return (
    <div className="v3d-stage">
      <div
        ref={host}
        className={`v3d-host bs-host tool-${tool}${eraser ? " erasing" : ""}`}
        data-testid="bs-host"
        data-phase={phase}
        tabIndex={0}
        onPointerDownCapture={onDownCapture}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerLeave={() => !strokeRef.current && drawOverlay("none", [])}
        onDoubleClick={onDouble}
        onKeyDown={onKey}
        aria-label="비드 선택 3D"
      >
        <canvas ref={overlay} className="bs-overlay" aria-hidden="true" />
      </div>
      {phase === "ready" && modelBbox && <ViewToolbar scene={() => sceneRef.current} modelBbox={modelBbox} selectionBbox={selectionBbox} keyTarget={host} />}
      {(phase === "nowebgl" || phase === "error") && (
        <div className="v3d-msg" role="status" data-testid="bs-unavailable">
          {phase === "error" && msg && msg !== NO_3D ? msg : NO_3D}
        </div>
      )}
      {(phase === "loading" || (!data && !ctrl.error)) && <div className="v3d-msg muted">3D 형상 불러오는 중…</div>}
      {ctrl.error && !data && (
        <div className="v3d-msg" role="alert">
          {ctrl.error}
        </div>
      )}
    </div>
  );
}

/** ② 비드 선택 + ③ 비드 목록·도구(§11.1) */
export function BeadSelectCards({ ctrl, editable, st, fixedMissing }: { ctrl: BeadSelectCtrl; editable: boolean; st: DoeSettingsOut | null; fixedMissing: boolean }) {
  const [tool, setTool] = useState<Tool>("click");
  const [brushPx, setBrushPx] = useState(20);
  const [visibleOnly, setVisibleOnly] = useState(true);
  const [eraser, setEraser] = useState(false);
  const s = ctrl.state;
  const layers: Layer[] = s
    ? [...s.beads.flatMap((b, bi) => [...Array.from({ length: b.nTiers }, (_, i): Layer => ({ kind: "tier", bead: bi, k: i + 1 })), { kind: "slope", bead: bi } as Layer]), { kind: "fixed" }, { kind: "exclude" }]
    : [];
  const ro = !editable;
  const noBead = !s?.beads.length;
  return (
    <div className="bs-grid">
      <Card title="② 비드 선택" right={<span className="small muted">{ctrl.data ? `요소 ${ctrl.data.manifest.n_elems.toLocaleString()} · 노드 ${ctrl.data.manifest.n_nodes.toLocaleString()}` : ""}</span>}>
        {fixedMissing && (
          <div className="warn-box small" role="alert" data-testid="bs-fixed-missing">
            체결 정보 없음 — 체결부를 고정으로 칠하세요(③ [고정 칠하기])
          </div>
        )}
        <div className="bs-tools" role="toolbar" aria-label="선택 도구">
          <span className="seg" role="radiogroup" aria-label="도구">
            {(Object.keys(TOOL_NAME) as Tool[]).map((t) => (
              <button key={t} type="button" role="radio" aria-checked={tool === t} className={`btn small ghost toggle${tool === t ? " on" : ""}`} onClick={() => setTool(t)} disabled={ro}>
                {TOOL_NAME[t]}
              </button>
            ))}
          </span>
          {tool === "brush" && (
            <label className="range-field">
              <span>브러시</span>
              <input type="range" min={4} max={80} step={1} value={brushPx} aria-label="브러시 크기(px)" onChange={(e) => setBrushPx(Number(e.target.value))} />
              <span className="mono small range-val">{brushPx}px</span>
            </label>
          )}
          <label className="field-inline">
            <span>층</span>
            <select aria-label="대상 층" value={layerKey(ctrl.layer)} disabled={ro || noBead} onChange={(e) => {
              const l = parseLayer(e.target.value);
              if (l) {
                ctrl.setLayer(l);
                if (l.kind === "tier" || l.kind === "slope") ctrl.setActive(l.bead), ctrl.setLayer(l);
              }
            }}>
              {noBead && <option value="">비드 없음 — [+ 비드]</option>}
              {s && layers.map((l) => (
                <option key={layerKey(l)} value={layerKey(l)}>
                  {layerLabel(s, l)}
                </option>
              ))}
            </select>
          </label>
          <label className="check-field" title="체크 = 화면에 보이는 면만 고름(가려진 뒷면 제외), 해제 = 관통 선택">
            <input type="checkbox" checked={visibleOnly} onChange={(e) => setVisibleOnly(e.target.checked)} />
            <span>보이는 면만</span>
          </label>
          <label className="field-inline" title="클릭+확장·사면 자동의 같은 법선 판정 각">
            <span>feature</span>
            <input type="number" className="doe-num short" min={1} max={45} step={0.5} aria-label="feature angle(°)" value={ctrl.featureAngle} disabled={ro} onChange={(e) => {
              const v = Number(e.target.value);
              if (v >= 1 && v <= 45) ctrl.setFeatureAngle(v);
            }} />
            <span className="small muted">°</span>
          </label>
          <span className="bs-tool-group">
            <button type="button" className={`btn small ghost icon toggle${eraser ? " on" : ""}`} aria-pressed={eraser} aria-label="지우개" onClick={() => setEraser((x) => !x)} disabled={ro || noBead && ctrl.layer?.kind !== "fixed"} title={ro ? RO_TIP : "지우개: 켜면 클릭·끌기가 지금 층에서 빼기(Alt 와 같음)"} data-testid="bs-eraser">
              <EraserIcon />
            </button>
            <button type="button" className="btn small ghost" onClick={() => {
              if (!s || !ctrl.layer) return;
              if (window.confirm(`'${layerLabel(s, ctrl.layer)}' 층의 요소를 모두 비웁니다. 실행 취소(Ctrl+Z)로 되돌릴 수 있습니다.`)) ctrl.clearLayer();
            }} disabled={ro || !ctrl.layer} title={ro ? RO_TIP : "지금 층(단 바닥·사면·고정·제외)의 요소를 모두 비웁니다(실행 취소 가능)"}>
              층 비우기
            </button>
            <button type="button" className="btn small" onClick={ctrl.runDerive} disabled={ro || noBead || ctrl.deriving} title="서버가 사면 요소·경계선·공칭 깊이·폭을 계산합니다(저장 안 함)">
              {ctrl.deriving ? "계산 중…" : "사면·경계 자동"}
            </button>
            <button type="button" className="btn small ghost" onClick={() => ctrl.ring(1)} disabled={ro || noBead} title="경계 바깥 한 줄을 사면에 더합니다">
              경계 +1줄
            </button>
            <button type="button" className="btn small ghost" onClick={() => ctrl.ring(-1)} disabled={ro || noBead} title="경계에 닿은 사면 한 줄을 뺍니다">
              −1줄
            </button>
            <button type="button" className="btn small ghost icon" onClick={ctrl.undo} disabled={ro || !ctrl.canUndo} aria-label="실행 취소" title="실행 취소(Ctrl+Z)">
              ↶
            </button>
            <button type="button" className="btn small ghost icon" onClick={ctrl.redo} disabled={ro || !ctrl.canRedo} aria-label="다시 실행" title="다시 실행(Ctrl+Y)">
              ↷
            </button>
          </span>
        </div>
        <Select3D ctrl={ctrl} editable={editable} tool={tool} brushPx={brushPx} visibleOnly={visibleOnly} eraser={eraser} />
        <div className="small muted bs-hint" data-testid="bs-hint">
          {eraser ? "지우개 켜짐: 클릭·끌기 = 지금 층에서 빼기(다시 누르면 더하기) · " : ""}
          {tool === "click" ? "클릭 = 같은 법선·연결 요소로 확장해 더하기 · Alt+클릭 또는 지우개 = 빼기 · 끌기 = 회전" : "끌기 = 칠하기 · Shift = 더하기 · Alt 또는 지우개 = 빼기 · Ctrl+끌기 = 회전"} · 층 비우기·비드 ✕·단 삭제 · Ctrl+Z = 실행 취소 · 오른쪽 끌기 = 이동 · 휠 = 확대 · 더블클릭 = 중심 · 색: 단 = 파랑 계열(밝은 단계 = 섬 — 바닥과 같이 이동), 사면 = 주황(연한 주황 = 자동 제안), 고정 = 진회색, 경계 = 검은 선
        </div>
        <ErrorLine text={ctrl.deriveError} />
      </Card>
      <Card title="③ 비드 목록·도구">
        <BeadList ctrl={ctrl} editable={editable} st={st} />
      </Card>
    </div>
  );
}

// ================================================================ 미리보기 안 3D 보기(§7.3) — 썸네일 클릭
export function SelectDesign3D({ studyId, rev, did, values, vmax, onClose, fixedViol }: { studyId: string; rev: number; did: string; values: Record<string, number>; vmax: number; onClose: () => void; fixedViol?: DoeFixedViol | null }) {
  const host = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<SceneApi | null>(null);
  const [phase, setPhase] = useState<"loading" | "ready" | "nowebgl" | "error">("loading");
  const [err, setErr] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<{ glb: ParsedGlb; vars: BasisVar[]; meta: DoeBasisMeta } | null>(null);
  const [showDesign, setShowDesign] = useState(true);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    let alive = true;
    setLoaded(null);
    setErr(null);
    void (async () => {
      try {
        const meta = await doe.basisMeta(studyId, rev);
        const [g, b] = await Promise.all([fetchBinary(doe.selectViewUrl(studyId, "part.glb")), fetchBinary(doe.basisUrl(studyId, rev))]);
        const glb = parseGlb(g);
        if (alive) setLoaded({ glb, vars: parseBasis(b, meta, meta.n_nodes ?? glb.positions.length / 3), meta });
      } catch (e) {
        if (alive) {
          setErr(errorText(e));
          setPhase("error");
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [studyId, rev]);

  const n = loaded ? loaded.glb.positions.length / 3 : 0;
  const u = useMemo(() => (loaded ? morph(loaded.vars, values, n) : null), [loaded, values, n]);
  const c = useMemo(() => (loaded ? heightChange(loaded.vars, values, n) : null), [loaded, values, n]);
  const V = vmax > 0 ? vmax : Math.max(1, c ? maxAbs(c) : 1);
  const designBbox = useMemo(() => (loaded ? positionsBbox(loaded.glb.positions) : null), [loaded]);
  /** 선택 맞춤 = 기저가 움직이는 노드(비드 + 블렌딩) bbox */
  const beadBbox = useMemo(() => {
    if (!loaded) return () => null;
    const p = loaded.glb.positions;
    const mn = [Infinity, Infinity, Infinity];
    const mx = [-Infinity, -Infinity, -Infinity];
    let any = false;
    for (const v of loaded.vars)
      for (const i of v.idx) {
        any = true;
        for (let k = 0; k < 3; k++) (mn[k] = Math.min(mn[k], p[i * 3 + k])), (mx[k] = Math.max(mx[k], p[i * 3 + k]));
      }
    const b = any ? { min: mn, max: mx } : null;
    return () => b;
  }, [loaded]);

  useEffect(() => {
    if (!loaded) return;
    if (!hasWebGL()) {
      setPhase("nowebgl");
      return;
    }
    let cancelled = false;
    let scene: SceneApi | null = null;
    let canvas: HTMLCanvasElement | null = null;
    void (async () => {
      try {
        const mod = await loadScene();
        if (cancelled || !host.current) return;
        canvas = document.createElement("canvas");
        canvas.className = "v3d-canvas";
        host.current.appendChild(canvas);
        const { min: mn, max: mx } = positionsBbox(loaded.glb.positions);
        scene = mod.createScene(canvas, { background: BACKGROUND, diag: Math.hypot(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]) || 1, bbox: { min: mn, max: mx }, projection: "ortho" });
        scene.setGeometry({ positions: loaded.glb.positions, indices: loaded.glb.indices, src: null }, null);
        scene.setColorMap?.("diverging");
        sceneRef.current = scene;
        setPhase("ready");
      } catch (e) {
        if (!cancelled) {
          setErr(errorText(e));
          setPhase("error");
        }
      }
    })();
    return () => {
      cancelled = true;
      sceneRef.current = null;
      scene?.dispose();
      canvas?.remove();
    };
  }, [loaded]);

  useEffect(() => {
    const sc = sceneRef.current;
    if (!sc || phase !== "ready" || !u || !c) return;
    sc.setColors(showDesign ? c : new Float32Array(c.length), -V, V);
    sc.setDeform(showDesign ? u : null, scale);
    // v0.15.1 침범한 고정 노드 = 빨간 점(지금 보이는 형상 위치)
    const ids = fixedViol?.node_idx ?? [];
    if (sc.setMarkers) {
      if (!ids.length || !loaded) sc.setMarkers(null);
      else {
        const p = loaded.glb.positions;
        const pts = new Float32Array(ids.length * 3);
        ids.forEach((i, k) => {
          for (let d = 0; d < 3; d++) pts[k * 3 + d] = p[i * 3 + d] + (showDesign ? u[i * 3 + d] * scale : 0);
        });
        sc.setMarkers(pts);
      }
    }
  }, [phase, u, c, showDesign, scale, V, fixedViol, loaded]);

  return (
    <Card title={`안 ${did} 3D 보기`} right={<button type="button" className="btn small ghost" onClick={onClose}>닫기</button>}>
      <div className="v3d">
        <div className="v3d-tools">
          <span className="seg" role="radiogroup" aria-label="형상">
            <button type="button" role="radio" aria-checked={!showDesign} className={`btn small ghost toggle${!showDesign ? " on" : ""}`} onClick={() => setShowDesign(false)}>
              공칭
            </button>
            <button type="button" role="radio" aria-checked={showDesign} className={`btn small ghost toggle${showDesign ? " on" : ""}`} onClick={() => setShowDesign(true)}>
              안 {did}
            </button>
          </span>
          <label className="field-inline" title="화면 표시용 확대(값·판정 영향 없음)">
            <span>크게 보기</span>
            <select aria-label="변형 배율" value={scale} onChange={(e) => setScale(Number(e.target.value))}>
              {[1, 2, 5].map((k) => (
                <option key={k} value={k}>
                  ×{k}
                </option>
              ))}
            </select>
          </label>
          <span className="small muted mono">{Object.entries(values).map(([k, v]) => `${k.replace("_", " ")} ${v}`).join(" · ")}</span>
        </div>
        {fixedViol && fixedViol.n > 0 && (
          <div className="small warn-text" data-testid="design-fixed-viol">
            <span className="fixed-dot" aria-hidden="true" /> 빨간 점 = 움직인 고정 노드 {fixedViol.n.toLocaleString()}개(최대 {fixedViol.max_mm} mm)
            <FixedViolNote cells={[{ fixed_viol: fixedViol }]} testId="design-fixed-viol-row" />
          </div>
        )}
        <div className="v3d-stage">
          <div ref={host} className="v3d-host" data-testid="bs-design-host" data-phase={phase} tabIndex={0} aria-label={`안 ${did} 3D`} />
          {phase === "ready" && designBbox && <ViewToolbar scene={() => sceneRef.current} modelBbox={designBbox} selectionBbox={beadBbox} keyTarget={host} />}
          {(phase === "nowebgl" || phase === "error") && <div className="v3d-msg" role="status">{err ?? NO_3D}</div>}
          {phase === "loading" && <div className="v3d-msg muted">3D 형상 불러오는 중…</div>}
        </div>
        <HeightLegend vmax={V} />
      </div>
    </Card>
  );
}

function EraserIcon() {
  return (
    <svg width={14} height={14} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.4} aria-hidden="true">
      <path d="M9.5 2.5 14 7l-6.5 6.5H4L1.8 11.3a1 1 0 0 1 0-1.4z" />
      <path d="M6 6l4.5 4.5M7.5 13.5H14" />
    </svg>
  );
}

/** 높이 변화 범례 1개(파랑 = 깊어짐 · 빨강 = 얕아짐, 모든 칸 같은 ±V) */
export function HeightLegend({ vmax, unit = "mm" }: { vmax: number; unit?: string }) {
  const v = vmax.toFixed(vmax < 10 ? 1 : 0);
  return (
    <div className="bs-legend small" data-testid="height-legend">
      <span>공칭 대비 높이 변화</span>
      <span className="mono">−{v}</span>
      <i style={{ background: DIVERGING_GRADIENT }} aria-hidden="true" />
      <span className="mono">+{v} {unit}</span>
      <span className="muted">빨강 = 얕아짐 · 파랑 = 깊어짐</span>
    </div>
  );
}

export const beadWarnText = (w: { code: string; message?: string | null }) => warnText(w);
