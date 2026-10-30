// v0.11.0 SCX 릴레이 API(계약 esl_scx_relay.md §7 — 기능 A: SCX 드라이브에서 고르기). check:api 가 이 파일의 경로도 openapi 와 대조한다.
// 문구(사유·오류)는 서버가 resources/scx_messages.json 에서 만든다 — 화면은 받은 문구를 표시만 한다.
import { request } from "./client";
import type { ScxBrowseOut, ScxFetchIn, ScxFetchOut, ScxStatusOut, UploadOut } from "./types";

/** 업로드 세션 client.name — SCX 워커가 받은 세션(§9.1) */
export const SCX_UPLOAD_CLIENT = "scx-relay";

/** SCX 에서 받은 세션인지: 서버는 files[].source = "scx" 를 주고, 세션 client 는 그 파일 항목의 client 에서 온다
 *  (워커가 첫 파일을 배치하기 전에는 client 가 null) — 둘 중 하나면 SCX */
export function isScxUpload(u: Pick<UploadOut, "client" | "files">): boolean {
  return u.client?.name === SCX_UPLOAD_CLIENT || (u.files ?? []).some((f) => f.source === "scx" && !f.removed);
}

export const scx = {
  /** §7: 기능별 사용 가능 여부·허용 루트(항상 200, 헬스 TTL 캐시) */
  status: (projectId: string) => request<ScxStatusOut>("GET", "/scx/status", { query: { project_id: projectId } }),
  /** 폴더 목록(폴더 먼저·이름 순, offset·limit 페이지) */
  browse: (projectId: string, root: string, path: string, offset?: number) =>
    request<ScxBrowseOut>("GET", "/scx/browse", { query: { project_id: projectId, root, path, offset } }),
  /** 202: 업로드 세션 + SCX_FETCH(XFER) 작업 */
  createFetch: (body: ScxFetchIn) => request<ScxFetchOut>("POST", "/scx/fetches", { body }),
};

/** 일반 사용자용 짧은 사유: 서버 문구 끝의 괄호(관리자 조치 안내)를 뗀다. 관리자는 전체 문구·코드를 본다. */
export function shortReason(reason: string | null | undefined): string {
  const r = (reason ?? "").trim();
  const k = r.search(/\s*[(（]/);
  return (k > 0 ? r.slice(0, k) : r) || r;
}

/** 루트 기준 상대 경로 이어 붙이기("" 루트) */
export const relJoin = (dir: string, name: string) => (dir ? `${dir}/${name}` : name);
