// v0.24.1 하중 출처 탭(esl_view3d_sources.md §6.1) — 스터디 하중 정의 탭(구 LoadTabSeg)을 범용으로 옮긴 것.
// 같은 DOM·tablist/tab/aria·화살표 키 규칙: 비활성 탭도 포커스를 받아 사유를 읽을 수 있고(.seg 밖 절대 위치 줄 — 높이 불변), Enter·Space = 선택.
import { Fragment, useRef, useState, type KeyboardEvent } from "react";
import type { SourceTabItem } from "./sources";

export interface SourceTabsProps {
  items: readonly SourceTabItem[];
  tab: string;
  setTab: (key: string) => void;
  /** tablist aria-label */
  label: string;
  /** DOM id·testid 접두: `<prefix>-tab-<key>`(탭 id) · `<prefix>-why-<key>`(사유) · `<prefix>-panel`(aria-controls) */
  prefix: string;
  /** tablist testid(스터디 = doe-load-tab, Case = v3d-src-tab) */
  testId: string;
  /** 포커스 사유 줄 testid */
  whyTestId: string;
}

// 표식이 있는 탭만(없으면 DOM 이 v0.24.2 와 같음): 머리 줄이 넘치면 라벨 말줄임(전체 = title)
const MARK_BTN = { maxWidth: "15rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } as const;
const MARK_COLOR: Record<NonNullable<SourceTabItem["mark"]>["tone"], string> = { ok: "var(--ok)", bad: "var(--bad)", warn: "var(--wait)", muted: "var(--muted)" };

export function SourceTabs({ items, tab, setTab, label, prefix, testId, whyTestId }: SourceTabsProps) {
  const [focus, setFocus] = useState<string | null>(null);
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const cur = items.find((i) => i.key === tab);
  /** 좌우 화살표(·Home·End) = 포커스만 이동(가능 여부와 무관), Enter·Space = 선택 */
  const onKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const n = items.length;
    const j = e.key === "ArrowRight" ? (i + 1) % n : e.key === "ArrowLeft" ? (i - 1 + n) % n : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : -1;
    if (j < 0) return;
    e.preventDefault();
    refs.current[items[j].key]?.focus();
  };
  const fi = focus ? items.find((i) => i.key === focus) : null;
  const focusReason = fi && !fi.ok ? fi.why : null;
  return (
    <span className={`${prefix}-tabwrap`} style={{ position: "relative", display: "inline-flex", verticalAlign: "middle" }}>
      <div className="seg" role="tablist" aria-label={label} data-testid={testId}>
        {items.map((s, i) => {
          const sel = tab === s.key;
          const usable = s.ok || !!s.add;
          return (
            <Fragment key={s.key}>
              <button
                ref={(el) => {
                  refs.current[s.key] = el;
                }}
                id={`${prefix}-tab-${s.key}`}
                type="button"
                role="tab"
                data-tab={s.key}
                data-add={s.add ? "1" : undefined}
                className={sel ? "on" : ""}
                aria-selected={sel}
                aria-controls={`${prefix}-panel`}
                aria-disabled={!usable}
                aria-describedby={!s.ok && s.why ? `${prefix}-why-${s.key}` : undefined}
                tabIndex={sel || (!cur?.ok && !cur?.add && i === 0) ? 0 : -1}
                style={s.add && !sel ? (s.mark ? { ...MARK_BTN, opacity: 0.6 } : { opacity: 0.6 }) : s.mark ? MARK_BTN : undefined}
                title={s.ok ? s.title : s.why ?? undefined}
                onFocus={() => setFocus(s.key)}
                onBlur={() => setFocus((f) => (f === s.key ? null : f))}
                onKeyDown={(e) => onKey(e, i)}
                onClick={() => usable && setTab(s.key)}
              >
                {s.label}
                {s.mark && (
                  <span className="small" data-testid={`${prefix}-mark-${s.key}`} data-tone={s.mark.tone} style={{ marginLeft: "0.35rem", color: MARK_COLOR[s.mark.tone], fontWeight: 650 }}>
                    {s.mark.text}
                  </span>
                )}
                {s.add ? " +" : ""}
              </button>
              {!s.ok && s.why && (
                <span id={`${prefix}-why-${s.key}`} className="sr-only">
                  {s.why}
                </span>
              )}
            </Fragment>
          );
        })}
      </div>
      {focusReason && (
        <span className="small warn-text" data-testid={whyTestId} role="status" style={{ position: "absolute", top: "100%", right: 0, zIndex: 5, whiteSpace: "nowrap", background: "var(--surface)", border: "1px solid var(--line-strong)", borderRadius: 4, padding: "0 0.4rem" }}>
          {focusReason}
        </span>
      )}
    </span>
  );
}
