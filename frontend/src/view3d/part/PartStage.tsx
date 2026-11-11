// v0.17.3 공통 3D 칸(esl_view_unify.md VU-D-2): 칸(host) + 시점 툴바(정면 ±X·±Y·±Z · 등각 · 꽉 차게 · 선택 맞춤) + 안내 문구.
// 비드 선택 3D(편집)·안 3D 보기·PartView 3D·3D 하중 보기(View3DCard)가 같은 칸을 쓴다. usePartScene = 고정 형상 장면(직교, 배경 회색).
import { useEffect, useMemo, useRef, useState, type HTMLAttributes, type MutableRefObject, type ReactNode, type RefObject } from "react";
import { errorText } from "../../api/client";
import { loadScene } from "../loadThree";
import type { SceneApi } from "../sceneApi";
import { ViewToolbar } from "../ViewToolbar";
import { positionsBbox, type Bbox } from "../viewFit";
import { hasWebGL } from "../webgl";
import type { PartMesh } from "./types";

export const NO_3D = "이 브라우저에서 3D 보기를 쓸 수 없습니다";
export const PART_BACKGROUND = "#dfe3e8";
export type ScenePhase = "idle" | "loading" | "ready" | "nowebgl" | "error";

/** 고정 형상 장면: mesh 가 바뀔 때만 다시 만든다. tri2elem 이 있으면 요소 모드(요소별 색) */
export function usePartScene(
  host: RefObject<HTMLElement | null>,
  mesh: PartMesh | null,
  opts?: { colorMap?: "blues" | "diverging" },
): { sceneRef: MutableRefObject<SceneApi | null>; phase: ScenePhase; error: string | null; bbox: Bbox | null } {
  const sceneRef = useRef<SceneApi | null>(null);
  const [phase, setPhase] = useState<ScenePhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const bbox = useMemo(() => (mesh ? positionsBbox(mesh.positions) : null), [mesh]);
  const colorMap = opts?.colorMap;
  useEffect(() => {
    if (!mesh || !bbox) return;
    if (!hasWebGL()) {
      setPhase("nowebgl");
      return;
    }
    let cancelled = false;
    let scene: SceneApi | null = null;
    let canvas: HTMLCanvasElement | null = null;
    setPhase("loading");
    setError(null);
    void (async () => {
      try {
        const mod = await loadScene();
        if (cancelled || !host.current) return;
        canvas = document.createElement("canvas");
        canvas.className = "v3d-canvas";
        host.current.insertBefore(canvas, host.current.firstChild);
        const { min: mn, max: mx } = bbox;
        const diag = Math.hypot(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]) || 1;
        scene = mod.createScene(canvas, { background: PART_BACKGROUND, diag, bbox: { min: mn, max: mx }, projection: "ortho" });
        if (mesh.tri2elem && !scene.setElements) throw new Error(NO_3D);
        scene.setGeometry({ positions: mesh.positions, indices: mesh.indices, src: null }, null);
        if (mesh.tri2elem) scene.setElements!(mesh.tri2elem, mesh.nElems ?? 0);
        if (colorMap) scene.setColorMap?.(colorMap);
        sceneRef.current = scene;
        setPhase("ready");
      } catch (e) {
        if (!cancelled) {
          setPhase("error");
          setError(e instanceof Error && e.message === NO_3D ? NO_3D : errorText(e));
        }
      }
    })();
    return () => {
      cancelled = true;
      sceneRef.current = null;
      scene?.dispose();
      canvas?.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mesh, bbox]);
  return { sceneRef, phase, error, bbox };
}

/** 3D 칸 + 시점 툴바 + 안내. hostProps = 칸에 붙일 입력 처리(편집 화면) */
export function PartStage({
  host,
  scene,
  phase,
  bbox,
  selectionBbox,
  testId,
  ariaLabel,
  className,
  hostProps,
  children,
  msg,
  msgTestId,
  loading,
  extra,
}: {
  host: RefObject<HTMLDivElement>;
  scene: () => SceneApi | null;
  phase: ScenePhase;
  bbox: Bbox | null;
  selectionBbox?: (() => Bbox | null) | null;
  testId: string;
  ariaLabel: string;
  className?: string;
  hostProps?: HTMLAttributes<HTMLDivElement>;
  children?: ReactNode;
  /** 3D 를 못 쓸 때 문구(null = 숨김) */
  msg?: ReactNode;
  msgTestId?: string;
  /** 불러오는 중 문구 표시 */
  loading?: boolean;
  /** 칸 위에 겹쳐 둘 것(정보 줄 등) */
  extra?: ReactNode;
}) {
  return (
    <div className="v3d-stage">
      <div ref={host} className={`v3d-host${className ? ` ${className}` : ""}`} data-testid={testId} data-phase={phase} tabIndex={0} aria-label={ariaLabel} {...hostProps}>
        {children}
      </div>
      {phase === "ready" && bbox && <ViewToolbar scene={scene} modelBbox={bbox} selectionBbox={selectionBbox ?? undefined} keyTarget={host} />}
      {msg != null && msg !== false && (
        <div className="v3d-msg" role="status" data-testid={msgTestId}>
          {msg}
        </div>
      )}
      {loading && <div className="v3d-msg muted">3D 형상 불러오는 중…</div>}
      {extra}
    </div>
  );
}
