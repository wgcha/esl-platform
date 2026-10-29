// ESL 라이브러리 [내보내기] 창(v0.10.0, esl_menu_restructure.md §6.3): 선택한 ESL 여러 개 → 형식·ID 시작 → 진행(2초 폴링) → zip 받기.
// 창을 닫아도 작업은 계속된다. 하단 '최근 내보내기'(GET /library/exports)에서 다시 받는다.
import { useEffect, useState } from "react";
import { ApiError, errorText } from "../api/client";
import { EXPORT_TERMINAL, exportZipName, library, type ExportBatchItem, type ExportBatchOut, type ExportBatchState, type ExportBatchSummary } from "../api/library";
import type { EntryOut, ExportTarget } from "../api/types";
import { dt } from "../lib/format";
import { BundleButton } from "./BundleButton";
import { isEligible } from "../pages/library/common";

export const EXPORT_TARGETS: { key: ExportTarget; label: string; short: string }[] = [
  { key: "radioss_inc", label: "Radioss inc (/CLOAD·/BCS)", short: "inc" },
  { key: "fem", label: "OptiStruct fem", short: "fem" },
  { key: "csv", label: "CSV", short: "csv" },
];
/** 폴링 간격(작업 진행 표시) */
export const EXPORT_POLL_MS = 2000;
export const ZIP_LABEL = "zip 받기";

const BATCH_STATE_LABEL: Record<ExportBatchState, string> = {
  QUEUED: "대기",
  RUNNING: "실행 중",
  SUCCEEDED: "완료",
  PARTIAL: "일부 실패",
  FAILED: "실패",
  CANCELED: "취소",
};

const shortTargets = (ts: ExportTarget[]) => EXPORT_TARGETS.filter((t) => ts.includes(t.key)).map((t) => t.short).join("·");

function ItemState({ it, pct }: { it: ExportBatchItem; pct: number | null }) {
  if (it.state === "DONE") return <span className="st-chip ok">완료</span>;
  if (it.state === "FAILED") return <span className="st-chip bad">실패</span>;
  return pct != null && pct > 0 ? <span className="st-chip run">실행 중 {pct}%</span> : <span className="st-chip wait">대기</span>;
}

function RecentExports({ projectId, current }: { projectId: string; current: string | null }) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<ExportBatchSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    library
      .exportBatches(projectId)
      .then(setRows)
      .catch((e) => setError(errorText(e)));
  }, [open, projectId]);
  return (
    <details className="export-recent" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>최근 내보내기</summary>
      {error && <div className="small error-text">{error}</div>}
      {open && !rows && !error && <div className="small muted">불러오는 중…</div>}
      {rows && rows.length === 0 && <div className="small muted">아직 없습니다</div>}
      {rows && rows.length > 0 && (
        <ul className="export-recent-list" aria-label="최근 내보내기">
          {rows
            .filter((r) => r.batch_id !== current)
            .map((r) => (
              <li key={r.batch_id}>
                <span className="small">
                  {dt(r.created_at)} · ESL {r.n_items}개 · {shortTargets(r.targets)} · {BATCH_STATE_LABEL[r.state]}
                </span>
                {(r.state === "SUCCEEDED" || r.state === "PARTIAL") && (
                  <BundleButton url={library.exportBundleUrl(r.batch_id)} filename={exportZipName(r)} label={ZIP_LABEL} title="이 내보내기의 zip 을 다시 받습니다" />
                )}
              </li>
            ))}
        </ul>
      )}
    </details>
  );
}

