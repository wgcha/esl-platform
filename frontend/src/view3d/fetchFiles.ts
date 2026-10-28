// view3d 바이너리 파일(part.glb · part_lod.glb · values.bin) 받기. 오류 본문 {detail:{code,message}} 는 ApiError 로.
import { API_PREFIX, ApiError } from "../api/client";
import type { ApiErrorDetail, View3dOut } from "../api/types";

/** manifest 의 상대 URL(또는 파일 이름)을 요청 주소로. "/" 로 시작하면 그대로, 아니면 /esl-runs/{id}/view3d/ 아래 */
export function resolveFileUrl(runId: string, urlOrName: string): string {
  if (/^https?:\/\//.test(urlOrName) || urlOrName.startsWith("/")) return urlOrName;
  return `${API_PREFIX}/esl-runs/${runId}/view3d/${urlOrName.replace(/^\.?\//, "")}`;
}

export function fileUrls(m: View3dOut): { geometry: string; lod: string | null; values: string } {
  return {
    geometry: resolveFileUrl(m.esl_run_id, m.geometry_url ?? m.geometry.name),
    lod: m.lod ? resolveFileUrl(m.esl_run_id, m.lod_url ?? m.lod.name) : null,
    values: resolveFileUrl(m.esl_run_id, m.values_url ?? m.values.name),
  };
}

export async function fetchBinary(url: string): Promise<ArrayBuffer> {
  let res: Response;
  try {
    res = await fetch(url, { method: "GET", credentials: "same-origin" });
  } catch {
    throw new ApiError(0, { code: "NETWORK_ERROR", message: "서버에 연결할 수 없습니다." });
  }
  if (!res.ok) {
    let detail: ApiErrorDetail = { code: `HTTP_${res.status}`, message: `요청 실패 (${res.status})` };
    try {
      const b = await res.json();
      if (b && typeof b.detail === "object" && b.detail) detail = { ...detail, ...b.detail };
    } catch {
      /* 본문 없음 */
    }
    throw new ApiError(res.status, detail);
  }
  return res.arrayBuffer();
}
