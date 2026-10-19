import type { ReactNode } from "react";

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

export function Card({ title, children, right }: { title?: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="card">
      {(title || right) && (
        <div className="card-head">
          {title && <h3>{title}</h3>}
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="stat" title={hint}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  );
}

export function Badge({ kind, children }: { kind: "ok" | "bad" | "warn" | "info"; children: ReactNode }) {
  return <span className={`badge ${kind}`}>{children}</span>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function ErrorLine({ text }: { text: string | null | undefined }) {
  if (!text) return null;
  return (
    <div className="banner bad" role="alert">
      {text}
    </div>
  );
}
