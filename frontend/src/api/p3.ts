// P3-UX API(계약 esl_p3_ux.md §1~§3·§6·§8). check:api 가 endpoints.ts 와 함께 이 파일의 경로도 openapi 와 대조한다.
import { API_PREFIX, ApiError, buildUrl, request } from "./client";
import type {
  ApiErrorDetail, BrowseOut, CaseCreate, CaseOut, ChangelogEntry, ClientCodeOut, ClientTokenOut, UploadChunkOut, UploadCompleteOut, UploadCreate, UploadFileIn, UploadOut, UploadState, VersionOut,
} from "./types";

export const BUNDLE_PARTS_DEFAULT = "export,report,summary";

export const p3 = {
  /** §6: h3d_path 또는 results_dir 중 하나 */
  createCase: (body: CaseCreate) => request<CaseOut>("POST", "/cases", { body }),
  createUpload: (body: UploadCreate) => request<UploadOut>("POST", "/uploads", { body }),
  /** 내 업로드 목록(최근 50개). state=OPEN 이면 사용자당 한도(UPLOAD_LIMIT)에 걸리는 진행 중 업로드 */
  uploads: (state?: UploadState) => request<UploadOut[]>("GET", "/uploads", { query: { state } }),
  upload: (id: string) => request<UploadOut>("GET", `/uploads/${id}`),
  /** 누락 include 추가 등록 */
  addUploadFiles: (id: string, files: UploadFileIn[]) => request<UploadOut>("POST", `/uploads/${id}/files`, { body: { files } }),
  completeUpload: (id: string) => request<UploadCompleteOut>("POST", `/uploads/${id}/complete`, { body: {} }),
  cancelUpload: (id: string) => request<UploadOut>("DELETE", `/uploads/${id}`),
  /** v0.6.0 US-17: 업로드 목록에서 파일 하나 빼기(index 유지, 서버는 _backup 으로 이동). 이미 뺐으면 200 */
  removeUploadFile: (id: string, index: number) => request<UploadOut>("DELETE", `/uploads/${id}/files/${index}`),
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

/** 청크 PUT(application/octet-stream). 실패하면 ApiError(0 = 네트워크, code ABORTED = 사용자가 멈춤).
 *  data 가 ArrayBuffer 면 sha256 계산에 쓴 같은 버퍼를 그대로 본문으로(두 번 읽지 않음). 429 는 detail.retry_after(초) */
export async function putChunk(uploadId: string, index: number, offset: number, data: Blob | ArrayBuffer, sha256?: string | null, signal?: AbortSignal): Promise<UploadChunkOut> {
  let res: Response;
  const headers: Record<string, string> = { "Content-Type": "application/octet-stream", "X-ESL-Request": "1", Accept: "application/json" };
  if (sha256) headers["X-Chunk-Sha256"] = sha256;
  try {
    res = await fetch(buildUrl(`/uploads/${uploadId}/files/${index}`, { offset }), {
      method: "PUT",
      headers,
      credentials: "same-origin",
      body: data,
      signal,
    });
  } catch (e) {
    if (signal?.aborted || (e instanceof DOMException && e.name === "AbortError")) throw new ApiError(0, { code: "ABORTED", message: "멈춤" });
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
    const ra = Number(res.headers.get("Retry-After"));
    if (res.status === 429 && ra > 0 && detail.retry_after === undefined) detail = { ...detail, retry_after: ra };
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as UploadChunkOut;
}
