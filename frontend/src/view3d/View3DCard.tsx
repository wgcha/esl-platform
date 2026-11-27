// ④ 3D 하중 보기 카드(계약 §5~§8). 컨트롤은 한 줄: 화살표 단계 · 변형 형상 · 배율 · 실제 크기 · 원근 · 맞춤.
// 원근 체크 해제 = 직교(기본). 선택은 브라우저별 localStorage(esl.v3d.projection.v1)에 기억.
// three 는 loadScene() 동적 import 로만 들어온다. WebGL 이 없거나 청크 적재가 실패하면 안내 문구만 보이고 표는 그대로.
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { errorText } from "../api/client";
import { Card } from "../components/ui";
import { ColorLegend, type LegendKind, type Range } from "../components/ColorLegend";
import { cssGradient, f3, mapFor } from "../lib/colormap";
import { N_STAGES, buildArrowSpecs, stageText, type ArrowSpec } from "./arrows";
import { EXP_MAX, EXP_MIN, EXP_STEP, defaultScaleExp, scaleFromExp, scaleLabel } from "./deform";
import { fetchBinary, fileUrls } from "./fetchFiles";
import { parseGlb, type ParsedGlb } from "./glb";
import { featureEdges } from "./edges";
import { infoLine, shortFieldName, type ProbeExtra } from "./info";
import { marksWanted } from "./marks";
import { LegendOverlay } from "./LegendOverlay";
import { LegendEditor, LegendPopover, type LegendEditorProps } from "./legend/LegendEditor";
import { COLOR_MODES, LEGEND_DEFAULTS, countOut, effectiveRange, formatValue, levelsOf, logAllowed, type ColorModeKey, type Range as LRange } from "./legend/legendModel";
import { cAutoRange, dcAutoRange, sceneExtras, type ScenePin } from "./sceneManifest";
import { ViewerChips, ViewerGear } from "./ViewerControls";
import { defaultPlanKey, effectiveLayers, planOf, usesLegendSync, usesPairSync } from "./viewerPlan";
import { useViewerStore, type ViewerSync } from "./viewerSync";
import { loadScene } from "./loadThree";
import { writeProjection, type Projection } from "./projection";
import { selectionFromPick, sceneSelection } from "./selection";
import type { SceneApi } from "./sceneApi";
import { PartStage } from "./part/PartStage";
import { buildSupportSpecs } from "./supports";
import { markLegend } from "./supportMarks";
import type { LoadView } from "./useLoadView";
import { fallbackAllowed, sourceRow, type LoadComp } from "./sources";
import { colorField, decodeValues, loadFieldOf, loadRangeTop, maxNorm3, type DecodedValues } from "./values";
import { hasWebGL } from "./webgl";

/** 색 모드 c·dc 의 기본 범례 제목(계약 §4.3) — 합 = C·ΔC 는 씬 manifest 의 float64 원값 */
export const C_LABEL = "C 기여도 F·u (N·mm) — 합 = C";
export const DC_LABEL = "C 기여도 차이 안 − 기준 (N·mm) — 합 = ΔC";
export const NO_C_TEXT = "이 3D 자료에는 C 기여도가 없습니다 — 씬 3D 를 만들면 볼 수 있습니다";
export const NO_DC_TEXT = "이 3D 자료에는 C 기여도 차이가 없습니다";
export const NO_3D_TEXT = "이 브라우저에서 3D 보기를 쓸 수 없습니다";
const BACKGROUND = "#dfe3e8";
/** 칸 폭이 이보다 좁으면(카드 < 620 px) 칩 글자를 "경계"·"하중"으로 줄임 */
const COMPACT_PX = 620;
/** umax 핀 기호·색(표시 전용 — 최대 표식 ● 주황과 구분) */
const PIN_SYMBOL = "◆";
const PIN_COLOR = "#1d4ed8";

interface Loaded {
  glb: ParsedGlb;
  vals: DecodedValues;
}

