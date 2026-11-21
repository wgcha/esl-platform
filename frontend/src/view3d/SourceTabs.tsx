// v0.24.1 하중 출처 탭(esl_view3d_sources.md §6.1) — 스터디 하중 정의 탭(구 LoadTabSeg)을 범용으로 옮긴 것.
// v0.24.4(esl_jig_case.md §6.2): 항목의 group 속성이 있으면 ≥ 2201px 은 그룹 머리 글자 + 하위 탭 한 줄 펼침, 이하는 "그룹 · 선택 ▾" 한 탭 + 팝오버(절대 위치 — 높이 불변).
// group 이 없으면 DOM 이 v0.24.3 과 같다. 분기는 미디어 질의(열 group 만 읽음 — 출처 이름 비교 없음).
// 같은 DOM·tablist/tab/aria·화살표 키 규칙: 비활성 탭도 포커스를 받아 사유를 읽을 수 있고(.seg 밖 절대 위치 줄 — 높이 불변), Enter·Space = 선택.
import { Fragment, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { GROUPS, type SourceTabItem } from "./sources";

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

/** 펼침 경계(styles.css 의 @media (max-width: 2200px) 와 같은 값 — D-0.23.1-UI-6) */
export const WIDE_QUERY = "(min-width: 2201px)";

/** 화면이 펼침 폭인가(matchMedia 없는 환경 = 펼침) */
function useWide(): boolean {
  const mq = () => (typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(WIDE_QUERY) : null);
  const [wide, setWide] = useState<boolean>(() => mq()?.matches ?? true);
  useEffect(() => {
    const m = mq();
    if (!m) return;
    const on = () => setWide(m.matches);
    on();
    if (m.addEventListener) m.addEventListener("change", on);
    else m.addListener?.(on);
    return () => {
      if (m.removeEventListener) m.removeEventListener("change", on);
      else m.removeListener?.(on);
    };
  }, []);
  return wide;
}

/** 키보드 이동 대상(최상위): 탭 하나 또는 접힌 그룹 */
type Entry = { ref: string; item?: SourceTabItem; group?: string; members?: SourceTabItem[] };

function Mark({ s, testid }: { s: SourceTabItem; testid: string }) {
  if (s.mark)
    return (
      <span className="small" data-testid={testid} data-tone={s.mark.tone} style={{ marginLeft: "0.35rem", color: MARK_COLOR[s.mark.tone], fontWeight: 650 }}>
        {s.mark.text}
      </span>
    );
  if (s.caution)
    return (
      <span className="small" data-testid={`${testid}-caution`} role="img" aria-label={`주의: ${s.caution}`} title={s.caution} style={{ marginLeft: "0.25rem", color: "var(--wait)", fontWeight: 650 }}>
        ⚠
      </span>
    );
  return null;
}

export function SourceTabs({ items, tab, setTab, label, prefix, testId, whyTestId }: SourceTabsProps) {
  const [focus, setFocus] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const refs = useRef<Record<string, HTMLElement | null>>({});
  const wide = useWide();
  const wrapRef = useRef<HTMLSpanElement | null>(null);
  const cur = items.find((i) => i.key === tab);
  const fold = !wide && items.some((i) => i.group);
  const entries: Entry[] = [];
  for (const it of items) {
    if (fold && it.group) {
      if (!entries.some((e) => e.group === it.group)) entries.push({ ref: `group:${it.group}`, group: it.group, members: items.filter((x) => x.group === it.group) });
    } else entries.push({ ref: it.key, item: it });
  }
  /** 좌우 화살표(·Home·End) = 포커스만 이동(가능 여부와 무관), Enter·Space = 선택 */
  const onKey = (e: KeyboardEvent<HTMLElement>, i: number) => {
    const n = entries.length;
    const j = e.key === "ArrowRight" ? (i + 1) % n : e.key === "ArrowLeft" ? (i - 1 + n) % n : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : -1;
    if (j < 0) return;
    e.preventDefault();
    refs.current[entries[j].ref]?.focus();
  };
  const fi = focus ? items.find((i) => i.key === focus) : null;
  const focusReason = fi && !fi.ok ? fi.why : null;

  // 팝오버: 바깥 클릭·포커스 이탈 = 닫기
  useEffect(() => {
    if (!open) return;
    const down = (ev: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(ev.target as Node)) setOpen(null);
    };
    document.addEventListener("mousedown", down);
    return () => document.removeEventListener("mousedown", down);
  }, [open]);
  useEffect(() => {
    if (!fold && open) setOpen(null);
  }, [fold, open]);

  const openGroup = (g: string, members: SourceTabItem[]) => {
    setOpen(g);
    const start = members.find((m) => m.key === tab) ?? members.find((m) => m.ok || m.add) ?? members[0];
    // 팝오버가 그려진 뒤 선택 항목에 포커스
    setTimeout(() => refs.current[`opt:${start.key}`]?.focus(), 0);
  };
  const closeGroup = (g: string) => {
    setOpen(null);
    refs.current[`group:${g}`]?.focus();
  };
  const onOptKey = (e: KeyboardEvent<HTMLElement>, g: string, members: SourceTabItem[], i: number) => {
    const n = members.length;
    const j = e.key === "ArrowDown" ? (i + 1) % n : e.key === "ArrowUp" ? (i - 1 + n) % n : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : -1;
    if (j >= 0) {
      e.preventDefault();
      refs.current[`opt:${members[j].key}`]?.focus();
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      closeGroup(g);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      const m = members[i];
      if (m.ok || m.add) {
        setTab(m.key);
        closeGroup(g);
      }
    } else if (e.key === "Tab") setOpen(null);
  };

  const popGroup = open ? entries.find((e) => e.group === open) : null;
  return (
    <span ref={wrapRef} className={`${prefix}-tabwrap`} style={{ position: "relative", display: "inline-flex", verticalAlign: "middle" }}>
      <div className="seg" role="tablist" aria-label={label} data-testid={testId}>
        {entries.map((en, i) => {
          if (en.group && en.members) {
            const g = en.group;
            const gl = GROUPS[g]?.label ?? g;
            const sub = en.members.find((m) => m.key === tab) ?? null;
            const isOpen = open === g;
            const fallbackFocus = !cur?.ok && !cur?.add && i === 0;
            return (
              <button
                key={en.ref}
                ref={(el) => {
                  refs.current[en.ref] = el;
                }}
                id={`${prefix}-tab-group-${g}`}
                type="button"
                role="tab"
                data-group={g}
                data-tab={sub?.key}
                className={sub ? "on" : ""}
                aria-selected={!!sub}
                aria-haspopup="listbox"
                aria-expanded={isOpen}
                aria-controls={isOpen ? `${prefix}-pop-${g}` : `${prefix}-panel`}
                aria-label={sub ? `${gl} · ${sub.label}` : gl}
                tabIndex={sub || fallbackFocus ? 0 : -1}
                style={sub?.mark ? MARK_BTN : undefined}
                title={sub?.ok ? sub.title : gl}
                onKeyDown={(e) => {
                  if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    isOpen ? setOpen(null) : openGroup(g, en.members!);
                  } else if (e.key === "Escape" && isOpen) {
                    e.preventDefault();
                    setOpen(null);
                  } else onKey(e, i);
                }}
                onClick={() => (isOpen ? setOpen(null) : openGroup(g, en.members!))}
              >
                {gl}
                {sub ? ` · ${sub.short ?? sub.label}` : ""}
                {sub && <Mark s={sub} testid={`${prefix}-mark-${sub.key}`} />}
                {" ▾"}
              </button>
            );
          }
          const s = en.item!;
          const sel = tab === s.key;
          const usable = s.ok || !!s.add;
          const groupHead = !fold && s.group && items.findIndex((x) => x.group === s.group) === items.indexOf(s);
          return (
            <Fragment key={s.key}>
              {groupHead && (
                <span className="seg-group" aria-hidden="true" data-group={s.group}>
                  {GROUPS[s.group!]?.label ?? s.group}
                </span>
              )}
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
                aria-label={s.group && s.short ? `${GROUPS[s.group]?.label ?? s.group} ${s.label}` : undefined}
                aria-describedby={!s.ok && s.why ? `${prefix}-why-${s.key}` : undefined}
                tabIndex={sel || (!cur?.ok && !cur?.add && i === 0) ? 0 : -1}
                style={s.add && !sel ? (s.mark ? { ...MARK_BTN, opacity: 0.6 } : { opacity: 0.6 }) : s.mark ? MARK_BTN : undefined}
                title={s.ok ? s.title : s.why ?? undefined}
                onFocus={() => setFocus(s.key)}
                onBlur={() => setFocus((f) => (f === s.key ? null : f))}
                onKeyDown={(e) => onKey(e, i)}
                onClick={() => usable && setTab(s.key)}
              >
                {s.group && s.short ? s.short : s.label}
                <Mark s={s} testid={`${prefix}-mark-${s.key}`} />
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
      {popGroup && popGroup.members && (
        <ul
          id={`${prefix}-pop-${popGroup.group}`}
          className="src-pop"
          role="listbox"
          aria-label={`${GROUPS[popGroup.group!]?.label ?? popGroup.group} 출처`}
          data-testid={`${prefix}-pop-${popGroup.group}`}
          onBlur={(e) => {
            if (!wrapRef.current?.contains(e.relatedTarget as Node | null)) setOpen(null);
          }}
        >
          {popGroup.members.map((m, i) => {
            const usable = m.ok || !!m.add;
            return (
              <li
                key={m.key}
                ref={(el) => {
                  refs.current[`opt:${m.key}`] = el;
                }}
                id={`${prefix}-opt-${m.key}`}
                role="option"
                data-tab={m.key}
                data-add={m.add ? "1" : undefined}
                aria-selected={tab === m.key}
                aria-disabled={!usable}
                tabIndex={-1}
                className={`src-opt${tab === m.key ? " on" : ""}`}
                title={m.ok ? m.title : m.why ?? undefined}
                onKeyDown={(e) => onOptKey(e, popGroup.group!, popGroup.members!, i)}
                onClick={() => {
                  if (!usable) return;
                  setTab(m.key);
                  closeGroup(popGroup.group!);
                }}
              >
                <span className="src-opt-name" aria-label={m.label}>
                  {m.short ?? m.label}
                  {m.add ? " +" : ""}
                </span>
                <Mark s={m} testid={`${prefix}-opt-mark-${m.key}`} />
                {!m.ok && m.why && (
                  <span className="small warn-text src-opt-why" data-testid={`${prefix}-opt-why-${m.key}`}>
                    {m.why}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {focusReason && (
        <span className="small warn-text" data-testid={whyTestId} role="status" style={{ position: "absolute", top: "100%", right: 0, zIndex: 5, whiteSpace: "nowrap", background: "var(--surface)", border: "1px solid var(--line-strong)", borderRadius: 4, padding: "0 0.4rem" }}>
          {focusReason}
        </span>
      )}
    </span>
  );
}
