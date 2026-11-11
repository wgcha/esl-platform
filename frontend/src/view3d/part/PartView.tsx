// v0.17.3 공통 형상 보기 PartView(esl_view_unify.md §3): 3D 와 평면도를 한 칸에서 [3D | 평면도]로 바꿔 보고, 같은 시점 툴바·층 칩을 쓴다.
// 화면마다 어댑터(adapters.ts)가 가진 자료만 넘기고(시나리오별 사본 없음), 자료가 없는 층·보기는 숨긴다(VU-D-4·5).
// 3D 칸은 3D 를 고를 때만 만든다(장면 1개 — 평면도만 볼 때 GPU 를 쓰지 않음).
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { PartPlan } from "./PartPlan";
import { NO_3D, PartStage, usePartScene } from "./PartStage";
import { BoundaryWarnList } from "./BoundaryWarnList";
import { LAYER_NAME, LAYER_OFF_DEFAULT, LAYER_ORDER, type LayerKey, type Part3DData, type PartViewData } from "./types";

export type PartMode = "3d" | "plan";

export function PartView({ data, tools, side, testId = "part-view" }: {
  data: PartViewData;
  /** 보기 줄 왼쪽에 둘 화면 고유 조작(예: 안 3D 의 공칭/안 · 배율) */
  tools?: ReactNode;
  /** 오른쪽 칸(단면 미니 그림·안내) — 경계 경고 표는 data.warnings 가 있으면 자동으로 이 아래 */
  side?: ReactNode;
  testId?: string;
}) {
  const has3d = !!data.scene;
  const hasPlan = !!data.plan;
  const [mode, setMode] = useState<PartMode>(data.initialMode ?? (hasPlan ? "plan" : "3d"));
  const cur: PartMode = mode === "3d" && !has3d ? "plan" : mode === "plan" && !hasPlan ? "3d" : mode;
  const layers = useMemo(() => LAYER_ORDER.filter((k) => data.layers.includes(k) && (cur === "3d" ? LAYER_3D.has(k) : LAYER_PLAN.has(k))), [data.layers, cur]);
  const [off, setOff] = useState<Set<LayerKey>>(() => new Set(LAYER_OFF_DEFAULT));
  const on = (k: LayerKey) => data.layers.includes(k) && !off.has(k);
  const toggle = (k: LayerKey) =>
    setOff((s) => {
      const n = new Set(s);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  const showSide = !!side || !!data.warnings;
  if (!has3d && !hasPlan) return null;
  return (
    <div className="pv" data-testid={testId} data-mode={cur}>
      <div className="pv-bar">
        {has3d && hasPlan && (
          <span className="seg" role="radiogroup" aria-label="보기">
            {(["3d", "plan"] as const).map((m) => (
              <button key={m} type="button" role="radio" aria-checked={cur === m} className={`btn small ghost toggle${cur === m ? " on" : ""}`} onClick={() => setMode(m)} data-testid={`pv-mode-${m}`}>
                {m === "3d" ? "3D" : "평면도"}
              </button>
            ))}
          </span>
        )}
        {tools}
        {layers.length > 0 && (
          <span className="pv-layers" role="group" aria-label="표시 층">
            {layers.map((k) => (
              <label key={k} className="check-field small pv-layer" title={`${LAYER_NAME[k]} ${on(k) ? "숨기기" : "보이기"}`}>
                <input type="checkbox" checked={on(k)} onChange={() => toggle(k)} data-testid={`pv-layer-${k}`} />
                <i className={`pv-sw pv-sw-${k}`} aria-hidden="true" />
                <span>{LAYER_NAME[k]}</span>
              </label>
            ))}
          </span>
        )}
      </div>
      <div className={showSide ? "doe-plan-grid" : undefined}>
        <div className="pv-main">
          {cur === "plan" && data.plan ? <PartPlan plan={data.plan} on={on} active={data.active ?? null} /> : data.scene ? <Part3D scene={data.scene} on={on} testId={data.scene.hostTestId ?? `${testId}-3d`} ariaLabel={data.scene.ariaLabel} /> : null}
        </div>
        {showSide && (
          <div className="doe-plan-side">
            {side}
            {data.warnings && <BoundaryWarnList w={data.warnings} />}
          </div>
        )}
      </div>
    </div>
  );
}

/** 3D 에서 의미 있는 층(요소 색·형상) — 평면 전용 층(점·고리·기호)은 3D 칩에서 숨김 */
const LAYER_3D = new Set<LayerKey>(["graph", "islands"]);
const LAYER_PLAN = new Set<LayerKey>(["mesh", "boundary", "beads", "fixed", "loads", "apoints", "nodes"]);

/** PartView 의 3D 칸(고정 형상 + 요소 색·안 변위·빨간 점) */
export function Part3D({ scene: d, on, testId, ariaLabel }: { scene: Part3DData; on: (k: LayerKey) => boolean; testId: string; ariaLabel?: string }) {
  const host = useRef<HTMLDivElement>(null);
  const { sceneRef, phase, error, bbox } = usePartScene(host, d.mesh, { colorMap: d.colorMap });
  const graphOn = on("graph");
  const islandsOn = on("islands");
  useEffect(() => {
    const sc = sceneRef.current;
    if (!sc || phase !== "ready") return;
    if (d.elemColors && sc.setElemColors) {
      const rgba = d.elemColors((k) => (k === "graph" ? graphOn : k === "islands" ? islandsOn : on(k)));
      if (rgba) sc.setElemColors(rgba);
    }
    if (d.design) {
      const V = d.design.vmax > 0 ? d.design.vmax : 1;
      sc.setColors(d.design.u ? d.design.c : new Float32Array(d.design.c.length), -V, V);
      sc.setDeform(d.design.u, d.design.scale);
    }
    if (sc.setMarkers) sc.setMarkers(d.markers && d.markers.length ? d.markers : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, d, graphOn, islandsOn]);
  const unavailable = phase === "nowebgl" || phase === "error";
  return (
    <PartStage
      host={host}
      scene={() => sceneRef.current}
      phase={phase}
      bbox={bbox}
      selectionBbox={d.selectionBbox}
      testId={testId}
      ariaLabel={ariaLabel ?? "형상 3D"}
      msg={unavailable ? (phase === "error" && error && error !== NO_3D ? error : NO_3D) : null}
      loading={phase === "loading"}
    />
  );
}