export function ExportDialog({ projectId, entries, onClose }: { projectId: string; entries: EntryOut[]; onClose: () => void }) {
  const [targets, setTargets] = useState<ExportTarget[]>(EXPORT_TARGETS.map((t) => t.key));
  const [idMode, setIdMode] = useState<"auto" | "manual">("auto");
  const [idValue, setIdValue] = useState("");
  const [batch, setBatch] = useState<ExportBatchOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nLegacy = entries.filter((e) => !isEligible(e)).length;
  const done = !!batch && EXPORT_TERMINAL.includes(batch.state);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  // 진행 폴링(끝나면 멈춤)
  useEffect(() => {
    if (!batch || done) return;
    const t = setInterval(() => {
      library
        .exportBatch(batch.batch_id)
        .then(setBatch)
        .catch((e) => setError(errorText(e)));
    }, EXPORT_POLL_MS);
    return () => clearInterval(t);
  }, [batch?.batch_id, done]); // eslint-disable-line react-hooks/exhaustive-deps

  const idOk = idMode === "auto" || /^\d+$/.test(idValue.trim());
  const block = !targets.length ? "형식을 하나 이상 고르세요" : !idOk ? "ID 시작은 0 이상 정수입니다" : null;

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const out = await library.createExport({
        project_id: projectId,
        entry_ids: entries.map((e) => e.id),
        targets,
        options: { id_offset: idMode === "auto" ? "auto" : Number(idValue.trim()), id_policy: "per_model_sequential" },
      });
      setBatch(out);
    } catch (e) {
      // R-MR-2: 같은 Case 에 진행 중인 내보내기가 있으면 409 — 잠시 후 다시
      setError(errorText(e) + (e instanceof ApiError && e.code === "CASE_JOB_BUSY" ? " 잠시 후 다시 시도하세요." : ""));
    } finally {
      setBusy(false);
    }
  }

  const pctOf = (it: ExportBatchItem) => batch?.jobs.find((j) => j.case_id === it.case_id)?.progress_pct ?? null;
  const failed = batch?.items.filter((it) => it.state === "FAILED") ?? [];
  const okCount = batch?.items.filter((it) => it.state === "DONE").length ?? 0;
  const jobFail = batch?.jobs.find((j) => j.failure_message);

  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal export-modal" role="dialog" aria-modal="true" aria-labelledby="exp-title">
        <h3 id="exp-title">내보내기 — ESL {entries.length}개</h3>
        {nLegacy > 0 && (
          <div className="small warn-text" data-testid="export-legacy">
            LEGACY {nLegacy}개 포함 — 하중은 같고 판정 체계만 이전입니다
          </div>
        )}
        {!batch ? (
          <>
            <fieldset>
              <legend className="field-label">형식</legend>
              <div className="checks">
                {EXPORT_TARGETS.map((t) => (
                  <label key={t.key} className="check">
                    <input type="checkbox" checked={targets.includes(t.key)} onChange={(e) => setTargets((o) => (e.target.checked ? [...o, t.key] : o.filter((x) => x !== t.key)))} />
                    {t.label}
                  </label>
                ))}
              </div>
            </fieldset>
            <fieldset>
              <legend className="field-label">Radioss·fem ID 시작</legend>
              <div className="checks" role="radiogroup" aria-label="ID 시작">
                <label className="check">
                  <input type="radio" name="id-mode" checked={idMode === "auto"} onChange={() => setIdMode("auto")} />
                  자동(rad 최대 ID 위)
                </label>
                <label className="check">
                  <input type="radio" name="id-mode" checked={idMode === "manual"} onChange={() => setIdMode("manual")} />
                  지정
                </label>
                <input
                  className="mono id-input"
                  inputMode="numeric"
                  aria-label="ID 시작 값"
                  value={idValue}
                  disabled={idMode !== "manual"}
                  aria-invalid={idMode === "manual" && !idOk}
                  onChange={(e) => setIdValue(e.target.value)}
                />
              </div>
              <div className="small muted">같은 모델 ESL은 ID가 겹치지 않게 이어서 배정합니다</div>
            </fieldset>
          </>
        ) : (
          <div className="export-progress" data-testid="export-progress">
            <div className="small">
              {BATCH_STATE_LABEL[batch.state]} · 완료 {okCount}/{batch.items.length} · {shortTargets(batch.targets)}
            </div>
            <div className="table-wrap export-items">
              <table className="table compact" aria-label="내보내기 진행">
                <tbody>
                  {batch.items.map((it) => (
                    <tr key={it.entry_id}>
                      <td className="mono small">{it.label}</td>
                      <td>
                        <ItemState it={it} pct={pctOf(it)} />
                      </td>
                      <td className="small">{it.files.length ? shortTargets(batch.targets) : ""}</td>
                      <td className="small num">{it.id_range ? `ID ${it.id_range[0]}–${it.id_range[1]}` : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {failed.length > 0 && (
              <table className="table compact" aria-label="실패 항목">
                <thead>
                  <tr>
                    <th>실패 항목</th>
                    <th>사유</th>
                  </tr>
                </thead>
                <tbody>
                  {failed.map((it) => (
                    <tr key={it.entry_id}>
                      <td className="mono small">{it.label}</td>
                      <td className="small error-text">{it.error?.message ?? it.error?.code ?? "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {done && okCount === 0 && jobFail && <div className="small error-text">{jobFail.failure_message}</div>}
          </div>
        )}
        {error && (
          <div className="error-text small" role="alert">
            {error}
          </div>
        )}
        <div className="actions modal-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            닫기
          </button>
          {!batch ? (
            <span className="primary-wrap" title={block ?? undefined}>
              <button type="button" className="btn primary" data-primary="true" disabled={!!block || busy} onClick={() => void start()}>
                {busy ? "처리 중…" : "내보내기 시작"}
              </button>
            </span>
          ) : done && okCount > 0 ? (
            <BundleButton url={library.exportBundleUrl(batch.batch_id)} filename={exportZipName(batch)} label={ZIP_LABEL} primary small={false} title="manifest·README 와 ESL 별 폴더를 zip 하나로" />
          ) : (
            <span className="primary-wrap" title={done ? "성공한 항목이 없습니다" : "진행 중 — 창을 닫아도 계속됩니다"}>
              <button type="button" className="btn primary" data-primary="true" disabled>
                {ZIP_LABEL}
              </button>
            </span>
          )}
        </div>
        <RecentExports projectId={projectId} current={batch?.batch_id ?? null} />
      </div>
    </div>
  );
}
