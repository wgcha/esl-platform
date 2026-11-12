// v0.19.0 목록 항목 삭제(esl_item_delete.md §5): 행마다 작은 "삭제" 버튼 1개 — 강성 평가 스터디·비드 최적화·종합 분석·버전 비교 공용.
// 클릭 → delete-check(연쇄 대상 개수) → 행 안 확인 줄 [영구 삭제] [취소](Templates.tsx 방식). 다중 선택 없음.
// can_delete=false → "–"(툴팁), delete_blocked → 비활성 + 사유 툴팁, check.blocked 가 있으면 확인 없이 사유·job 링크만.
import { useState } from "react";
import { Link, useParams, type NavigateFunction } from "react-router-dom";
import { ApiError, errorText } from "../api/client";
import { api } from "../api/endpoints";
import { doe } from "../api/doe";
import { opt } from "../api/opt";
import type { DeleteBlockOut, DeleteCheckOut, DeleteKind, DeleteOut } from "../api/types";

const FOLDER: Record<DeleteKind, string> = { DOE: "_doe", OPT: "_opt", ANALYSIS: "_analysis", COMPARE: "_compare" };
const GONE_CODES = ["DOE_NOT_FOUND", "OPT_RUN_NOT_FOUND", "ANALYSIS_NOT_FOUND", "COMPARISON_NOT_FOUND", "ITEM_DELETED"];

const API: Record<DeleteKind, { check: (id: string) => Promise<DeleteCheckOut>; remove: (id: string) => Promise<DeleteOut> }> = {
  DOE: { check: doe.deleteCheck, remove: doe.remove },
  OPT: { check: opt.deleteCheck, remove: opt.remove },
  ANALYSIS: { check: api.analysisDeleteCheck, remove: api.deleteAnalysis },
  COMPARE: { check: api.comparisonDeleteCheck, remove: api.deleteComparison },
};

/** 삭제 오류 코드 → 한국어 문구(서버 메시지 대신). 모르는 코드는 errorText */
export const DELETE_ERROR_TEXT: Record<string, string> = {
  NOT_ITEM_OWNER: "등록자·관리자만 삭제할 수 있습니다.",
  ITEM_BUSY: "진행 중인 작업이 있어 지금은 삭제할 수 없습니다 — 끝나거나 취소된 뒤 다시 시도하세요.",
  FILE_LOCKED: "파일이 열려 있습니다(보고서·3D 보기 창을 닫고 다시).",
  PATH_UNSAFE: "작업 폴더 경로가 안전하지 않아 삭제하지 않았습니다 — 관리자에게 알리세요.",
  ITEM_DELETE_DISABLED: "삭제 기능이 서버에서 꺼져 있습니다(관리자 문의).",
  CONFIG_INVALID: "서버 설정에 문제가 있어 삭제할 수 없습니다 — 관리자에게 알리세요.",
  FORBIDDEN: "이 프로젝트에서 실행 권한이 없습니다.",
};

/** 409 ITEM_BUSY 의 details.blocked[] (details 아래 또는 detail 바로 아래) */
export function blockedOf(e: unknown): DeleteBlockOut[] {
  if (!(e instanceof ApiError)) return [];
  const d = e.detail.details as { blocked?: DeleteBlockOut[] } | undefined;
  const b = d?.blocked ?? (e.detail.blocked as DeleteBlockOut[] | undefined);
  return Array.isArray(b) ? b : [];
}

export function deleteErrorText(e: unknown): string {
  if (e instanceof ApiError && DELETE_ERROR_TEXT[e.code]) return DELETE_ERROR_TEXT[e.code];
  return errorText(e);
}

/** 상세 화면 조회가 404(항목 없음·삭제됨)면 해당 목록으로 이동하고 오류는 그대로 던진다(§5 상세 페이지) */
export const goneToList = (nav: NavigateFunction, listPath: string) => (e: unknown): never => {
  if (e instanceof ApiError && e.status === 404 && GONE_CODES.includes(e.code)) nav(listPath, { replace: true });
  throw e;
};

/** 확인 문구(§5) — 개수는 delete-check 값 */
export function confirmText(c: DeleteCheckOut): string {
  const tail8 = c.id.slice(0, 8);
  const parts = [`실행 이력 ${c.n_jobs}건`];
  if (c.kind === "DOE") parts.push(`검증 낙하 ${c.n_verify_drops}건`);
  return `'${c.title}'을(를) 영구 삭제합니다. ${parts.join("·")}과 esl 작업 폴더(${FOLDER[c.kind]}/…${tail8})가 지워지며 되돌릴 수 없습니다. 올린 입력 파일·SPDM·SCX 드라이브 파일은 그대로 둡니다.`;
}

