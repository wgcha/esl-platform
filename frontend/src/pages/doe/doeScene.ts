// v0.25.1 F1b 낙하 씬 선택·자료 고르기 — 순수 함수(계약 esl_view3d_scene_legend.md §4.1~§4.4, D-0.25.1-VL-7).
// 씬 상태는 결과 화면 한 곳의 entry_id | null(null = 자동 = 선택 안의 최악 ESL). 선택 지점 3곳(3D 바·ESL 표·순위표)이 같은 상태를 바꾼다.
// 문구는 SCENE_TEXT 한 곳, 자료 유무·건너뜀 사유는 응답(results.scene_view)만 읽는다 — 출처 이름 분기 없음.
import type { DoeResultOut, DoeSceneSkippedOut } from "../../api/types";
import { sceneExtras } from "../../view3d/sceneManifest";

/** 화면 문구 표(한 곳) */
export const SCENE_TEXT = {
  selectLabel: "3D 낙하 씬",
  autoLabel: (label: string | null) => `자동 — 최악 ESL${label ? `(${label})` : ""}`,
  noDataTail: " · 자료 없음",
  /** 3D 칸 자리 안내 */
  missing: (label: string) => `ESL ${label} 의 3D 자료가 없습니다`,
  failedTail: (text: string) => text,
  createLabel: "씬 3D 만들기",
  creating: "만드는 중…",
  createHint: "관리자 또는 스터디 작성자가 만들 수 있습니다",
  /** 한도로 빠진 씬은 다시 만들어도 빠질 수 있음 */
  budgetHint: "저장 한도는 그대로라 다시 만들어도 빠질 수 있습니다",
  /** 옛 결과(scene_view null) 안내 한 줄 */
  oldNote: "이 결과에는 낙하 씬별 3D 가 없습니다 — 씬 3D 를 만들면 씬을 골라 볼 수 있습니다",
  oldNoteNoAdd: "이 결과에는 낙하 씬별 3D 가 없습니다",
  cTitle: "C = Σ F·u — 하중이 한 일. 하중이 큰 곳의 변위가 줄면 C 가 좋아집니다. umax 는 한 점의 최대 변위라 하중이 작은 곳에서 늘 수 있습니다 — 핀이 그 위치입니다.",
  dcTitle: "차이 = 안 − 기준(같은 씬). 파랑 = C 가 줄어든 곳(개선), 빨강 = 늘어난 곳",
  refCNote: " — 기준 C 기여도(참고)",
  pickedNote: "(선택한 씬)",
} as const;

export type ColorSel = "disp" | "load" | "c" | "dc";
export const COLOR_SEL_BUTTONS: readonly { key: ColorSel; label: string }[] = [
  { key: "disp", label: "응답 변위" },
  { key: "load", label: "하중" },
  { key: "c", label: "C 기여도" },
  { key: "dc", label: "차이" },
];

export interface SceneChoice {
  entry_id: string;
  label: string;
  /** 이 탭 출처 묶음에 이 안 자료가 없음(고를 수는 있음 — §4.4) */
  missing: boolean;
}

export const labelOfEntry = (result: DoeResultOut, eid: string | null | undefined): string | null => (eid ? result.esl?.find((x) => x.entry_id === eid)?.label ?? eid.slice(0, 8) : null);

/** 사이드카 요약이 있고 이 출처 묶음이 있으면 그 묶음, 아니면 null(옛 결과·묶음 없음 = 기존 폴더) */
export function packOf(result: DoeResultOut, srcKey: string | null | undefined) {
  if (!srcKey) return null;
  return result.scene_view?.packs?.[srcKey] ?? null;
}

/** 씬 묶음에서 이 안·기준 둘 다 이 엔트리의 자료가 있는가 */
export function hasScenePair(result: DoeResultOut, srcKey: string | null | undefined, did: string | null, eid: string | null): boolean {
  const p = packOf(result, srcKey);
  if (!p || !did || !eid) return false;
  return (p.designs[did] ?? []).includes(eid) && (p.designs["d000"] ?? []).includes(eid);
}

/** 자료 없는 이유(건너뜀 기록) — 안·기준·출처 전체 어느 쪽이든 이 엔트리에 걸리는 것 중 첫째. 없으면 null */
export function skippedFor(result: DoeResultOut, srcKey: string | null | undefined, did: string | null, eid: string | null): DoeSceneSkippedOut | null {
  const p = packOf(result, srcKey);
  if (!p || !eid) return null;
  return (p.skipped ?? []).find((s) => (s.entry_id == null || s.entry_id === eid) && (s.did == null || s.did === did || s.did === "d000")) ?? null;
}

/** 3D 바 선택 칸 항목: 엔트리 순서대로(사이드카 entries → 없으면 결과 esl 열) */
export function sceneChoices(result: DoeResultOut, srcKey: string | null | undefined, did: string | null): SceneChoice[] {
  const ids = result.scene_view?.entries?.length ? result.scene_view.entries.map((e) => e.entry_id) : (result.esl ?? []).map((e) => e.entry_id);
  const withPack = !!packOf(result, srcKey);
  return ids.map((id) => ({ entry_id: id, label: labelOfEntry(result, id) ?? id, missing: withPack && !hasScenePair(result, srcKey, did, id) }));
}

/** 씬 요약 한 줄 값(씬 manifest c.value·pins.umax.value — 표 값과 같음). 어느 쪽이든 없으면 그 부분 생략 */
export interface SceneSummaryIn {
  label: string;
  base: unknown;
  cand: unknown;
}
const g4 = (x: number) => Number(x.toPrecision(4)).toString();
const rel = (a: number, b: number) => (a !== 0 && Number.isFinite(a) && Number.isFinite(b) ? `${b / a - 1 >= 0 ? "+" : "−"}${Math.abs((b / a - 1) * 100).toFixed(1)} %` : null);
export function sceneSummary(x: SceneSummaryIn): string {
  const b = sceneExtras(x.base);
  const d = sceneExtras(x.cand);
  const parts = [`ESL ${x.label}`];
  if (b.c && d.c) {
    const r = rel(b.c.value, d.c.value);
    parts.push(`C 기준 ${g4(b.c.value)} → 안 ${g4(d.c.value)}${r ? ` (${r})` : ""}`);
  }
  if (b.umaxPin && d.umaxPin) {
    const r = rel(b.umaxPin.value, d.umaxPin.value);
    parts.push(`umax 기준 ${b.umaxPin.value.toFixed(3)} → 안 ${d.umaxPin.value.toFixed(3)}${r ? ` (${r})` : ""} mm`);
  }
  return parts.join(" · ");
}

/** 색 모드 버튼 비활성 사유(활성이면 null). 값은 안 카드 manifest 기준(차이 = 안만, C 기여도 = 두 카드 모두) */
export function colorDisabled(sel: ColorSel, noC: string, noDc: string, base: unknown, cand: unknown): string | null {
  if (sel === "disp" || sel === "load") return null;
  const b = sceneExtras(base);
  const d = sceneExtras(cand);
  if (sel === "c") return b.c && d.c ? null : noC;
  return d.dc ? null : noDc;
}

/** ESL별 개선율 표 열 머리 클릭 = 그 씬(선택된 열을 다시 누르면 자동) */
export const toggleScene = (cur: string | null, eid: string): string | null => (cur === eid ? null : eid);
