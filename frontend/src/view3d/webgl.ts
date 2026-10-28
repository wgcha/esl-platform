// WebGL 사용 가능 여부(계약 §5: 불가하면 안내 + 표 유지). 시험에서는 vi.mock 으로 바꾼다.
export function hasWebGL(): boolean {
  try {
    if (typeof document === "undefined") return false;
    if (/jsdom/i.test(navigator.userAgent)) return false; // 시험 환경: getContext 미구현 경고를 피한다
    const c = document.createElement("canvas");
    // jsdom 은 getContext 가 구현되어 있지 않아 null/undefined(또는 "Not implemented" 경고)
    const gl = c.getContext("webgl2") || c.getContext("webgl");
    return !!gl;
  } catch {
    return false;
  }
}
