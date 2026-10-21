import type { ReviewDiff } from "../api/history";

/** 값 한 칸 표기: 숫자는 자릿수 정리, 배열은 쉼표, 객체는 JSON, null 은 "–" */
export function diffValue(v: unknown): string {
  if (v === null || v === undefined) return "–";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "–";
    if (Number.isInteger(v)) return v.toLocaleString();
    return Math.abs(v) < 1e-3 || Math.abs(v) >= 1e6 ? v.toExponential(2) : String(Number(v.toPrecision(4)));
  }
  if (typeof v === "boolean") return v ? "예" : "아니오";
  if (Array.isArray(v)) return v.map(diffValue).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** "현재와 다른 점" 표(접힘 기본 펼침) */
export function DiffTable({ diff }: { diff: ReviewDiff[] }) {
  if (!diff.length) return null;
  return (
    <details className="card diff-card" open data-testid="diff-table">
      <summary>현재와 다른 점 ({diff.length})</summary>
      <table className="table compact">
        <thead>
          <tr>
            <th>항목</th>
            <th>그때</th>
            <th>지금</th>
          </tr>
        </thead>
        <tbody>
          {diff.map((d) => (
            <tr key={d.key}>
              <td>{d.label}</td>
              <td className="mono">{diffValue(d.past)}</td>
              <td className={d.current === null ? "mono muted" : "mono"}>{d.current === null ? "현재 결과 없음" : diffValue(d.current)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
