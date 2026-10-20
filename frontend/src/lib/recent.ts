// 사용 가이드 바로가기용: 마지막으로 연 프로젝트·Case(이 브라우저에만 저장)
const KEY = "esl.recentCase";
export interface RecentCase {
  projectId: string;
  caseId: string;
  title: string;
}
export function rememberCase(r: RecentCase) {
  try {
    localStorage.setItem(KEY, JSON.stringify(r));
  } catch {
    /* 저장소 없음 */
  }
}
export function recentCase(): RecentCase | null {
  try {
    const v = localStorage.getItem(KEY);
    return v ? (JSON.parse(v) as RecentCase) : null;
  } catch {
    return null;
  }
}
