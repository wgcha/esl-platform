// ④ 3D 뷰어 마우스 조작 상수(v0.12.5, 자유 회전). three 에 의존하지 않는다 — scene.ts 가 TrackballControls 에 적용한다.
// 체감은 v0.12.3 까지의 OrbitControls 기본값(rotateSpeed 1, zoomSpeed 1, 감쇠 없음, 화면 공간 팬)에 맞췄다.

/** 회전 감도: 화면 높이만큼 끌면 몇 바퀴 도는가(OrbitControls 기본 = 1 바퀴/화면 높이) */
export const ROTATE_TURNS_PER_HEIGHT = 1;
/**
 * 휠 줌 감도(TrackballControls.zoomSpeed). 휠 한 칸(deltaY 100 px) 의 배율 = 1 + 0.025·이 값
 * → 2.1 이면 1.0525 ≈ 1/0.95(OrbitControls 기본 한 칸 5 %)
 */
export const WHEEL_ZOOM_SPEED = 2.1;
/** 팬 감도: 1 = 커서를 그대로 따라감(타깃 깊이 기준, 원근·직교 공통) */
export const PAN_SPEED = 1;
/** 감쇠(관성) 없음 — 손을 떼면 바로 멈춘다(기존과 같음) */
export const STATIC_MOVING = true;

/** TrackballControls.rotateSpeed: 마우스 좌표가 화면 폭 절반 = 1 로 정규화되므로 화면비를 곱해 높이 기준 감도로 맞춘다 */
export function trackballRotateSpeed(widthPx: number, heightPx: number, turnsPerHeight = ROTATE_TURNS_PER_HEIGHT): number {
  const w = Math.max(1, widthPx);
  const h = Math.max(1, heightPx);
  // 1 px 당 각도: Orbit = 2π·turns/h, Trackball = speed·2/w → speed = π·turns·w/h
  return (Math.PI * turnsPerHeight * w) / h;
}