type Phase = { t: "idle" } | { t: "checking" } | { t: "confirm"; c: DeleteCheckOut } | { t: "blocked"; list: DeleteBlockOut[] } | { t: "deleting"; c: DeleteCheckOut };

export function ItemDeleteButton({
  kind,
  id,
  title,
  canDelete,
  deleteBlocked,
  onDeleted,
}: {
  kind: DeleteKind;
  id: string;
  title: string;
  canDelete: boolean;
  deleteBlocked: string | null;
  onDeleted: (msg: string) => void;
}) {
  const { projectId = "" } = useParams();
  const [ph, setPh] = useState<Phase>({ t: "idle" });
  const [error, setError] = useState<string | null>(null);
  const done = () => onDeleted(`'${title}' 삭제됨`);

  if (!canDelete) return <span className="small muted" title="등록자·관리자만 삭제할 수 있습니다">–</span>;

  async function start() {
    setError(null);
    setPh({ t: "checking" });
    try {
      const c = await API[kind].check(id);
      setPh(c.blocked.length || !c.can_delete ? { t: "blocked", list: c.blocked } : { t: "confirm", c });
    } catch (x) {
      if (x instanceof ApiError && x.code === "ITEM_DELETED") return done();
      setError(deleteErrorText(x));
      setPh({ t: "idle" });
    }
  }

  async function remove(c: DeleteCheckOut) {
    setError(null);
    setPh({ t: "deleting", c });
    try {
      await API[kind].remove(id);
      done();
    } catch (x) {
      if (x instanceof ApiError && x.code === "ITEM_DELETED") return done();
      const list = x instanceof ApiError && x.code === "ITEM_BUSY" ? blockedOf(x) : [];
      if (list.length) return setPh({ t: "blocked", list });
      setError(deleteErrorText(x));
      setPh({ t: "confirm", c });
    }
  }

  if (ph.t === "idle" || ph.t === "checking") {
    const off = !!deleteBlocked || ph.t === "checking";
    return (
      <span className="inline-actions" title={deleteBlocked ?? undefined}>
        <button type="button" className="btn small ghost" disabled={off} onClick={start} title={deleteBlocked ?? undefined}>
          삭제
        </button>
        {error && <span className="small error-text" role="alert" style={{ whiteSpace: "normal", maxWidth: "26rem" }}>{error}</span>}
      </span>
    );
  }
  if (ph.t === "blocked") {
    return (
      <div className="inline-actions" style={{ whiteSpace: "normal", maxWidth: "28rem" }} data-testid="delete-blocked">
        <span className="small error-text">지금은 삭제할 수 없습니다 — 먼저 끝내거나 취소하세요.</span>
        <ul className="reasons small" style={{ margin: 0, paddingLeft: "1.1rem", flexBasis: "100%" }}>
          {ph.list.map((b, i) => (
            <li key={i}>
              {b.message}
              {b.job_id && (
                <>
                  {" "}
                  <Link to={`/p/${projectId}/jobs/${b.job_id}`}>작업 보기</Link>
                </>
              )}
            </li>
          ))}
        </ul>
        <button type="button" className="btn small ghost" onClick={() => setPh({ t: "idle" })}>
          닫기
        </button>
      </div>
    );
  }
  const c = ph.c;
  const busy = ph.t === "deleting";
  return (
    <div className="inline-actions" style={{ whiteSpace: "normal", maxWidth: "30rem" }} data-testid="delete-confirm">
      <span className="small error-text" style={{ flexBasis: "100%" }}>
        {confirmText(c)}
        {c.kind === "ANALYSIS" && c.n_opt_unlinked > 0 ? ` 이 분석으로 만든 비드 최적화 ${c.n_opt_unlinked}건은 남고 연결만 끊깁니다.` : ""}
      </span>
      <button type="button" className="btn small danger" disabled={busy} onClick={() => void remove(c)}>
        영구 삭제
      </button>
      <button type="button" className="btn small ghost" disabled={busy} onClick={() => setPh({ t: "idle" })}>
        취소
      </button>
      {error && (
        <span className="small error-text" role="alert" style={{ flexBasis: "100%" }}>
          {error}
        </span>
      )}
    </div>
  );
}
