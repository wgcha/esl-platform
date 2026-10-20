// P3-UX API(계약 esl_p3_ux.md §1~§3·§6·§8). check:api 가 endpoints.ts 와 함께 이 파일의 경로도 openapi 와 대조한다.
import { API_PREFIX, ApiError, buildUrl, request } from "./client";
import type {
  ApiErrorDetail, BrowseOut, CaseCreate, CaseOut, ChangelogEntry, ClientCodeOut, ClientTokenOut, UploadChunkOut, UploadCompleteOut, UploadCreate, UploadFileIn, UploadOut, VersionOut,
} from "./types";

export const BUNDLE_PARTS_DEFAULT = "export,report,summary";

export const p3 = {
  /** §6: h3d_path 또는 results_dir 중 하나 */
  createCase: (body: CaseCreate) => request<CaseOut>("POST", "/cases", { body }),
  createUpload: (body: UploadCreate) => request<UploadOut>("POST", "/uploads", { body }),
  upload: (id: string) => request<UploadOut>("GET", `/uploads/${id}`),
  /** 누락 include 추가 등록 */
  addUploadFiles: (id: string, files: UploadFileIn[]) => request<UploadOut>("POST", `/uploads/${id}/files`, { body: { files } }),
  completeUpload: (id: string) => request<UploadCompleteOut>("POST", `/uploads/${id}/complete`, { body: {} }),
  cancelUpload: (id: string) => request<UploadOut>("DELETE", `/uploads/${id}`),
  browse: (root?: number, path?: string, offset?: number) => request<BrowseOut>("GET", "/fs/browse", { query: { root, path, offset } }),
  version: () => request<VersionOut>("GET", "/version"),
  /** §9.1 PC 연결 코드(6자리·15분·1회용, 현재 프로젝트) — power 이상 */
  createClientCode: (projectId: string) => request<ClientCodeOut>("POST", "/client-tokens/codes", { body: { project_id: projectId } }),
  /** 내 연결된 PC(토큰) 목록 */
  clientTokens: (projectId?: string) => request<ClientTokenOut[]>("GET", "/client-tokens", { query: { project_id: projectId } }),
  revokeClientToken: (id: string) => request<ClientTokenOut>("DELETE", `/client-tokens/${id}`),
  changelog: () => request<ChangelogEntry[]>("GET", "/changelog"),
  caseBundleUrl: (caseId: string, parts = BUNDLE_PARTS_DEFAULT) => `${API_PREFIX}/cases/${caseId}/bundle` + `?parts=${encodeURIComponent(parts)}`,
  analysisBundleUrl: (id: string, parts = "report,deck,csv") => `${API_PREFIX}/library/analyses/${id}/bundle` + `?parts=${encodeURIComponent(parts)}`,
};

/** 청크 PUT(application/octet-stream). 실패하면 ApiError(0 = 네트워크) */
export async function putChunk(uploadId: string, index: number, offset: number, data: Blob, sha256?: string | null): Promise<UploadChunkOut> {
  let res: Response;
  const headers: Record<string, string> = { "Content-Type": "application/octet-stream", "X-ESL-Request": "1", Accept: "application/json" };
  if (sha256) headers["X-Chunk-Sha256"] = sha256;
  try {
    res = await fetch(buildUrl(`/uploads/${uploadId}/files/${index}`, { offset }), {
      method: "PUT",
      headers,
      credentials: "same-origin",
      body: data,
    });
  } catch {
    throw new ApiError(0, { code: "NETWORK_ERROR", message: "서버에 연결할 수 없습니다." });
  }
  if (!res.ok) {
    let detail: ApiErrorDetail = { code: res.status === 507 ? "INSUFFICIENT_STORAGE" : `HTTP_${res.status}`, message: `청크 전송 실패 (${res.status})` };
    try {
      const b = await res.json();
      if (b && typeof b.detail === "object" && b.detail) detail = { ...detail, ...b.detail };
    } catch {
      /* 본문 없음 */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as UploadChunkOut;
}