/** v0.9.0 비드 DOE 비교용 선택 옵션(esl_bead_doe.md §11 — 안 주면 기존 동작 그대로) */
export interface View3DOptions {
  /** 카드 제목(기본 "3D 하중 보기") */
  title?: string;
  /** 표면 색: load = 면압|Fn|/A(기본) · disp = 변위 |u| (mm) */
  colorBy?: "load" | "disp";
  /** v0.25.1 색 모드(계약 §4.3): disp 응답 변위 · load 하중 · c C 기여도(씬 값 c) · dc 차이(씬 값 dc, 0 중심 발산). 주면 colorBy 보다 앞선다.
   *  c·dc 인데 값 파일에 그 배열이 없으면 색을 칠하지 않고 안내 문구(호출부가 버튼을 비활성하는 것이 원칙) */
  colorMode?: "disp" | "load" | "c" | "dc";
  /** v0.25.1 범례 제목 문구를 직접 정함(예: "C 기여도 F·u (N·mm) — 합 = C"). 없으면 모드별 기본 문구 */
  colorLabel?: string;
  /** v0.25.1 umax 위치 핀(계약 §3.3·§4.3). 안 주면 값 파일 manifest 의 pins.umax 를 쓴다. null·{umax:null} = 핀 없음.
   *  ⚙/범례 편집의 `umax 위치` 체크(legend.upin)로 끌 수 있다 */
  pins?: { umax?: ScenePin | null } | null;
  /** 색 범위 고정(카드 여럿을 같은 범위로). 주면 이 값을 쓰고, 범위 입력·'자동'은 onRangeChange 로 알린다(null = 자동) */
  range?: Range | null;
  rangeManual?: boolean;
  /** 변위 색 범례 문구(기본 "변위 |u| (mm)") — v0.20.0 강체 제거 표기 */
  dispLabel?: string;
  onRangeChange?: (r: Range | null) => void;
  /** v0.23.3 지그 진단(esl_jig_view.md §7.2): 화살표를 manifest top/군집 대신 이 사양으로(영역 합력). 주면 화살표 단계 슬라이더 숨김 */
  arrowsOverride?: ArrowSpec[] | null;
  /** v0.23.3 표면 색을 이 정점 값으로(영역 색 — NaN = 회색). 범례 문구 label, 범위 min~max */
  fieldOverride?: { values: Float32Array; min: number; max: number; label: string; /** 색 역할(기본 region = 분류 — 범례 편집 비활성). seq = 값 컨투어 */ role?: "region" | "seq" } | null;
  /** v0.23.3 카드 여럿이 같은 변형 켜기·배율·실제 크기를 쓰게(공유 상태). 안 주면 카드마다 따로(기존) */
  deformSync?: { on: boolean; kexp: number | null; real: boolean; set: (s: { on?: boolean; kexp?: number | null; real?: boolean }) => void } | null;
  /** v0.23.3 지지 기호 색(정점 → 색, null = 기본) — 지그 노드 상대 부품별 */
  supportColor?: ((vertex: number) => string | null) | null;
  /** v0.24.1 카드 머리 오른쪽(제목 줄 — 새 줄 없음): Case ③ 출처 탭 */
  headRight?: ReactNode;
  /** v0.24.1 도구 줄 앞·끝에 붙일 요소(보기 세그먼트·하중 색 선택 / 재현 한 줄) — 새 블록 줄 없음 */
  toolsLead?: ReactNode;
  toolsTail?: ReactNode;
  /** v0.24.1 변위 색·변형·화살표 변형에 쓸 u(3n, mm) — 목표·재현·오차. 안 주면 values.bin u(=목표 u_rel) */
  dispOverride?: { u: Float32Array; label: string } | null;
  /** v0.24.1 하중 색 성분: pa 면압 · fn 법선 · fmag 크기. null/없음 = 지금 colorField(면압, 없으면 |Fn|) */
  loadField?: LoadComp | null;
  /** v0.24.6 뷰어 계획 키(viewerPlan.ts 표) — 층 기본값·기억·동기 종류. 안 주면 색 종류로 case_load / case_disp */
  plan?: string;
  /** v0.24.6 2카드 쌍이 공유하는 상태(시점·변형·층·범례 레벨). 주면 deformSync 는 무시 — 없으면 카드 자체 상태 */
  viewerSync?: ViewerSync | null;
}

