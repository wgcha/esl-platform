// v0.24.6 뷰어 상태 공유(esl_viewer_hv.md §2.7·§4·§6.1).
//  - useViewerStore(planKey): 카드 하나의 보기 상태(층·레벨 = 이 브라우저에 기억, 변형·투영 = 메모리/투영 기억).
//  - useViewerSync(planKey): 2카드 쌍이 공유하는 같은 상태 + 카메라 중계. 한 카드의 회전·줌·팬·시점 버튼 → 상대 카드 applyCameraState 1회
//    (적용 중에는 다시 내보내지 않음 — 핑퐁 금지, 출처 id 가드).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { pairScaleExp } from "./deform";
import { readProjection, type Projection } from "./projection";
import type { CameraState, SceneApi } from "./sceneApi";
import { planOf, type ViewerState } from "./viewerPlan";
import { readViewerPrefs, writeViewerPrefs } from "./viewerPrefs";

/** 카드가 읽는 보기 상태: 기억하는 것(층·레벨) + 이번 화면에서만 도는 것(변형·투영) */
export interface ViewerShared extends ViewerState {
  deformOn: boolean;
  kexp: number | null;
  real: boolean;
  proj: Projection;
}

export interface ViewerStore {
  planKey: string;
  state: ViewerShared;
  set: (patch: Partial<ViewerShared>) => void;
}

export interface ViewerSync extends ViewerStore {
  /** 쌍의 한 카드 장면을 등록. 반환 = 해제. 이미 다른 카드가 있으면 그 시점으로 맞춘다 */
  attach: (id: string, scene: SceneApi) => () => void;
  /** 카드가 자기 변위 규모(대각선·최대 변위)를 쌍에 알림. 반환 = 해제. 기본 배율은 쌍 전체가 정함(적재 순서 무관) */
  reportBasis: (id: string, b: { diag: number; umax: number }) => () => void;
  /** 사용자가 배율을 아직 안 만졌을 때 쌍이 같이 쓰는 기본 배율 지수(알린 카드가 없으면 null) */
  kexpDefault: number | null;
}

const initial = (planKey: string): ViewerShared => ({ ...readViewerPrefs(planKey), deformOn: false, kexp: null, real: false, proj: readProjection() });
const MEMO_KEYS = ["bc", "load", "ghost", "marks", "levels"] as const;

export function useViewerStore(planKey: string): ViewerStore {
  planOf(planKey); // 알 수 없는 키 = 오류
  const [state, setState] = useState<ViewerShared>(() => initial(planKey));
  const ref = useRef(state);
  ref.current = state;
  const keyRef = useRef(planKey);
  useEffect(() => {
    if (keyRef.current === planKey) return;
    keyRef.current = planKey;
    const s = { ...ref.current, ...readViewerPrefs(planKey) }; // 변형·투영은 보기를 바꿔도 유지
    ref.current = s;
    setState(s);
  }, [planKey]);
  const set = useCallback(
    (patch: Partial<ViewerShared>) => {
      const next = { ...ref.current, ...patch };
      const memo = MEMO_KEYS.some((k) => patch[k] !== undefined && patch[k] !== ref.current[k]);
      ref.current = next;
      setState(next);
      if (memo) writeViewerPrefs(keyRef.current, { bc: next.bc, load: next.load, ghost: next.ghost, marks: next.marks, levels: next.levels });
    },
    [],
  );
  return useMemo(() => ({ planKey, state, set }), [planKey, state, set]);
}

export function useViewerSync(planKey: string): ViewerSync {
  const store = useViewerStore(planKey);
  const members = useRef(new Map<string, SceneApi>());
  const applying = useRef(false);
  const relay = useCallback((from: string, cs: CameraState) => {
    if (applying.current) return;
    applying.current = true;
    try {
      for (const [id, sc] of members.current) if (id !== from) sc.applyCameraState?.(cs);
    } finally {
      applying.current = false;
    }
  }, []);
  const attach = useCallback(
    (id: string, scene: SceneApi) => {
      const first = [...members.current.values()][0];
      members.current.set(id, scene);
      scene.onCameraChange?.((cs) => relay(id, cs));
      if (first?.cameraState) {
        applying.current = true;
        try {
          scene.applyCameraState?.(first.cameraState());
        } finally {
          applying.current = false;
        }
      }
      return () => {
        if (members.current.get(id) === scene) members.current.delete(id);
        scene.onCameraChange?.(null);
      };
    },
    [relay],
  );
  const [basis, setBasis] = useState<Record<string, { diag: number; umax: number }>>({});
  const reportBasis = useCallback((id: string, b: { diag: number; umax: number }) => {
    setBasis((p) => (p[id]?.diag === b.diag && p[id]?.umax === b.umax ? p : { ...p, [id]: b }));
    return () =>
      setBasis((p) => {
        if (!(id in p)) return p;
        const { [id]: _drop, ...rest } = p;
        void _drop;
        return rest;
      });
  }, []);
  const kexpDefault = useMemo(() => pairScaleExp(Object.values(basis)), [basis]);
  return useMemo(() => ({ ...store, attach, reportBasis, kexpDefault }), [store, attach, reportBasis, kexpDefault]);
}
