// esl.md §5: 접두 /esl/api, 비GET에 X-ESL-Request: 1, 오류 {detail:{code,message}}.
import type { ApiErrorDetail } from "./types";

export const API_PREFIX = "/esl/api";

export class ApiError extends Error {
  status: number;
  code: string;
  detail: ApiErrorDetail;
  constructor(status: number, detail: ApiErrorDetail) {
    super(detail.message);
    this.status = status;
    this.code = detail.code;
    this.detail = detail;
  }
}

const FALLBACK: Record<number, string> = {
  401: "로그인이 필요합니다. 대시보드에서 로그인하세요.",
  403: "권한이 없습니다.",
  404: "대상을 찾을 수 없습니다.",
  409: "현재 상태에서는 처리할 수 없습니다.",
  413: "파일이 커서 다운로드 대신 경로를 복사하세요.",
  422: "입력값을 확인하세요.",
  503: "서버를 사용할 수 없습니다. 잠시 후 다시 시도하세요.",
  507: "서버 저장 공간이 부족합니다 — 관리자에게 알리거나, PC에서 추출한 결과 폴더(수백 MB)만 올리세요.",
};

type Query = Record<string, string | number | boolean | null | undefined>;

export function buildUrl(path: string, query?: Query): string {
  let url = API_PREFIX + path;
  if (query) {
    const qs = Object.entries(query)
      .filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join("&");
    if (qs) url += "?" + qs;
  }
  return url;
}

export async function request<T>(method: string, path: string, opts: { query?: Query; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-ESL-Request"] = "1";
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method,
      headers,
      credentials: "same-origin",
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    });
  } catch {
    throw new ApiError(0, { code: "NETWORK_ERROR", message: "서버에 연결할 수 없습니다." });
  }
  if (!res.ok) {
    let detail: ApiErrorDetail = { code: `HTTP_${res.status}`, message: FALLBACK[res.status] ?? `요청 실패 (${res.status})` };
    try {
      const b = await res.json();
      if (b && typeof b.detail === "object" && b.detail) detail = { ...detail, ...b.detail };
    } catch {
      /* 본문 없음 */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** 오류 코드별 안내(서버 메시지 대신) */
export const CODE_TEXT: Record<string, string> = {
  JOB_NOT_TERMINAL: "작업이 아직 끝나지 않았습니다 — 실패·중단·취소된 작업만 재시도할 수 있습니다.",
  JOB_TERMINAL: "이미 끝난 작업입니다.",
  CASE_JOB_BUSY: "같은 작업이 이미 대기 중이거나 실행 중입니다.",
  ARTIFACT_TOO_LARGE: "파일이 커서 다운로드 대신 경로를 복사하세요.",
  CSRF_HEADER_REQUIRED: "요청 헤더(X-ESL-Request)가 없습니다.",
  ENTRY_EXISTS: "이 ESL 결과는 이미 라이브러리에 등록되어 있습니다.",
  VALIDATION_NOT_PASS: "변위 기준 PASS만 라이브러리에 등록할 수 있습니다 — FAIL 사유는 [결과 받기(zip)]로 확인하세요.",
  VALIDATION_LEGACY: "이전 판정 체계 결과는 등록할 수 없습니다 — ④에서 다시 검증하세요.",
  ENTRY_NOT_ELIGIBLE: "LEGACY·FAIL·판정 불가 항목이 섞여 있습니다 — 재검증 후 사용하세요.",
  SUPPORT_CHECK_FAILED: "지정한 지지 노드가 품질 검사를 통과하지 못했습니다.",
  TOO_MANY_ENTRIES: "한 번에 내보낼 수 있는 ESL 수를 넘었습니다.",
  ENTRY_FILES_MISSING: "라이브러리 항목 파일(raw.npz·entry.json)이 없습니다 — 관리자에게 알리세요.",
  EXPORT_NOT_READY: "내보내기가 아직 진행 중입니다.",
  EXPORT_FAILED: "성공한 항목이 없어 zip 을 만들 수 없습니다.",
  MAPPING_DEGENERATE: "대상 메시로 하중을 옮길 수 없는 항목이 있습니다(매핑 퇴화) — 필터에서 빼고 다시 실행하세요.",
  GRID_MISMATCH: "항목들의 정규화 격자가 달라 대상 없이 묶을 수 없습니다 — 설계 대상을 고르세요.",
  NORMALIZATION_META_MISSING: "질량 정규화에 필요한 제품 질량이 없는 항목이 있습니다 — 라이브러리에서 입력하세요.",
  BUNDLE_EMPTY: "받을 결과가 아직 없습니다 — ④ 검증(보고서)을 먼저 실행하세요.",
  INSUFFICIENT_STORAGE: "서버 저장 공간이 부족합니다 — 관리자에게 알리거나, PC에서 추출한 결과 폴더(수백 MB)만 올리세요.",
  CHUNK_SHA256_MISMATCH: "전송 중 손상된 청크가 있습니다 — '이어 올리기'로 다시 보내세요.",
  VERSION_CONFLICT: "다른 사용자가 먼저 수정했습니다 — 새로 고친 뒤 다시 시도하세요.",
};

const MISSING_TEXT: Record<string, string> = {
  extract: "① 추출",
  tstar: "② t*",
  support_set: "② 지지점",
  support_blocked: "② 지지점 자동 선택 실패 — ②에서 사유 확인",
  disp_frame: "t* 프레임 변위",
  esl_run: "③ ESL 결과",
  current_esl_run: "현재 ESL 결과",
  fresh_esl_run: "최신 ESL 결과(③ 다시 계산)",
};

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const base = CODE_TEXT[e.code] ?? e.message;
    const miss = Array.isArray(e.detail.missing) ? e.detail.missing : [];
    return miss.length ? `${base} (필요: ${miss.map((m) => MISSING_TEXT[m] ?? m).join(", ")})` : base;
  }
  return e instanceof Error ? e.message : String(e);
}

/** 파일 다운로드(GET). 실패하면 ApiError(413 ARTIFACT_TOO_LARGE 면 detail.rel·path·size·limit). */
export async function downloadFile(url: string, filename: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(url, { method: "GET", credentials: "same-origin" });
  } catch {
    throw new ApiError(0, { code: "NETWORK_ERROR", message: "서버에 연결할 수 없습니다." });
  }
  if (!res.ok) {
    let detail: ApiErrorDetail = { code: `HTTP_${res.status}`, message: FALLBACK[res.status] ?? `요청 실패 (${res.status})` };
    try {
      const b = await res.json();
      if (b && typeof b.detail === "object" && b.detail) detail = { ...detail, ...b.detail };
    } catch {
      /* 본문 없음 */
    }
    throw new ApiError(res.status, detail);
  }
  const blob = await res.blob();
  if (typeof URL.createObjectURL !== "function") return; // 시험 환경(jsdom)
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}
