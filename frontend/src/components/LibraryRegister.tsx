// ⑤ 결과 카드 안 보조 버튼 "라이브러리 등록"(계약 §11). PASS 는 바로 등록, FAIL 은 확정 사유 입력 대화상자.
// 이미 등록된(ACTIVE) ESL 결과면 버튼 대신 '등록됨' 표시.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/endpoints";
import { errorText } from "../api/client";
import type { ValidationOut } from "../api/types";
import { NO_PERMISSION } from "../app/AppContext";
import { usePolling } from "../lib/usePolling";
import { Badge } from "./ui";

export function LibraryRegister({ projectId, v, allowed, failLabels }: { projectId: string; v: ValidationOut; allowed: boolean; failLabels: Record<string, string> }) {
  const entries = usePolling(() => api.libraryEntries({ project_id: projectId, status: "ACTIVE" }), 0, [projectId, v.esl_run_id]);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const done = entries.data?.find((e) => e.esl_run_id === v.esl_run_id);

  if (!entries.data) return null;
  if (done)
    return (
      <span className="inline-actions">
        <Badge kind="info">라이브러리 등록됨</Badge>
        <Link className="small" to={`/p/${projectId}/library`}>
          보기
        </Link>
      </span>
    );

  const blocked = !allowed ? NO_PERMISSION : v.stale ? "이전 입력의 검증입니다 — ⑤ 검증을 다시 실행한 뒤 등록하세요" : null;

  async function submit(force_reason?: string) {
    setBusy(true);
    setError(null);
    try {
      await api.createEntry({ esl_run_id: v.esl_run_id, validation_id: v.id, force_reason: force_reason ?? null });
      setOpen(false);
      await entries.reload();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <span className="primary-wrap" title={blocked ?? (v.verdict === "PASS" ? "검증 PASS 결과를 라이브러리에 등록" : "검증 FAIL — 사유를 적고 확정 등록")}>
        <button
          type="button"
          className="btn small"
          disabled={!!blocked || busy}
          onClick={() => (v.verdict === "PASS" ? void submit() : (setError(null), setOpen(true)))}
        >
          라이브러리 등록
        </button>
      </span>
      {error && !open && (
        <span className="small error-text" role="alert">
          {error}
        </span>
      )}
      {open && (
        <ReasonDialog
          reasons={v.fail_reasons.map((f) => (failLabels[f] ? `${f} — ${failLabels[f]}` : f))}
          value={reason}
          onChange={setReason}
          busy={busy}
          error={error}
          onCancel={() => setOpen(false)}
          onSubmit={() => void submit(reason.trim())}
        />
      )}
    </>
  );
}

function ReasonDialog({
  reasons,
  value,
  onChange,
  busy,
  error,
  onCancel,
  onSubmit,
}: {
  reasons: string[];
  value: string;
  onChange: (s: string) => void;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const area = useRef<HTMLTextAreaElement>(null);
  const [touched, setTouched] = useState(false);
  useEffect(() => {
    area.current?.focus();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onCancel]);
  const empty = !value.trim();
  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="reg-title">
        <h3 id="reg-title">검증 FAIL 결과를 라이브러리에 등록</h3>
        <div className="small">이 결과는 판정 기준을 넘었습니다. 그래도 하중 근거로 쓸 이유를 적어 확정하세요(기록에 남습니다).</div>
        <ul className="reasons small">
          {reasons.map((r) => (
            <li key={r} className="error-text">
              {r}
            </li>
          ))}
        </ul>
        <label className="field">
          <span className="field-label">확정 사유 (필수)</span>
          <textarea ref={area} rows={3} value={value} onChange={(e) => (setTouched(true), onChange(e.target.value))} aria-invalid={empty && touched} placeholder="예: 누적 소성 시나리오 — 최대변형률 오차는 소성 영역 탄성 근사 한계로 확인" />
        </label>
        {error && (
          <div className="error-text small" role="alert">
            {error}
          </div>
        )}
        <div className="actions modal-actions">
          <button type="button" className="btn ghost" onClick={onCancel}>
            취소
          </button>
          <span className="primary-wrap" title={empty ? "사유를 입력하세요" : undefined}>
            <button type="button" className="btn primary" disabled={empty || busy} onClick={onSubmit}>
              {busy ? "처리 중…" : "확정 등록"}
            </button>
          </span>
        </div>
      </div>
    </div>
  );
}
