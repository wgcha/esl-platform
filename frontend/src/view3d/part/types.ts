// v0.17.3 공통 형상 보기(PartView) 자료 형식(esl_view_unify.md §3). 화면마다 어댑터(adapters.ts)가 가진 자료만 채우고,
// 자료가 없는 층은 숨긴다(가짜 자료로 채우지 않음 — VU-D-5).
import type { DoePlanLink, DoeSettingsOut, PlanViewFrame, XY } from "../../api/types";
import type { Bbox } from "../viewFit";

/** 켜고 끌 수 있는 층 */
/** v0.18.0 region = ③ STEP 기준 select 평가 영역(주 시트) 외곽 */
export type LayerKey = "mesh" | "boundary" | "region" | "beads" | "fixed" | "loads" | "apoints" | "graph" | "islands" | "nodes";

export const LAYER_ORDER: LayerKey[] = ["mesh", "boundary", "region", "beads", "graph", "islands", "fixed", "apoints", "loads", "nodes"];
export const LAYER_NAME: Record<LayerKey, string> = {
  mesh: "메시",
  boundary: "외곽·구멍",
  region: "주 시트 영역",
  beads: "비드",
  graph: "세그먼트 색",
  islands: "섬",
  fixed: "고정",
  apoints: "A 체결·연결",
  loads: "하중 집중",
  nodes: "노드 점",
};
/** 처음에 꺼 둘 층(점이 많아 그림을 가림) */
export const LAYER_OFF_DEFAULT: LayerKey[] = ["nodes"];

/** 고른 변수 행(평면도 범위 표시·강조) */
export interface PlanVar {
  name: string;
  type: "D" | "W";
  bead: string;
  tier?: number | null;
  nominal: number;
  lo: number;
  hi: number;
}

export interface PlanBead {
  id: string;
  /** 외곽 고리(여러 개 = 다리·조각) */
  rings: XY[][];
  /** 폭 W 법선(고리 점마다) — 있으면 W 범위 점선 */
  e?: XY[][];
  /** 단(tier) 바닥 고리 — 있으면 단 색(파랑 명도)으로 칠함, 없으면 번호만(이전 방식 비드) */
  tiers?: { k: number; ring_ab: XY[][] }[];
  /** 라벨 칩 위치·글 */
  label?: XY;
  chip?: string | null;
}

export interface PartPlanData {
  /** 그림 이름(접근성 — 시험에서 찾는 이름) */
  ariaLabel: string;
  /** select = 메시 점 흐리게·단 색·라벨 칩(v0.15 SelectPlan), legacy = 비드 번호·주황 칠(v0.9 BoundaryPlan) */
  style: "select" | "legacy";
  frame: PlanViewFrame;
  outline: XY[];
  holes: XY[][];
  /** 메시 층: 요소 중심 [a, b, pid] */
  points?: [number, number, number][] | null;
  /** 노드 층 */
  nodes?: XY[] | null;
  beads?: PlanBead[] | null;
  /** label 이 있으면 B 고정 클러스터(큰 점 + 툴팁), 없으면 고정 노드(작은 점). xfer = v0.18.0 ③ A 고정 이전 노드(테 두른 점) */
  fixed?: { label?: string; kind?: string; a: number; b: number; xfer?: boolean }[] | null;
  /** v0.18.0 ③ 평가 영역(주 시트) 외곽 고리 — 자료가 있을 때만 */
  region?: XY[][] | null;
  loads?: { entry_id: string; share: number; a: number; b: number }[] | null;
  apoints?: { label: string; a: number; b: number }[] | null;
  /** 경고 연결선(apoints 층과 함께 켜고 끔) */
  links?: DoePlanLink[] | null;
}

export interface PartMesh {
  positions: Float32Array;
  indices: Uint32Array;
  /** 요소 모드(삼각형 → 요소) — 있으면 요소별 색(세그먼트·섬) */
  tri2elem?: Uint32Array | null;
  nElems?: number;
}

export interface Part3DData {
  /** 장면 다시 만들기 기준(같은 key = 같은 형상) */
  key: string;
  mesh: PartMesh;
  /** 요소 색: on(층) = 지금 켜진 층(세그먼트·섬) */
  elemColors?: ((on: (k: LayerKey) => boolean) => Uint8Array | null) | null;
  /** 안 변위(설계 형상): u = 정점 변위 3·n, c = 높이 변화(색), ±vmax, 표시 배율 */
  design?: { u: Float32Array | null; c: Float32Array; vmax: number; scale: number } | null;
  /** 빨간 점(고정 침범 등) 3·n */
  markers?: Float32Array | null;
  /** 선택 맞춤(없으면 버튼 숨김) */
  selectionBbox?: (() => Bbox | null) | null;
  colorMap?: "blues" | "diverging";
  /** 3D 칸 시험 id·이름(없으면 PartView testId + "-3d", "형상 3D") */
  hostTestId?: string;
  ariaLabel?: string;
}

/** 경계 매핑 경고(②③ — 링크 표·경고 수) */
export interface PartWarnings {
  links: DoePlanLink[];
  /** 서버 판정 경고 수(prep.boundary.n_warn) — B 후보 0 이면 선 없이 수만 */
  nWarn: number | null;
  st: DoeSettingsOut | null;
}

/** v0.18.0 ③ select plan-view 보강(계약 §4.2·openapi 미기재 — 백엔드가 주면 씀): region_ab = 평가 영역(주 시트) 외곽 고리 */
export type DoePlanOutStep = import("../../api/types").DoePlanOut & { region_ab?: XY[][] | null };

export interface PartViewData {
  plan: PartPlanData | null;
  scene: Part3DData | null;
  /** 자료가 있는 층(이 순서로 켜기·끄기 칩) */
  layers: LayerKey[];
  warnings: PartWarnings | null;
  /** 강조(고른 변수 행) — 그 비드만 진하게, W 범위 점선, 선택 맞춤 대상 */
  active?: PlanVar | null;
  /** 처음 보기(없으면 평면도가 있으면 평면도) */
  initialMode?: "3d" | "plan";
}
