import type { ReactNode } from "react";
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

/** 카드: 머리(제목·오른쪽 요소) + 본문. PhysicsAI Card 와 같은 구조(.card-head / .card-body). */
export function Card({ title, children, right }: { title?: string; children: ReactNode; right?: ReactNode }) {
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

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="field">
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

export function ErrorLine({ text }: { text: string | null | undefined }) {
  if (!text) return null;
  return (
    <div className="error-text" role="alert">
      {text}
    </div>
  );
}
