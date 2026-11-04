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
  // v0.12.1 h3d 변형률 결과 대체(esl_strain_fallback.md §3·§4·§5)
  H3D_NO_STRAIN_SOURCE: "h3d 에 변형률·응력 결과가 없음 — 덱 /H3D 출력 확인",
  H3D_NO_EPSP: "h3d 에 소성 변형률(Plastic Strain)이 없어 epsp=0 으로 처리했습니다.",
  STRAIN_TMAX_SAMPLED: "변형률 최대를 h3d 출력 프레임에서 재현 — ε 과소평가·t* 출력 간격 양자화 가능. 덱에 /H3D/SHELL/TENS/STRAIN/TMAX 출력을 권장합니다.",
  STRAIN_FROM_STRESS: "변형률 결과가 없어 응력(Max_Stress)으로 대체 — 변형률 참고 지표는 생략, 판정은 변위 기준입니다.",
  VD_STRAIN_SOURCE_MISMATCH: "원 낙하와 검증 낙하의 변형률 기준이 다릅니다 — ε 비는 참고만 하세요.",
  // v0.13.0 일괄 실행(esl_run_all.md §7): API 오류 + 멈춤 코드(run_alls.stop_code) + ② 가드 사유(stop_reason.detail.reasons)
  RUN_ALL_ACTIVE: "일괄 실행 중입니다 — 바꾸려면 먼저 [일괄 취소]",
  RUN_ALL_NOT_RUNNING: "진행 중인 일괄 실행이 없습니다.",
  TSTAR_REVIEW_REQUIRED: "t* 확인이 필요합니다 — ②에서 후보를 보고 [t* 확정]",
  SUPPORT_AUTO_BLOCKED: "지지점을 자동으로 정하지 못했습니다 — ②에서 사유 확인",
  SUPPORT_AUTO_ERROR: "지지점 자동 선택 중 오류 — 관리자에게 알리세요.",
  STEP_FAILED: "작업 실패 — 로그 확인 후 [재시도] 또는 입력 수정",
  STEP_INTERRUPTED: "워커가 끊겨 작업이 중단되었습니다",
  VALIDATION_FAIL: "검증 FAIL — 원인 확인 후 ②·③ 조건을 바꿔 [이어서 실행]",
  VALIDATION_UNDETERMINED: "검증 판정 불가 — ④ 결과 확인",
  CASE_CHANGED: "실행 중 Case 가 바뀌었습니다",
  JOB_CANCELED: "작업이 취소되었습니다",
  RUN_ALL_CANCELED: "일괄 실행을 취소했습니다",
  TSTAR_ADJUSTED: "1순위 시점이 변위 추출 프레임에 없어 다른 후보로 바뀌었습니다",
  TSTAR_METRIC_ERROR: "t* 지표 계산에 오류가 있습니다",
  USER_TSTAR_CHANGED: "직접 고른 t* 와 새 자동 t* 가 다릅니다",
  // v0.14.0 ④ 형상 직접 비교(esl_step_compare.md §8) — 원본 문구는 서버 resources/doe_messages.json, 여기는 메시지 없을 때
  COMPARE_DISABLED: "'형상 직접 비교'가 서버에서 꺼져 있습니다(관리자 문의)",
  SHAPES_EMPTY: "비교할 STEP 을 올리세요",
  SHAPES_TOO_FEW: "기준 STEP 외에 비교할 STEP 을 하나 이상 올리세요",
  SHAPES_TOO_MANY: "STEP 개수가 상한을 넘었습니다",
  SHAPES_TOO_LARGE: "STEP 파일 합계 크기가 상한을 넘었습니다",
  SHAPE_NAME_INVALID: "형상 이름이 올바르지 않습니다(1~64자, 제어문자 금지)",
  SHAPE_NAME_DUPLICATE: "형상 이름이 겹칩니다(대소문자 무시)",
  REFERENCE_MULTIPLE: "기준 형상은 하나만 고를 수 있습니다",
  SCENARIO_UNSUPPORTED: "이 시나리오에서는 쓸 수 없는 기능입니다",
  SHAPE_SIZE_MISMATCH: "기준과 크기가 다릅니다(±5 % 밖)",
  SHAPE_MISALIGNED: "기준과 위치·방향이 다릅니다 — 같은 좌표계로 내보낸 STEP 인지 확인하세요",
  COMPARE_REF_CASE_MESH: "기준이 낙하 메시(다른 메싱 방식)라 개선율에 메시 차이가 섞입니다",
  SHAPE_DUPLICATE_FILE: "같은 STEP 파일이 두 번 이상 들어 있습니다",
  SHAPE_QUALITY_FAIL: "메시 품질 Fail 요소 비율이 상한을 넘었습니다(차단 아님 — 결과에 메시 품질 차이가 섞일 수 있음)",
  DEFEATURE_SKIPPED: "작은 구멍 메움을 건너뛰고 그대로 메싱했습니다",
  MESH_FACE_FALLBACK: "일부 면을 다른 2D 알고리즘(또는 제약 해제)으로 메시했습니다 — 그 면 주변 요소 모양이 다를 수 있음",
};

/** 일괄 실행 멈춤 코드 중 일반 API 오류와 이름이 같아 CODE_TEXT 에 넣지 않는 것(errorText 회귀 방지) */
export const RUN_ALL_STOP_TEXT: Record<string, string> = {
  PREREQUISITE_MISSING: "앞 단계가 필요합니다",
  CASE_ARCHIVED: "보관된 Case 입니다",
  FRAME_NOT_CANDIDATE: "현재 t* 프레임이 후보에 없습니다",
};

/** 멈춤·사유 코드 → 사람말(모르는 코드는 그대로) */
export const stopCodeText = (code: string | null | undefined) => (code ? CODE_TEXT[code] ?? RUN_ALL_STOP_TEXT[code] ?? code : "");

/** 경고 문자열(코드 또는 "코드: 상세") → 사람말. 모르는 코드·일반 문구는 그대로 */
export function warnText(w: string): string {
  const m = /^([A-Z][A-Z0-9_]+)(?:\s*[:—-]\s*(.*))?$/s.exec(w.trim());
  if (!m || !CODE_TEXT[m[1]]) return w;
  return m[2] ? `${CODE_TEXT[m[1]]} (${m[2]})` : CODE_TEXT[m[1]];
}

/** 작업 실패 코드·메시지에 들어 있는 원인 코드의 사람말 1줄(워커 step 코드 H3D_EXTRACT_FAILED 메시지에 done.json code 가 실림) */
const FAILURE_HINT_CODES = ["H3D_NO_STRAIN_SOURCE"];
export function failureHint(code: string | null | undefined, message: string | null | undefined): string | null {
  const t = `${code ?? ""} ${message ?? ""}`;
  const k = FAILURE_HINT_CODES.find((c) => t.includes(c));
  return k ? CODE_TEXT[k] : null;
}

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
    // v0.10.0 MR-D-4: ESL_SOLVE 409 PREREQUISITE_MISSING 에 support_blocked=true 면 '② 지지점' 대신 자동 선택 실패 문구
    const miss0: string[] = Array.isArray(e.detail.missing) ? (e.detail.missing as string[]) : [];
    const miss = e.detail.support_blocked === true ? miss0.map((m) => (m === "support_set" ? "support_blocked" : m)) : miss0;
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
