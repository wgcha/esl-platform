// ④ 3D 하중 보기 카드(계약 §5~§8). 컨트롤은 한 줄: 화살표 단계 · 변형 형상 · 배율 · 실제 크기 · 맞춤.
// three 는 loadScene() 동적 import 로만 들어온다. WebGL 이 없거나 청크 적재가 실패하면 안내 문구만 보이고 표는 그대로.
import { useEffect, useMemo, useRef, useState } from "react";
import { errorText } from "../api/client";
import { Card } from "../components/ui";
import { ColorLegend, countOut, useLegendRange } from "../components/ColorLegend";
import { f3 } from "../lib/colormap";
import { N_STAGES, buildArrowSpecs, stageText } from "./arrows";
import { BLUES_GRADIENT } from "./colors";
import { EXP_MAX, EXP_MIN, EXP_STEP, defaultScaleExp, scaleFromExp, scaleLabel } from "./deform";
import { fetchBinary, fileUrls } from "./fetchFiles";
import { parseGlb, type ParsedGlb } from "./glb";
import { infoLine } from "./info";
import { loadScene } from "./loadThree";
import { selectionFromPick, sceneSelection } from "./selection";
import type { SceneApi } from "./sceneApi";
import { buildSupportSpecs } from "./supports";
import type { LoadView } from "./useLoadView";
import { colorField, decodeValues, type DecodedValues } from "./values";
import { hasWebGL } from "./webgl";

export const NO_3D_TEXT = "이 브라우저에서 3D 보기를 쓸 수 없습니다";
const BACKGROUND = "#dfe3e8";

interface Loaded {
  glb: ParsedGlb;
  vals: DecodedValues;
}

