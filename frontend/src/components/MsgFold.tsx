// v0.17.1 경고·정보·로그 접기: 긴 주황 목록(v0.16.3 "[단계별: …]" 사다리 문구, MESH_FREEFORM·MESH_TRIA_FALLBACK, AUTO_*·BG_*) 대신
// 요약 1줄 "⚠ 경고 N건 · 정보 M건 · <가장 중요한 항목 머리말> — 자세히". 누르면 전체 목록(항목마다 접기, 긴 글은 높이 고정 스크롤 상자).
// 펼침 상태는 스터디마다 sessionStorage(try/catch — 저장소가 없어도 접힌 채로 동작).
// 막는 오류(FAILED)는 BlockErr: 빨간 1줄(짧은 제목 + 자세히), 내용은 접힘.
import { useState, type ReactNode } from "react";

export interface FoldItem {
  /** 전체 문구(이미 warnText 등으로 번역된 것) */
  text: string;
  /** 정보 수준(ⓘ — 경고 개수에 넣지 않음) */
  info?: boolean;
}

const KEY = "esl.msgfold.";

function readOpen(key: string | null | undefined): boolean {
  if (!key) return false;
  try {
    return window.sessionStorage.getItem(KEY + key) === "1";
  } catch {
    return false;
  }
}
function writeOpen(key: string | null | undefined, open: boolean) {
  if (!key) return;
  try {
    if (open) window.sessionStorage.setItem(KEY + key, "1");
    else window.sessionStorage.removeItem(KEY + key);
  } catch {
    /* 저장소 없음 */
  }
}

/** 머리말 1줄: 앞의 "[단계별: …]" 같은 대괄호 묶음을 빼고 첫 줄만 */
export function msgHead(text: string): string {
  let t = text.trim();
  for (let i = 0; i < 3 && t.startsWith("["); i += 1) {
    const end = t.indexOf("]");
    if (end < 0) break;
    const rest = t.slice(end + 1).trim();
    if (!rest) break;
    t = rest;
  }
  return t.split("\n")[0].trim();
}

/** 개수: 경고(정보 아닌 것) · 정보 */
export function foldCounts(items: FoldItem[]): { warn: number; info: number } {
  const info = items.filter((x) => x.info).length;
  return { warn: items.length - info, info };
}

/** 요약 문구 "⚠ 경고 N건 · 정보 M건"(경고 0건이면 ⓘ) */
export function foldSummary(items: FoldItem[]): string {
  const c = foldCounts(items);
  return `${c.warn ? "⚠" : "ⓘ"} 경고 ${c.warn}건 · 정보 ${c.info}건`;
}

/** 긴 항목 기준(머리말과 다르거나 길면 접기 단추) */
const isLong = (t: string) => msgHead(t) !== t.trim() || t.length > 90;

function FoldEntry({ item }: { item: FoldItem }) {
  const [open, setOpen] = useState(false);
  const head = msgHead(item.text);
  const mark = item.info ? "ⓘ" : "⚠";
  if (!isLong(item.text)) {
    return (
      <li className={`msg-fold-item${item.info ? " info" : ""}`}>
        <span className="msg-fold-wrap">
          {mark} {item.text}
        </span>
      </li>
    );
  }
  return (
    <li className={`msg-fold-item${item.info ? " info" : ""}`}>
      <button type="button" className="msg-fold-entry" aria-expanded={open} onClick={() => setOpen((x) => !x)} title={open ? "접기" : "펼치기"}>
        <span aria-hidden>{open ? "▾" : "▸"}</span>
        <span className="msg-fold-head">
          {mark} {head}
        </span>
      </button>
      {open && <div className="msg-fold-body">{item.text}</div>}
    </li>
  );
}

/** 경고·정보 요약 1줄(기본 접힘). items 가 비면 아무것도 그리지 않음 */
export function MsgFold({ items, storeKey, testId }: { items: FoldItem[]; storeKey?: string | null; testId?: string }) {
  const [open, setOpen] = useState(() => readOpen(storeKey));
  if (!items.length) return null;
  const sorted = [...items.filter((x) => !x.info), ...items.filter((x) => x.info)];
  const c = foldCounts(items);
  const head = msgHead(sorted[0].text);
  const toggle = () => {
    setOpen((x) => {
      writeOpen(storeKey, !x);
      return !x;
    });
  };
  return (
    <div className={`msg-fold${c.warn ? " warn" : " info"}`} data-testid={testId}>
      <button type="button" className="msg-fold-line" aria-expanded={open} onClick={toggle} title={open ? "접기" : head}>
        <span className="msg-fold-count" data-testid={testId ? `${testId}-count` : undefined}>
          {foldSummary(items)}
        </span>
        <span className="msg-fold-head sep">{head}</span>
        <span className="msg-fold-more">{open ? "접기" : "자세히"}</span>
      </button>
      {open && (
        <ul className="msg-fold-list" aria-label="경고·정보 목록">
          {sorted.map((x, i) => (
            <FoldEntry key={i} item={x} />
          ))}
        </ul>
      )}
    </div>
  );
}

/** 막는 오류(FAILED): 빨간 1줄 = 짧은 제목 + [자세히], 내용은 접힘 */
export function BlockErr({ title, detail, children, testId, right }: { title: string; detail?: string | null; children?: ReactNode; testId?: string; right?: ReactNode }) {
  const [open, setOpen] = useState(false);
  const has = !!detail || !!children;
  return (
    <div className="block-err" role="alert" data-testid={testId}>
      <div className="block-err-line">
        <span className="block-err-title" title={title}>
          ✗ {title}
        </span>
        {right}
        {has && (
          <button type="button" className="msg-fold-more link-btn" aria-expanded={open} onClick={() => setOpen((x) => !x)}>
            {open ? "접기" : "자세히"}
          </button>
        )}
      </div>
      {open && has && (
        <div className="block-err-body">
          {detail && <div className="msg-fold-body">{detail}</div>}
          {children}
        </div>
      )}
    </div>
  );
}
