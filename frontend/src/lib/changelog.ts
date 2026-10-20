// CHANGELOG.md(계약 §3 형식: "## [0.4.0] - 2026-10-20" + "### 추가|변경|수정" + "- 항목") 파서·버전 비교.
import type { ChangelogEntry, ChangelogSection } from "../api/types";

export const SECTIONS: ChangelogSection[] = ["추가", "변경", "수정"];

export function parseChangelog(md: string): ChangelogEntry[] {
  const out: ChangelogEntry[] = [];
  let cur: ChangelogEntry | null = null;
  let sec: ChangelogSection | null = null;
  for (const raw of md.split(/\r?\n/)) {
    const line = raw.trimEnd();
    const h = line.match(/^##\s+\[([^\]]+)\](?:\s*-\s*(\S+))?/);
    if (h) {
      cur = { version: h[1], date: h[2] ?? null, sections: {} };
      out.push(cur);
      sec = null;
      continue;
    }
    const s = line.match(/^###\s+(\S+)/);
    if (s && cur) {
      sec = (SECTIONS as string[]).includes(s[1]) ? (s[1] as ChangelogSection) : null;
      continue;
    }
    const item = line.match(/^\s*[-*]\s+(.+)/);
    if (item && cur && sec) (cur.sections[sec] ??= []).push(item[1]);
  }
  return out;
}

/** SemVer 비교(a>b → 양수). 숫자 아닌 조각은 0 */
export function cmpVersion(a: string, b: string): number {
  const pa = a.replace(/^v/, "").split(/[.-]/).map((x) => Number.parseInt(x, 10) || 0);
  const pb = b.replace(/^v/, "").split(/[.-]/).map((x) => Number.parseInt(x, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length, 3); i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d) return d;
  }
  return 0;
}

const SEEN_KEY = "esl.lastSeenVersion";

export function lastSeenVersion(): string | null {
  try {
    return localStorage.getItem(SEEN_KEY);
  } catch {
    return null;
  }
}
export const SEEN_EVENT = "esl:version-seen";
export function markVersionSeen(v: string) {
  try {
    localStorage.setItem(SEEN_KEY, v);
  } catch {
    /* 저장소 없음 */
  }
  window.dispatchEvent(new Event(SEEN_EVENT));
}
/** 새 버전 배지: 본 적 없거나 마지막으로 본 버전보다 높을 때 */
export function isNewVersion(current: string, seen: string | null): boolean {
  return !seen || cmpVersion(current, seen) > 0;
}
