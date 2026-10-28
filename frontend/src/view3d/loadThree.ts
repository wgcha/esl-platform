// three 청크 지연 적재(계약 §8): ④ 화면에서 3D 카드가 마운트될 때만 `import("./scene")` — 메인 청크에 three 없음.
import type { SceneModule } from "./sceneApi";

let cached: Promise<SceneModule> | null = null;

export function loadScene(): Promise<SceneModule> {
  if (!cached) {
    cached = import("./scene").catch((e) => {
      cached = null; // 일시 실패 후 재시도 허용
      throw e;
    });
  }
  return cached;
}
