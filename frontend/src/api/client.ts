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
  422: "입력값을 확인하세요.",
  503: "서버를 사용할 수 없습니다. 잠시 후 다시 시도하세요.",
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

export function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : String(e);
}
