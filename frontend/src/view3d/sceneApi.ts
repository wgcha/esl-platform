// 장면 인터페이스(three 에 의존하지 않음). View3DCard 는 이 인터페이스만 알고, 구현(scene.ts)은 동적 import 로 별도 청크에서 적재한다.
// 시험에서는 이 인터페이스를 흉내 내는 mock 을 끼운다.
import type { ArrowSpec } from "./arrows";
import type { V3 } from "./pick";
import type { SupportSpec } from "./supports";

export interface GeoData {
  /** float32 mm, 길이 3n */
  positions: Float32Array;
  indices: Uint32Array;
  /** LOD 일 때 원 정점 번호(_SRC), 전체 해상도면 null */
  src: Uint32Array | null;
}

export type PickEvent =
  | { type: "arrow"; index: number }
  | { type: "vertex"; vertex: number }
  | { type: "support"; index: number }
  | { type: "none" };

export interface SceneOptions {
  background: string;
  /** bbox 대각선(mm) — 화살표·기호 크기 기준 */
  diag: number;
  bbox: { min: number[]; max: number[] };
}

export interface SceneApi {
  /** 부품 표면. lod 가 있으면 조작 중에는 lod, 멈춘 뒤 250 ms 후 full */
  setGeometry(full: GeoData, lod: GeoData | null): void;
  /** 정점 색(선형 공간) — values 는 원 정점 순서 */
  setColors(values: Float32Array, min: number, max: number): void;
  /** 변형 형상: 위치 = base + k·u. u = null 이면 원형 */
  setDeform(u: Float32Array | null, k: number): void;
  setArrows(arrows: ArrowSpec[], selectedIndex: number | null): void;
  setSupports(supports: SupportSpec[]): void;
  /** 선택 강조: 화살표 번호(null 없음) + 노드 표식 정점(null 없음) */
  select(arrowIndex: number | null, vertex: number | null): void;
  /** 카메라 중심을 이 점으로(더블클릭) */
  focus(point: V3): void;
  /** bbox 맞춤(등각 +X+Y+Z, up = +Z) */
  fit(): void;
  onPick(cb: (e: PickEvent) => void): void;
  stats(): { renders: number };
  dispose(): void;
}

export type CreateScene = (canvas: HTMLCanvasElement, opts: SceneOptions) => SceneApi;
export interface SceneModule {
  createScene: CreateScene;
}
