// 압축 모드(계약 esl_upload_speed.md §4.6·§6): 이 브라우저의 안내 기본값(localStorage esl.slim.v1, 기본 ON)과 업로드 메타 표기.
// 웹 체크 상태는 PC 도구에 전달되지 않는다(US-3) — 도구는 실행할 때 묻는다.
import type { H3dMeta } from "../api/types";
import { bytes } from "./format";

export const SLIM_KEY = "esl.slim.v1";

export function readSlim(): boolean {
  try {
    return localStorage.getItem(SLIM_KEY) !== "0";
  } catch {
    return true;
  }
}
export function writeSlim(on: boolean) {
  try {
    localStorage.setItem(SLIM_KEY, on ? "1" : "0");
  } catch {
    /* 저장소 없음 */
  }
}

export function secText(s: number): string {
  const t = Math.max(0, Math.round(s));
  if (t < 60) return `${t}초`;
  const m = Math.floor(t / 60);
  if (m < 60) return t % 60 ? `${m}분 ${t % 60}초` : `${m}분`;
  return `${Math.floor(m / 60)}시간 ${m % 60}분`;
}

const RESULT_LABEL: Record<string, string> = { Displacement: "변위", Max_Strain: "최대 변형률", "Plastic Strain": "소성 변형률" };

/** "48.2 GB → 2.9 GB · hvtrans 6분 12초 · 파트 1234 chassis_rear" (알 수 있는 항목만) */
export function slimLine(m: H3dMeta): string {
  const parts: string[] = [];
  if (m.source_bytes && m.slim_bytes) parts.push(`${bytes(m.source_bytes)} → ${bytes(m.slim_bytes)}`);
  else if (m.slim_bytes) parts.push(bytes(m.slim_bytes));
  if (m.hvtrans_sec != null) parts.push(`hvtrans ${secText(m.hvtrans_sec)}`);
  if (m.part_id != null) parts.push(`파트 ${m.part_id}${m.part_title ? ` ${m.part_title}` : ""}`);
  return parts.join(" · ");
}

export function slimResults(m: H3dMeta): string {
  return (m.results ?? []).map((r) => `${RESULT_LABEL[r.type] ?? r.type}${r.layer ? `(${r.layer})` : ""}`).join(", ");
}

/** 툴팁 문구: 원본 이름·크기 → 슬림 크기, hvtrans 시간, 남긴 결과 */
export function slimTip(m: H3dMeta): string {
  const lines = [slimLine(m)];
  if (m.source_name) lines.unshift(`원본 ${m.source_name}`);
  const r = slimResults(m);
  if (r) lines.push(`남긴 결과: ${r} · 전 프레임`);
  return lines.join("\n");
}