export function View3DCard({ view }: { view: LoadView }) {
  const { manifest, error, mode, selection, stage } = view;
  const host = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<SceneApi | null>(null);
  const [phase, setPhase] = useState<"idle" | "loading" | "ready" | "nowebgl" | "error">("idle");
  const [phaseErr, setPhaseErr] = useState<string | null>(null);
  const [data, setData] = useState<Loaded | null>(null);
  const [deformOn, setDeformOn] = useState(false);
  const [real, setReal] = useState(false);
  const [kexp, setKexp] = useState<number | null>(null);
  const staleRetried = useRef(false);
  const arrowKeysRef = useRef<string[]>([]);

  const diag = manifest?.bbox.diag ?? 1;
  const umax = manifest?.ranges.u_max ?? 0;
  useEffect(() => {
    if (manifest && kexp === null) setKexp(defaultScaleExp(diag, umax));
  }, [manifest, kexp, diag, umax]);
  const k = real ? 1 : scaleFromExp(kexp ?? 0);
  const hasU = !!data?.vals.u;

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
          scene = mod.createScene(canvas, { background: BACKGROUND, diag: manifest.bbox.diag, bbox: manifest.bbox });
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

  // ---- 표면 색: 면압 |Fn|/A (MPa), 없으면 |Fn| (N)
  const field = useMemo(() => (data ? colorField(data.vals) : null), [data]);
  const unit = field?.unit ?? "MPa";
  const auto = useMemo(() => {
    const r = unit === "MPa" ? manifest?.ranges.pa : manifest?.ranges.fn_abs;
    const top = r && r.p99 > 0 ? r.p99 : r?.max && r.max > 0 ? r.max : 1;
    return { min: 0, max: top };
  }, [manifest, unit]);
  const legend = useLegendRange(view.runId, "load", unit === "MPa" ? "pa" : "fn", "zero", auto);
  const outCount = useMemo(() => (field ? countOut(field.values, legend.range) : { above: 0, below: 0 }), [field, legend.range]);
  useEffect(() => {
    if (field && sceneRef.current) sceneRef.current.setColors(field.values, legend.range.min, legend.range.max);
  }, [field, legend.range.min, legend.range.max]);

  // ---- 변형 형상
  useEffect(() => {
    if (!data || !sceneRef.current) return;
    sceneRef.current.setDeform(deformOn ? data.vals.u : null, k);
  }, [data, deformOn, k]);

  // ---- 화살표·지지 기호
  const uForArrows = data?.vals.u ?? null;
  const arrows = useMemo(() => (manifest ? buildArrowSpecs(manifest, mode, uForArrows, deformOn ? k : 0) : []), [manifest, mode, uForArrows, deformOn, k]);
  arrowKeysRef.current = arrows.map((a) => a.key);
  const supports = useMemo(() => (manifest ? buildSupportSpecs(manifest.supports, uForArrows, deformOn ? k : 0, manifest.bbox.diag) : []), [manifest, uForArrows, deformOn, k]);
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
    sceneRef.current.select(s.arrowIndex, s.vertex);
  }, [data, manifest, arrows, selection]);

  // ---- 더블클릭: 카메라 중심 이동
  const seq = view.focusReq?.seq;
  useEffect(() => {
    if (view.focusReq && sceneRef.current) sceneRef.current.focus(view.focusReq.point);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seq]);

  const info = manifest ? infoLine(selection, manifest, data?.vals ?? null, data?.glb.nodeIds ?? null) : null;
  const fref = arrows.reduce((a, r) => Math.max(a, r.mag), 0);
  const failed = !manifest && !!error;

  return (
    <Card title="3D 하중 보기">
      {failed ? (
        <div className="small warn-text" role="alert" data-testid="v3d-error">
          {error} — 3D 보기를 건너뛰고 아래 표만 보입니다.
        </div>
      ) : !manifest ? (
        <div className="empty small">불러오는 중…</div>
      ) : (
        <div className="v3d">
          <div className="v3d-tools">
            <label className="range-field" title="화살표 개수 — 왼쪽 끝 100 노드, 오른쪽으로 갈수록 줄고 마지막 4칸은 공간 군집 합력(5·4·3·2)">
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
            </label>
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
                value={kexp ?? 0}
                disabled={!deformOn || real}
                aria-label="변형 확대 배율"
                onChange={(e) => setKexp(Number(e.target.value))}
              />
            </label>
            <button type="button" className={`btn small ghost toggle${real ? " on" : ""}`} aria-pressed={real} disabled={!deformOn} onClick={() => setReal((x) => !x)} title="변형 확대 없이 실제 변위 그대로 그립니다">
              실제 크기(×1)
            </button>
            <button type="button" className="btn small ghost" onClick={() => sceneRef.current?.fit()} disabled={phase !== "ready"} title="부품 전체가 보이도록 카메라를 맞춥니다">
              맞춤
            </button>
          </div>
          <div className="v3d-stage">
            <div ref={host} className="v3d-host" data-testid="v3d-host" data-phase={phase} />
            {(phase === "nowebgl" || phase === "error") && (
              <div className="v3d-msg" role="status" data-testid="v3d-unavailable">
                {phase === "error" && phaseErr && phaseErr !== NO_3D_TEXT ? phaseErr : NO_3D_TEXT}
              </div>
            )}
            {phase === "loading" && <div className="v3d-msg muted">3D 형상 불러오는 중…</div>}
            {info && (
              <div className="v3d-info mono small" data-testid="v3d-info" aria-live="polite">
                {info}
              </div>
            )}
          </div>
          <div className="v3d-foot">
            <span className="small muted" data-testid="v3d-note">
              화살표 최대 = {f3(fref)} N · 길이 ∝ |F| (최소 길이 제한)
              {mode.kind === "cluster" ? " · 군집 모드: ΣF ≈ 0 (자기평형)" : ""}
            </span>
            {field && (
              <ColorLegend
                kind="zero"
                label={unit === "MPa" ? "면압 |Fn|/A (MPa)" : "|Fn| 면외 하중 (N)"}
                range={legend.range}
                manual={legend.manual}
                gradient={BLUES_GRADIENT}
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


