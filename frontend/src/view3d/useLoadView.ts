// ④ 3D 하중 보기·상위 표가 공유하는 상태(manifest · 화살표 단계 · 선택 · 카메라 이동 요청).
// manifest 가 413/409/503 등으로 실패하면 사유 한 줄 + /forces?top=100 폴백 표(계약 §5).
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/endpoints";
import { errorText } from "../api/client";
import type { ForcesOut, View3dOut } from "../api/types";
import { nearestEnabledStage, stageEnabled, stageMode, type ArrowMode } from "./arrows";
import type { V3 } from "./pick";
import { reconcile, visibleKeys, type Selection } from "./selection";
import { fallbackAllowed, isLegacySource } from "./sources";

export interface LoadView {
  runId: string;
  /** v0.24.1 하중 출처 키(없음 = legacy 전 노드 — 지금 화면 그대로) */
  src: string | null;
  /** 범례 수동 범위 기억 키: legacy = runId 그대로(저장된 범위 유지), 그 밖 `runId:src` */
  rangeKey: string;
  manifest: View3dOut | null;
  /** manifest 실패 사유(한국어 한 줄) */
  error: string | null;
  fallback: ForcesOut | null;
  loading: boolean;
  stage: number;
  setStage: (i: number) => void;
  mode: ArrowMode;
  selection: Selection;
  setSelection: (s: Selection) => void;
  /** 더블클릭: 카메라 중심 이동 요청 */
  focusReq: { point: V3; seq: number } | null;
  requestFocus: (p: V3) => void;
  /** manifest 다시 받기(파일 요청이 409 VIEW3D_STALE 일 때 1회) */
  reload: () => void;
}

/** src 없음·legacy 행(full) = 옛 URL(`?src` 없음)로 받는다 — 응답·키·ETag 가 v0.24.0 과 같음. 그 밖 = `?src=<key>` */
export function useLoadView(runId: string | null, enabled: boolean, src?: string | null): LoadView | null {
  const legacy = isLegacySource(src);
  const srcKey = legacy ? null : src ?? null;
  const allowFallback = fallbackAllowed(src);
  const [manifest, setManifest] = useState<View3dOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fallback, setFallback] = useState<ForcesOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [stage, setStageRaw] = useState(0);
  const [selection, setSelectionRaw] = useState<Selection>(null);
  const [nonce, setNonce] = useState(0);
  const [focusReq, setFocusReq] = useState<LoadView["focusReq"]>(null);

  useEffect(() => {
    setManifest(null);
    setError(null);
    setFallback(null);
    setSelectionRaw(null);
    setStageRaw(0);
    if (!runId || !enabled) return;
    let alive = true;
    setLoading(true);
    api
      .view3d(runId, srcKey ?? undefined)
      .then(async (m) => {
        if (!alive) return;
        setManifest(m);
        const s = nearestEnabledStage(m, 0);
        setStageRaw(s < 0 ? 0 : s);
      })
      .catch(async (e) => {
        if (!alive) return;
        setError(errorText(e));
        // /forces 는 전 노드 ESL 전용 표 — 다른 출처에 붙이면 틀린 표라 legacy 행만(C4)
        if (!allowFallback) return;
        try {
          const f = await api.forces(runId, 100);
          if (alive) setFallback(f);
        } catch {
          /* 폴백도 실패하면 표는 비어 있고 사유만 보인다 */
        }
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [runId, enabled, nonce, srcKey, allowFallback]);

  const mode = useMemo(() => stageMode(stage), [stage]);
  const setStage = useCallback(
    (i: number) => {
      if (!manifest) return;
      const j = stageEnabled(manifest, i) ? i : nearestEnabledStage(manifest, i);
      if (j < 0) return;
      setStageRaw(j);
      setSelectionRaw((s) => reconcile(s, visibleKeys(manifest, stageMode(j))));
    },
    [manifest],
  );
  const setSelection = useCallback((s: Selection) => setSelectionRaw(s), []);
  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const requestFocus = useCallback((p: V3) => setFocusReq((r) => ({ point: p, seq: (r?.seq ?? 0) + 1 })), []);

  return useMemo(
    () => (runId ? { runId, src: srcKey, rangeKey: srcKey ? `${runId}:${srcKey}` : runId, manifest, error, fallback, loading, stage, setStage, mode, selection, setSelection, focusReq, requestFocus, reload } : null),
    [runId, srcKey, manifest, error, fallback, loading, stage, setStage, mode, selection, setSelection, focusReq, requestFocus, reload],
  );
}