/** 자동 범위가 서버에 없을 때(옛 manifest) 값에서 직접: 부호 없음 = [min(최소,0), max(최대,0)] · 대칭 = ±최대 절댓값. 퇴화 = 0~1(대칭 ±1) */
function dataRange(values: ArrayLike<number> | undefined, sym: boolean): Range {
  let lo = 0;
  let hi = 0;
  if (values) {
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      if (!Number.isFinite(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
  }
  if (sym) {
    const V = Math.max(Math.abs(lo), Math.abs(hi));
    return V > 0 ? { min: -V, max: V } : { min: -1, max: 1 };
  }
  return hi > lo ? { min: lo, max: hi } : { min: 0, max: 1 };
}

/** |u| (mm) 정점 값 */
function dispField(u: Float32Array | null): Float32Array | null {
  if (!u) return null;
  const out = new Float32Array(u.length / 3);
  for (let i = 0; i < out.length; i++) out[i] = Math.hypot(u[i * 3], u[i * 3 + 1], u[i * 3 + 2]);
  return out;
}

export function View3DCard({ view, options }: { view: LoadView; options?: View3DOptions }) {
  const colorBy: "load" | "disp" = options?.colorMode ? (options.colorMode === "disp" || options.colorMode === "dc" ? "disp" : "load") : options?.colorBy ?? "load";
  const { manifest, error, mode, selection, stage } = view;
  const host = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<SceneApi | null>(null);
  const [phase, setPhase] = useState<"idle" | "loading" | "ready" | "nowebgl" | "error">("idle");
  const [phaseErr, setPhaseErr] = useState<string | null>(null);
  const [data, setData] = useState<Loaded | null>(null);
  const planKey = options?.plan ?? defaultPlanKey(colorBy);
  const ownStore = useViewerStore(planKey);
  // 계획 표 열 sync: pair 인 보기만 쌍 상태를 공유한다(none 이면 호출부가 viewerSync 를 줘도 카드 자체 상태)
  const sync = options?.viewerSync && usesPairSync(planKey) ? options.viewerSync : null;
  const store = sync ?? ownStore;
  const st = store.state;
  // 계획 표 열 layers: 쓸 수 없는 층은 켜 둔 값이어도 꺼짐(장면·표식·선택 공통)
  const lay = effectiveLayers(planKey, st);
  const ds = sync ? null : options?.deformSync ?? null; // viewerSync 가 있으면 deformSync 무시(호환 유지)
  const deformOn = ds ? ds.on : st.deformOn;
  const real = ds ? ds.real : st.real;
  const kexp = ds ? ds.kexp : st.kexp;
  const setDeformOn = (f: (x: boolean) => boolean) => (ds ? ds.set({ on: f(ds.on) }) : store.set({ deformOn: f(st.deformOn) }));
  const setReal = (f: (x: boolean) => boolean) => (ds ? ds.set({ real: f(ds.real) }) : store.set({ real: f(st.real) }));
  const setKexp = (v: number) => (ds ? ds.set({ kexp: v }) : store.set({ kexp: v }));
  const proj = st.proj;
  const projRef = useRef(proj);
  projRef.current = proj;
  const uid = useId();
  const [hostBox, setHostBox] = useState({ w: 0, h: 0 });
  const staleRetried = useRef(false);
  const idRef = useRef(uid);
  const arrowKeysRef = useRef<string[]>([]);

  const diag = manifest?.bbox.diag ?? 1;
  const dov = options?.dispOverride ?? null;
  const n0 = manifest?.n_nodes ?? 0;
  const ovU = dov && dov.u.length === n0 * 3 ? dov.u : null;
  const umax = useMemo(() => (ovU ? maxNorm3(ovU) : manifest?.ranges.u_max ?? 0), [ovU, manifest]);
  // 기본 배율: 쌍(viewerSync)은 두 카드가 알린 값의 최대 기준(pairScaleExp — 적재 순서 무관), 카드 하나는 자기 manifest 기준
  const reportBasis = sync?.reportBasis;
  useEffect(() => {
    if (!manifest || !reportBasis) return;
    return reportBasis(idRef.current, { diag, umax });
  }, [manifest, reportBasis, diag, umax]);
  useEffect(() => {
    if (manifest && !sync && kexp === null) setKexp(defaultScaleExp(diag, umax));
  }, [manifest, sync, kexp, diag, umax]);
  const kexpEff = kexp ?? sync?.kexpDefault ?? null;
  const k = real ? 1 : scaleFromExp(kexpEff ?? 0);
  const uEff = ovU ?? data?.vals.u ?? null;
  const hasU = !!uEff;

  // ---- 장면·자료 적재 (manifest key 가 바뀔 때만)
  const mkey = manifest?.key ?? null;
  const runId = view.runId;
  useEffect(() => {
    if (!manifest) return;
    if (!hasWebGL()) {
      setPhase("nowebgl");
      return;
    }
    let cancelled = false;
    let scene: SceneApi | null = null;
    let canvas: HTMLCanvasElement | null = null;
    setPhase("loading");
    setPhaseErr(null);
    void (async () => {
      try {
        const urls = fileUrls(manifest);
        const [mod, glbBuf, valBuf, lodBuf] = await Promise.all([
          loadScene().catch(() => {
            throw new Error(NO_3D_TEXT);
          }),
          fetchBinary(urls.geometry),
          fetchBinary(urls.values),
          urls.lod ? fetchBinary(urls.lod) : Promise.resolve(null),
        ]);
        if (cancelled) return;
        const glb = parseGlb(glbBuf);
        if (glb.positions.length / 3 !== manifest.n_nodes) throw new Error("3D 형상의 정점 수가 manifest 와 다릅니다");
        const vals = decodeValues(valBuf, manifest);
        const lod = lodBuf ? parseGlb(lodBuf) : null;
        if (!host.current) return;
        canvas = document.createElement("canvas");
        canvas.className = "v3d-canvas";
        host.current.appendChild(canvas);
        try {
          scene = mod.createScene(canvas, { background: BACKGROUND, diag: manifest.bbox.diag, bbox: manifest.bbox, projection: projRef.current });
        } catch {
          throw new Error(NO_3D_TEXT);
        }
        scene.onPick((e) => view.setSelection(selectionFromPick(e, arrowKeysRef.current)));
        scene.setGeometry({ positions: glb.positions, indices: glb.indices, src: null }, lod ? { positions: lod.positions, indices: lod.indices, src: lod.src } : null);
        sceneRef.current = scene;
        setData({ glb, vals });
        setPhase("ready");
      } catch (e) {
        if (cancelled) return;
        if (e instanceof Error && (e as { code?: string }).code === "VIEW3D_STALE" && !staleRetried.current) {
          staleRetried.current = true;
          view.reload();
          return;
        }
        setPhase("error");
        setPhaseErr(e instanceof Error && e.message === NO_3D_TEXT ? NO_3D_TEXT : errorText(e));
      }
    })();
    return () => {
      cancelled = true;
      sceneRef.current = null;
      scene?.dispose();
      canvas?.remove();
      setData(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mkey, runId]);

  // ---- 투영(원근/직교): 전환 시 같은 시점 유지는 장면이 맡는다
  useEffect(() => {
    if (data && sceneRef.current) sceneRef.current.setProjection(proj);
  }, [data, proj]);
  const toggleProj = (persp: boolean) => {
    const p: Projection = persp ? "persp" : "ortho";
    store.set({ proj: p });
    writeProjection(p);
  };

  // ---- 표면 색(계약 §4.3·§5): 모드 표 COLOR_MODES 의 행 하나가 역할(레인보우·발산·분류)·로그 가능·범위 공유를 정한다.
  const fo = options?.fieldOverride ?? null;
  const loadComp = options?.loadField ?? null;
  const extras = useMemo(() => sceneExtras(manifest), [manifest]);
  const modeKey: ColorModeKey = fo ? (fo.role === "seq" ? "field" : "region") : options?.colorMode === "c" ? "c" : options?.colorMode === "dc" ? "dc" : colorBy === "disp" ? "disp" : "load";
  const modeRow = fo ? { ...COLOR_MODES[modeKey], editable: false } : COLOR_MODES[modeKey]; // 직접 준 영역 색(fieldOverride)은 범위·범례를 호출부가 정함
  const foOk = !!(fo && data && fo.values.length === data.glb.positions.length / 3);
  // 범례 모양: 쌍이 공유(legendSync) — 분류(하중 영역)는 편집 불가라 기본 모양(연속·끝색·뒤집기 없음)으로 고정
  const legendStore = sync && usesLegendSync(planKey) ? sync : ownStore;
  const lgAll = legendStore.state.legend;
  const lg = modeRow.editable ? lgAll : { ...LEGEND_DEFAULTS, continuous: true };
  const field = useMemo(() => {
    if (!data) return null;
    if (fo && foOk) return { values: fo.values, unit: "mm" as const };
    if (modeKey === "c") return data.vals.c ? { values: data.vals.c, unit: "N·mm" as const } : null;
    if (modeKey === "dc") return data.vals.dc ? { values: data.vals.dc, unit: "N·mm" as const } : null;
    if (colorBy === "disp") {
      const v = dispField(uEff);
      return v ? { values: v, unit: "mm" as const } : null;
    }
    return loadComp ? loadFieldOf(data.vals, loadComp) : colorField(data.vals);
  }, [data, colorBy, fo, foOk, modeKey, uEff, loadComp]);
  const unit: "MPa" | "N" | "mm" | "N·mm" = field?.unit ?? (modeKey === "c" || modeKey === "dc" ? "N·mm" : colorBy === "disp" ? "mm" : "MPa");
  // 자동 범위(이 카드 하나) — c = [min(p01,0), max(p99,0)] · dc = ±abs_p99 · disp = 0~최대 · load = 0~p99
  const autoOwn: LRange = useMemo(() => {
    if (fo) return { min: fo.min, max: fo.max };
    if (modeKey === "c") return cAutoRange(extras) ?? dataRange(field?.values, false);
    if (modeKey === "dc") return dcAutoRange(extras) ?? dataRange(field?.values, true);
    if (colorBy === "disp") return { min: 0, max: umax > 0 ? umax : 1 };
    if (!manifest) return { min: 0, max: 1 };
    return { min: 0, max: loadRangeTop(manifest.ranges, loadComp, unit === "MPa" ? "MPa" : "N") };
  }, [fo, modeKey, extras, field, manifest, unit, colorBy, umax, loadComp]);
  // 직접 입력 범위: 범위 공유 모드는 저장소(쌍 공유·기억 안 함), 차이처럼 안 공유하는 모드는 카드 자신
  const [locMan, setLocMan] = useState<{ min: number | null; max: number | null }>({ min: null, max: null });
  const hostR = options?.range ?? null;
  const manMin = hostR ? (options?.rangeManual ? hostR.min : null) : modeRow.pairRange ? legendStore.state.manMin : locMan.min;
  const manMax = hostR ? (options?.rangeManual ? hostR.max : null) : modeRow.pairRange ? legendStore.state.manMax : locMan.max;
  const reportRange = sync?.reportRange;
  useEffect(() => {
    // 쌍의 자동 범위 = 두 카드를 포함(합집합) — 값 종류가 같은 카드끼리만(차이 모드는 빠짐)
    if (!reportRange || !modeRow.pairRange || !field || hostR || !modeRow.editable) return;
    return reportRange(idRef.current, autoOwn);
  }, [reportRange, modeRow.pairRange, modeRow.editable, field, hostR, autoOwn.min, autoOwn.max]); // eslint-disable-line react-hooks/exhaustive-deps
  const base: LRange = hostR ?? (sync && modeRow.pairRange && sync.pairAuto && usesLegendSync(planKey) ? sync.pairAuto : autoOwn);
  const range: LRange = useMemo(() => {
    if (fo) return base;
    const max = manMax ?? base.max;
    const min = modeRow.sym ? -max : manMin ?? base.min;
    return max > min ? { min, max } : base;
  }, [fo, base, manMin, manMax, modeRow.sym]);
  const setRange = (p: { min?: number | null; max?: number | null }) => {
    const nMin = p.min !== undefined ? p.min : manMin;
    const nMax = p.max !== undefined ? p.max : manMax;
    if (options?.onRangeChange && hostR) {
      if (nMin === null && nMax === null) options.onRangeChange(null);
      else {
        const max = nMax ?? range.max;
        options.onRangeChange({ min: modeRow.sym ? -max : nMin ?? range.min, max });
      }
    } else if (modeRow.pairRange) legendStore.set({ manMin: nMin, manMax: nMax });
    else setLocMan({ min: nMin, max: nMax });
  };
  // 값 종류·단위가 바뀌면 직접 입력 범위를 버린다(뜻이 달라 다음에 잘못 적용됨 — 계약 §5.6)
  const scopeKey = `${modeKey}:${unit}`;
  const scopeRef = useRef(scopeKey);
  useEffect(() => {
    if (scopeRef.current === scopeKey) return;
    scopeRef.current = scopeKey;
    setLocMan({ min: null, max: null });
    if (legendStore.state.manMin !== null || legendStore.state.manMax !== null) legendStore.set({ manMin: null, manMax: null });
  }, [scopeKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const wantLog = lg.scale === "log" && logAllowed(modeRow, range);
  const eff = effectiveRange(range, wantLog ? "log" : "linear", lg.logDecades);
  const levels = levelsOf(lg);
  const outGray = lg.out === "gray";
  // 도구 줄의 기존 범위 입력(ColorLegend)도 같은 상태를 본다: 차이 = ±R · C 기여도·최소를 직접 입력한 값 = 최소·최대 · 그 밖 = 최대만(최소 자동)
  const lkind: LegendKind = modeRow.sym ? "sym" : modeKey === "c" || manMin !== null ? "minmax" : "zero";
  const legend = {
    range: eff.range,
    manual: manMin !== null || manMax !== null,
    apply: (r: Range) => (lkind === "minmax" ? setRange({ min: r.min, max: r.max }) : setRange({ max: r.max })),
    reset: () => setRange({ min: null, max: null }),
  };
  const outCount = useMemo(() => (field ? countOut(field.values, eff.range) : { above: 0, below: 0 }), [field, eff.range]);
  // v0.24.6 GPU 재색칠: 필드가 바뀔 때만 aValue 업로드(setField), 범위·레벨·눈금·범위 밖 색은 uniform 만(setLegend), 색 지도·뒤집기는 색표 256칸 교체(setColorMap). 옛 장면(mock)은 setColors
  useEffect(() => {
    const sc = sceneRef.current;
    if (field && sc?.setField) sc.setField(field.values);
  }, [field, data]);
  useEffect(() => {
    sceneRef.current?.setColorMap?.(modeRow.role, lg.reversed);
  }, [data, modeRow.role, lg.reversed]);
  useEffect(() => {
    const sc = sceneRef.current;
    if (!field || !sc) return;
    if (sc.setLegend) sc.setLegend({ min: eff.range.min, max: eff.range.max, levels, log: eff.scale === "log", outGray });
    else sc.setColors(field.values, eff.range.min, eff.range.max);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [field, data, eff.range.min, eff.range.max, eff.scale, levels, outGray]);

  // ---- 변형 형상
  useEffect(() => {
    if (!data || !sceneRef.current) return;
    sceneRef.current.setDeform(deformOn ? uEff : null, k);
  }, [data, deformOn, k, uEff]);

  // ---- 화살표·지지 기호
  const uForArrows = uEff;
  const ao = options?.arrowsOverride ?? null;
  const arrows = useMemo(() => (ao ?? (manifest ? buildArrowSpecs(manifest, mode, uForArrows, deformOn ? k : 0) : [])), [ao, manifest, mode, uForArrows, deformOn, k]);
  arrowKeysRef.current = arrows.map((a) => a.key);
  const sc = options?.supportColor ?? null;
  const supports = useMemo(() => {
    const out = manifest ? buildSupportSpecs(manifest.supports, uForArrows, deformOn ? k : 0, manifest.bbox.diag, deformOn ? k : 1) : [];
    return sc ? out.map((x) => ({ ...x, color: sc(x.vertex) ?? undefined })) : out;
  }, [manifest, uForArrows, deformOn, k, sc]);
  useEffect(() => {
    if (data && sceneRef.current) sceneRef.current.setArrows(arrows, null);
  }, [data, arrows]);
  useEffect(() => {
    if (data && sceneRef.current) sceneRef.current.setSupports(supports);
  }, [data, supports]);

  // ---- 선택 강조 (화살표를 다시 만든 뒤에 실행되도록 아래에 선언)
  useEffect(() => {
    if (!data || !sceneRef.current || !manifest) return;
    const s = sceneSelection(selection, arrows, manifest.supports, manifest.top);
    // 하중 층을 끄면 화살표 강조 대신 노드 표식(주황 점)으로 위치를 보인다
    sceneRef.current.select(lay.load ? s.arrowIndex : null, s.vertex);
  }, [data, manifest, arrows, selection, lay.load]);
  // 경계조건 층을 끄면 지지 선택 해제
  useEffect(() => {
    if (!lay.bc && selection?.kind === "support") view.setSelection(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lay.bc, selection]);

  // ---- v0.24.6 층 켜기/끄기(visible 만 — 다시 만들기·요청 없음)
  const ghostOn = lay.ghost && deformOn;
  useEffect(() => {
    const sc = sceneRef.current;
    if (!data || !sc?.setLayerVisible) return;
    sc.setLayerVisible("supports", lay.bc);
    sc.setLayerVisible("arrows", lay.load);
    sc.setLayerVisible("ghost", ghostOn);
    sc.setLayerVisible("marks", lay.marks || (lg.minMark && modeRow.editable) || lay.upin);
  }, [data, lay.bc, lay.load, lay.marks, lay.upin, lg.minMark, modeRow.editable, ghostOn]);
  // 원형 외곽선: 처음 켤 때 1회 계산(기하별 캐시), 이후는 visible 만
  const ghostCache = useRef<ParsedGlb | null>(null);
  useEffect(() => {
    const sc = sceneRef.current;
    if (!data || !sc?.setGhostEdges || !ghostOn || ghostCache.current === data.glb) return;
    ghostCache.current = data.glb;
    sc.setGhostEdges(data.glb.positions, featureEdges(data.glb.positions, data.glb.indices));
  }, [data, ghostOn]);
  useEffect(() => {
    if (!data) ghostCache.current = null;
  }, [data]);

  // ---- 최대·최소 표식(범례 편집의 □최대 표식 □최소 표식) + umax 핀(□umax 위치): 지금 칠한 색 필드(영역 색 fieldOverride 는 표식 없음)
  const fmtv = (v: number) => formatValue(v, lg.format, lg.digits);
  const pin: ScenePin | null = options?.pins !== undefined ? options.pins?.umax ?? null : extras.umaxPin;
  const nVert = data ? data.glb.positions.length / 3 : 0;
  const pinOn = lay.upin && !!pin && !!data && pin.vertex >= 0 && pin.vertex < nVert;
  const wantMin = lg.minMark && modeRow.editable;
  const ext = useMemo(() => (field && !fo ? marksWanted(field.values, { max: lay.marks, min: wantMin }) : []), [field, fo, lay.marks, wantMin]);
  const marksUnit = unit;
  const markList = useMemo(() => {
    if (!data) return [];
    const nid = data.glb.nodeIds;
    const kk = deformOn && uEff ? k : 0;
    const at = (v: number): [number, number, number] => {
      const i = v * 3;
      const b = data.glb.positions;
      return kk && uEff ? [b[i] + kk * uEff[i], b[i + 1] + kk * uEff[i + 1], b[i + 2] + kk * uEff[i + 2]] : [b[i], b[i + 1], b[i + 2]];
    };
    // 최대 표식과 같은 정점이면 최대 표식 라벨을 숨긴다(겹침 방지 — 핀 라벨이 남는다)
    const out: { vertex: number; position: [number, number, number]; text: string; symbol?: string; color?: string }[] = ext
      .filter((e) => !(pinOn && pin && e.vertex === pin.vertex))
      .map((e) => ({ vertex: e.vertex, position: at(e.vertex), text: `${e.which === "max" ? "최대" : "최소"} ${fmtv(e.value)} ${marksUnit} · N${nid ? nid[e.vertex] : e.vertex}` }));
    if (pinOn && pin) out.push({ vertex: pin.vertex, position: at(pin.vertex), text: `umax ${f3(pin.value)} mm @N ${pin.node_id}`, symbol: PIN_SYMBOL, color: PIN_COLOR });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, ext, deformOn, k, uEff, marksUnit, pinOn, pin, lg.format, lg.digits]);
  useEffect(() => {
    sceneRef.current?.setValueMarks?.(markList);
  }, [data, markList]);

  // ---- 쌍 동기화: 장면을 쌍에 등록(시점 중계)
  const attach = sync?.attach;
  useEffect(() => {
    const sc = sceneRef.current;
    if (!data || !sc || !attach) return;
    return attach(idRef.current, sc);
  }, [data, attach]);

  // ---- 칸 크기(구간 범례 높이·칩 글자 줄임)
  useEffect(() => {
    const el = host.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setHostBox({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setHostBox({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, [manifest]);

  // ---- 더블클릭: 카메라 중심 이동
  const seq = view.focusReq?.seq;
  useEffect(() => {
    if (view.focusReq && sceneRef.current) sceneRef.current.focus(view.focusReq.point);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seq]);

  const probe: ProbeExtra | null = data
    ? {
        color: modeKey === "disp" && field ? { short: shortFieldName(fo ? fo.label : options?.dispLabel ?? dov?.label ?? "변위 |u|"), values: field.values, unit: "mm", step: ovU || fo ? null : Math.max(...data.vals.scale.u) || null } : null,
        u: uEff,
        uStep: ovU ? null : data.vals.scale.u,
        xyz: data.glb.positions,
        cc: data.vals.c ? { values: data.vals.c, step: data.vals.scale.c || null } : null,
        dc: data.vals.dc ? { values: data.vals.dc, step: data.vals.scale.dc || null } : null,
      }
    : null;
  const info = manifest ? infoLine(selection, manifest, data?.vals ?? null, data?.glb.nodeIds ?? null, probe) : null;
  const fref = arrows.reduce((a, r) => Math.max(a, r.mag), 0);
  const failed = !manifest && !!error;
  const hasBc = (manifest?.supports.length ?? 0) > 0;
  const hasLoad = arrows.length > 0;
  const compact = hostBox.w > 0 && hostBox.w < COMPACT_PX;
  const legendLabel = fo
    ? fo.label
    : modeKey === "c"
    ? options?.colorLabel ?? C_LABEL
    : modeKey === "dc"
    ? options?.colorLabel ?? DC_LABEL
    : unit === "mm"
    ? options?.dispLabel ?? dov?.label ?? "변위 |u| (mm)"
    : unit === "MPa"
    ? "면압 |Fn|/A (MPa)"
    : loadComp === "fmag"
    ? "|F| 하중 크기 (N)"
    : "|Fn| 면외 하중 (N)";
  const nodeOf = (v: number) => (data?.glb.nodeIds ? data.glb.nodeIds[v] : v);
  const extLine = (which: "max" | "min") => {
    const e = ext.find((x) => x.which === which);
    return e ? `${which === "max" ? "최대" : "최소"} ${fmtv(e.value)} @N ${nodeOf(e.vertex)}` : null;
  };
  const maxLine = extLine("max");
  const minLine = extLine("min");
  const bcLegend = manifest && hasBc ? markLegend(manifest.supports, sourceRow(view.src)?.group === "jig") : null;
  // 범례 편집(범례 클릭 팝오버 · ⚙ 팝오버의 `범례` 절 — 같은 컴포넌트). 분류 표시(하중 영역)·직접 준 영역 색은 편집 없음
  const [legendOpen, setLegendOpen] = useState(false);
  const editorProps: LegendEditorProps | null =
    modeRow.editable && field
      ? {
          settings: lgAll,
          onChange: (p) => legendStore.setLegend(p),
          range,
          manMin,
          manMax,
          onRange: setRange,
          mode: modeRow,
          logOk: logAllowed(modeRow, range),
          marksOn: lay.marks,
          onMarks: (on) => store.set({ marks: on }),
          hasPin: !!pin,
          onReset: () => {
            legendStore.setLegend({ ...LEGEND_DEFAULTS });
            store.set({ marks: planOf(planKey).defaults.marks });
            setRange({ min: null, max: null });
          },
        }
      : null;
  const noValues = !!data && !field && (modeKey === "c" || modeKey === "dc");
  const controlProps = { store, hasBc, hasLoad, deformOn, compact, bcLegend, legendEditor: editorProps };
  const hotkeys = {
    b: () => hasBc && planOf(planKey).layers.includes("bc") && store.set({ bc: !st.bc }),
    l: () => hasLoad && planOf(planKey).layers.includes("load") && store.set({ load: !st.load }),
  };

  return (
    <Card title={options?.title ?? "3D 하중 보기"} right={options?.headRight}>
      {failed ? (
        <div className="small warn-text" role="alert" data-testid="v3d-error">
          {error}{fallbackAllowed(view.src) ? " — 3D 보기를 건너뛰고 아래 표만 보입니다." : ""}
        </div>
      ) : !manifest ? (
        <div className="empty small">불러오는 중…</div>
      ) : (
        <div className="v3d">
          <div className="v3d-tools">
            {options?.toolsLead}
            {!ao && <label className="range-field" title="화살표 개수 — 왼쪽 끝 100 노드, 오른쪽으로 갈수록 줄고 마지막 4칸은 공간 군집 합력(5·4·3·2)">
              <span>화살표</span>
              <input
                type="range"
                min={0}
                max={N_STAGES - 1}
                step={1}
                value={stage}
                aria-label="화살표 단계"
                aria-valuetext={stageText(stage)}
                onChange={(e) => view.setStage(Number(e.target.value))}
              />
              <span className="mono small range-val" data-testid="v3d-stage">
                {stageText(stage)}
              </span>
            </label>}
            <button type="button" className={`btn small ghost toggle${deformOn ? " on" : ""}`} aria-pressed={deformOn} disabled={!hasU} onClick={() => setDeformOn((x) => !x)} title="u_rel × 배율로 변형된 형상을 보입니다(표시 전용)">
              변형 형상
            </button>
            <label className="range-field" title="배율은 화면 표시용이며 값·판정에 영향 없음">
              <span data-testid="v3d-scale-label">{scaleLabel(k, umax)}</span>
              <input
                type="range"
                min={EXP_MIN}
                max={EXP_MAX}
                step={EXP_STEP}
                value={kexpEff ?? 0}
                disabled={!deformOn || real}
                aria-label="변형 확대 배율"
                onChange={(e) => setKexp(Number(e.target.value))}
              />
            </label>
            <button type="button" className={`btn small ghost toggle${real ? " on" : ""}`} aria-pressed={real} disabled={!deformOn} onClick={() => setReal((x) => !x)} title="변형 확대 없이 실제 변위 그대로 그립니다">
              실제 크기(×1)
            </button>
            <label className="check-field" title="체크 = 원근, 해제 = 직교(기본, 치수 왜곡 없음). 같은 시점·같은 크기로 전환">
              <input type="checkbox" checked={proj === "persp"} onChange={(e) => toggleProj(e.target.checked)} data-testid="v3d-persp" />
              <span>원근</span>
            </label>
            {options?.toolsTail}
          </div>
          {/* v0.17.3 칸·시점 툴바 = 공통 PartStage(esl_view_unify.md VU-D-2) — 장면·화살표·색은 이 카드가 그대로 맡음 */}
          <PartStage
            host={host}
            scene={() => sceneRef.current}
            phase={phase}
            bbox={manifest.bbox}
            testId="v3d-host"
            ariaLabel="3D 하중 보기"
            msg={phase === "nowebgl" || phase === "error" ? (phase === "error" && phaseErr && phaseErr !== NO_3D_TEXT ? phaseErr : NO_3D_TEXT) : null}
            msgTestId="v3d-unavailable"
            loading={phase === "loading"}
            controls={{ lead: <ViewerChips {...controlProps} />, tail: <ViewerGear {...controlProps} />, hotkeys }}
            extra={
              <>
                {field && (
                  <LegendOverlay
                    levels={levels}
                    range={eff.range}
                    scale={eff.scale}
                    role={modeRow.role}
                    reversed={lg.reversed}
                    format={lg.format}
                    digits={lg.digits}
                    title={legendLabel}
                    above={outCount.above}
                    below={outCount.below}
                    outGray={outGray}
                    maxLine={maxLine}
                    minLine={minLine}
                    hostHeight={hostBox.h}
                    onOpen={editorProps ? () => setLegendOpen((x) => !x) : undefined}
                    open={legendOpen && !!editorProps}
                  >
                    {legendOpen && editorProps && (
                      <LegendPopover onClose={() => setLegendOpen(false)}>
                        <LegendEditor {...editorProps} />
                      </LegendPopover>
                    )}
                  </LegendOverlay>
                )}
                {noValues && (
                  <div className="v3d-info mono small" data-testid="v3d-no-c" role="status">
                    {modeKey === "c" ? NO_C_TEXT : NO_DC_TEXT}
                  </div>
                )}
                {info ? (
                  <div className="v3d-info mono small" data-testid="v3d-info" aria-live="polite">
                    {info}
                  </div>
                ) : null}
              </>
            }
          />
          <div className="v3d-foot">
            <span className="small muted" data-testid="v3d-note">
              화살표 최대 = {f3(fref)} N · 길이 ∝ |F| (최소 길이 제한)
              {ao ? " · 영역 합력" : mode.kind === "cluster" ? " · 군집 모드: ΣF ≈ 0 (자기평형)" : ""}
              {!lay.load ? " · 화살표 숨김" : ""}
            </span>
            {field && (
              <ColorLegend
                kind={lkind}
                label={legendLabel}
                range={legend.range}
                manual={legend.manual}
                gradient={cssGradient(mapFor(modeRow.role), { reversed: lg.reversed, levels })}
                onApply={legend.apply}
                onReset={legend.reset}
                above={outCount.above}
                below={outCount.below}
                testId="v3d-legend"
              />
            )}
          </div>
        </div>
      )}
    </Card>
  );
}


