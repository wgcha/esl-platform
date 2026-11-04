// v0.15.1 고정 침범 원인 표시(select): 코어 미리보기 셀 fixed_viol{n, max_mm, bead_vars, node_idx} → 변수별 요약 문구.
// 셀 상태와 무관하게 fixed_viol 만 본다 — 지금은 침범 = 스킵(SKIPPED_FIXED)이지만 다음 버전 '경고만'(READY + fixed_viol)에서도 그대로 쓴다.
import type { DoeFixedViol } from "../api/types";

export interface FixedViolRow {
  /** 변수 이름(B1_W) */
  name: string;
  /** 침범을 낸 안 수 */
  designs: number;
  /** 그 변수로 움직인 고정 노드 수(안들 중 최대) */
  nodes: number;
  /** 최대 이동(mm) */
  maxMm: number;
}

/** 안들의 fixed_viol → 변수별(최대 이동 큰 순) */
export function fixedViolRows(cells: { fixed_viol?: DoeFixedViol | null }[]): FixedViolRow[] {
  const by = new Map<string, FixedViolRow>();
  for (const c of cells) {
    for (const v of c.fixed_viol?.bead_vars ?? []) {
      const r = by.get(v.name) ?? { name: v.name, designs: 0, nodes: 0, maxMm: 0 };
      r.designs += 1;
      r.nodes = Math.max(r.nodes, v.n);
      r.maxMm = Math.max(r.maxMm, v.max_mm);
      by.set(v.name, r);
    }
  }
  return [...by.values()].sort((a, b) => b.maxMm - a.maxMm || a.name.localeCompare(b.name));
}

const label = (name: string) => name.replace("_", " ");
const mm = (v: number) => (v < 10 ? v.toFixed(2).replace(/0$/, "") : v.toFixed(1));

/** 한 줄: "B1 W 를 바꾸면 고정 노드 37개가 최대 0.8 mm 움직임 → B1 W 해제 또는 블렌딩 반경 축소"(폭) / "… → B1 D1 범위 축소 또는 해제"(깊이) */
export function fixedViolText(r: FixedViolRow): string {
  const fix = /_W$/.test(r.name) ? `${label(r.name)} 해제 또는 블렌딩 반경 축소` : `${label(r.name)} 범위 축소 또는 해제(또는 고정 노드가 비드 안이면 선택 수정)`;
  return `${label(r.name)} 를 바꾸면 고정 노드 ${r.nodes.toLocaleString()}개가 최대 ${mm(r.maxMm)} mm 움직임 → ${fix}`;
}

/** 원인 목록(없으면 null). title = 앞 문구(예: "고정 침범 원인") */
export function FixedViolNote({ cells, title, testId = "fixed-viol" }: { cells: { fixed_viol?: DoeFixedViol | null }[]; title?: string; testId?: string }) {
  const rows = fixedViolRows(cells);
  if (!rows.length) return null;
  return (
    <div className="small fixed-viol" data-testid={testId}>
      {title && <b>{title}</b>}
      <ul className="reasons">
        {rows.map((r) => (
          <li key={r.name} data-testid={`${testId}-${r.name}`}>
            {fixedViolText(r)}
            {r.designs > 1 ? <span className="muted"> (안 {r.designs}개)</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
