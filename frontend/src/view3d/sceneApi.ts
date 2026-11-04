// 장면 인터페이스(three 에 의존하지 않음). View3DCard 는 이 인터페이스만 알고, 구현(scene.ts)은 동적 import 로 별도 청크에서 적재한다.
// 시험에서는 이 인터페이스를 흉내 내는 mock 을 끼운다.
import type { ArrowSpec } from "./arrows";
import type { V3 } from "./pick";
import type { Projection } from "./projection";
import type { SupportSpec } from "./supports";
import type { IdPatch, Rect } from "./select/lasso";

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
  /** 처음 투영(없으면 DEFAULT_PROJECTION = 직교) */
  projection?: Projection;
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
  /** 투영 전환(원근/직교) — 위치·타깃·방향 보존, 전환 전후 타깃 거리의 보이는 높이 같음 */
  setProjection(p: Projection): void;
  projection(): Projection;
  onPick(cb: (e: PickEvent) => void): void;
  stats(): { renders: number };
  dispose(): void;

  // ---- v0.15.0 비드 직접 선택(esl_bead_select.md §11.2) — 선택 모드 전용, 위 메서드 동작은 그대로. 없는 구현(시험 mock)은 선택 모드를 못 씀
  /** 표면 색표: blues(기본) · diverging(발산 ±, §7.3) */
  setColorMap?(map: "blues" | "diverging"): void;
  /** 요소 모드 시작: 삼각형 t → 요소 tri2elem[t]. 이후 표면 = 요소별 평면 음영(setElemColors) */
  setElements?(tri2elem: Uint32Array, nElems: number): void;
  /** 요소별 RGBA(sRGB 8비트, 길이 4·nElems) */
  setElemColors?(rgba: Uint8Array): void;
  /** 화면 좌표(client px) 아래 보이는 요소(Raycaster faceIndex → tri2elem) */
  pickElem?(clientX: number, clientY: number): { elem: number; point: V3 } | null;
  /** 보이는 면만: 요소 번호 + 1 을 24비트 색으로 그린 오프스크린 버퍼의 rect(캔버스 CSS px) 조각 */
  idBuffer?(rect: Rect): IdPatch;
  /** 관통 선택: 요소 중심(3·n) → 화면 CSS px(2·n, 화면 밖 = NaN) */
  projectCentroids?(centroids: Float32Array): Float32Array;
  /** 경계선(검정 2 px) — 선분 끝점 6 개씩, null = 지움 */
  setOverlayLines?(segments: Float32Array | null): void;
}

export type CreateScene = (canvas: HTMLCanvasElement, opts: SceneOptions) => SceneApi;
export interface SceneModule {
  createScene: CreateScene;
}
