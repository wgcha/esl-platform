import { useEffect, useState, type ReactNode } from "react";
import type { JobState, StrainSource } from "../api/types";
import { JOB_STATE_LABEL, strainSourceBadge } from "../lib/format";

/** 단계 주 버튼(단계당 1개). 비활성 사유는 툴팁(title)으로 보인다. */
export function PrimaryButton({ label, onClick, disabledReason, busy }: { label: string; onClick: () => void; disabledReason?: string | null; busy?: boolean }) {
  const disabled = !!disabledReason || !!busy;
  return (
    <span className="primary-wrap" title={disabledReason ?? undefined}>
      <button type="button" className="btn primary" data-primary="true" disabled={disabled} aria-disabled={disabled} onClick={onClick}>
        {busy ? "처리 중…" : label}
      </button>
      {disabledReason && <span className="sr-only">{disabledReason}</span>}
    </span>
  );
}

/** v0.23.1 카드 접기(esl_doe_ui_tidy.md §1): 접힘 = 본문 hidden(언마운트 안 함), 사용자 조작만 sessionStorage */
export interface CardFold {
  /** sessionStorage 키 뒷부분(esl.cardfold.<storeKey>) */
  storeKey: string;
  /** 사용자가 바꾸지 않았을 때의 기본 */
  defaultOpen: boolean;
  /** 항상 펼침(실행 중·실패 단계) — 접기 단추 없음 */
  locked?: boolean;
}
const FOLD_KEY = "esl.cardfold.";
function readFold(key: string): boolean | null {
  try {
    const v = window.sessionStorage.getItem(FOLD_KEY + key);
    return v === "1" ? true : v === "0" ? false : null;
  } catch {
    return null;
  }
}
function writeFold(key: string, open: boolean) {
  try {
    window.sessionStorage.setItem(FOLD_KEY + key, open ? "1" : "0");
  } catch {
    /* 저장소 없음 */
  }
}

function FoldCard({ title, children, right, fold }: { title?: string; children: ReactNode; right?: ReactNode; fold: CardFold }) {
  const [saved, setSaved] = useState<boolean | null>(() => readFold(fold.storeKey));
  useEffect(() => setSaved(readFold(fold.storeKey)), [fold.storeKey]);
  const open = fold.locked || (saved ?? fold.defaultOpen);
  const toggle = () => {
    writeFold(fold.storeKey, !open);
    setSaved(!open);
  };
  return (
    <section className={open ? "card" : "card folded"} aria-label={title}>
      <header className="card-head">
        <h3>
          {fold.locked ? (
            title
          ) : (
            <button type="button" className="card-fold-btn" aria-expanded={open} onClick={toggle} title={open ? "접기" : "펼치기"}>
              <span aria-hidden="true">{open ? "▾" : "▸"}</span>
              {title}
            </button>
          )}
        </h3>
        {right}
      </header>
      <div className="card-body" hidden={!open}>
        {children}
      </div>
    </section>
  );
}

/** 카드: 머리(제목·오른쪽 요소) + 본문. PhysicsAI Card 와 같은 구조(.card-head / .card-body). fold 가 없으면 기존과 같은 DOM */
export function Card({ title, children, right, fold }: { title?: string; children: ReactNode; right?: ReactNode; fold?: CardFold | null }) {
  if (fold) return <FoldCard title={title} right={right} fold={fold}>{children}</FoldCard>;
  return (
    <section className="card" aria-label={title}>
      {(title || right) && (
        <header className="card-head">
          <h3>{title}</h3>
          {right}
        </header>
      )}
      <div className="card-body">{children}</div>
    </section>
  );
}

export function Field({ label, children, hint, className }: { label: string; children: ReactNode; hint?: ReactNode; className?: string }) {
  return (
    <label className={className ? `field ${className}` : "field"}>
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export function Stat({ label, value, hint, sub, tone }: { label: string; value: ReactNode; hint?: string; sub?: ReactNode; tone?: "bad" | "ok" }) {
  return (
    <div className={tone ? `stat ${tone}` : "stat"} title={hint}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub !== undefined && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

export function Badge({ kind, children }: { kind: "ok" | "bad" | "warn" | "info"; children: ReactNode }) {
  return <span className={`badge ${kind}`}>{children}</span>;
}

/** v0.12.1 변형률 대체 배지(esl_strain_fallback.md §7) — max_strain·없음이면 표시 없음 */
export function StrainSourceBadge({ source, title }: { source: StrainSource | null | undefined; title?: string }) {
  const b = strainSourceBadge(source);
  if (!b) return null;
  return (
    <span className={`badge ${b.kind}`} data-testid="strain-source-badge" title={title}>
      {b.text}
    </span>
  );
}

/** 작업 상태 점(PhysicsAI StateDot 과 같은 색 규칙) */
export function StateDot({ state }: { state: JobState | null | undefined }) {
  if (!state) return null;
  const cls = state === "SUCCEEDED" ? "ok" : state === "FAILED" || state === "INTERRUPTED" ? "bad" : state === "QUEUED" ? "wait" : state === "CANCELED" ? "off" : "run";
  return <span className={`dot ${cls}`} title={JOB_STATE_LABEL[state]} />;
}

export function JobStatusBadge({ state }: { state: JobState }) {
  return (
    <span className={`state state-${state.toLowerCase()}`}>
      <StateDot state={state} />
      {JOB_STATE_LABEL[state]}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

/** onClose 가 있으면 [닫기] — v0.15.1: 동작 오류는 사용자가 닫거나 같은 동작을 다시 할 때만 지운다(폴링·재렌더로 지우지 않음) */
export function ErrorLine({ text, onClose }: { text: string | null | undefined; onClose?: () => void }) {
  if (!text) return null;
  return (
    <div className="error-text" role="alert">
      {text}
      {onClose && (
        <button type="button" className="btn small ghost icon err-close" aria-label="오류 닫기" title="닫기" onClick={onClose}>
          ✕
        </button>
      )}
    </div>
  );
}
