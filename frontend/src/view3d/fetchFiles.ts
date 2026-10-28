// view3d 바이너리 파일(part.glb · part_lod.glb · values.bin) 받기. 오류 본문 {detail:{code,message}} 는 ApiError 로.
import { API_PREFIX, ApiError } from "../api/client";
import type { ApiErrorDetail, View3dOut } from "../api/types";

/** manifest 의 파일 URL(API 루트 기준 경로 `/esl-runs/{id}/view3d/part.glb`, 접두 /esl/api 없음)을 요청 주소로.
 *  api 클라이언트와 같이 API_PREFIX 를 붙이고 `?key=<manifest.key>` 를 단다(409 VIEW3D_STALE 감지). 파일 이름만 오면 view3d 아래로 본다. */
export function resolveFileUrl(runId: string, urlOrName: string, key?: string): string {
  let url: string;
  if (/^https?:\/\//.test(urlOrName)) url = urlOrName;
  else if (urlOrName.startsWith("/")) url = urlOrName.startsWith(`${API_PREFIX}/`) ? urlOrName : API_PREFIX + urlOrName;
  else url = `${API_PREFIX}/esl-runs/${runId}/view3d/${urlOrName.replace(/^\.?\//, "")}`;
  return key && !url.includes("?") ? `${url}?key=${encodeURIComponent(key)}` : url;
}

export function fileUrls(m: View3dOut): { geometry: string; lod: string | null; values: string } {
  return {
    geometry: resolveFileUrl(m.esl_run_id, m.geometry_url || m.geometry.name, m.key),
    lod: m.lod ? resolveFileUrl(m.esl_run_id, m.lod_url || m.lod.name, m.key) : null,
    values: resolveFileUrl(m.esl_run_id, m.values_url || m.values.name, m.key),
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
