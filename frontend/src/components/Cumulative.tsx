// v0.8.0 누적 낙하 씬 표시(계약 esl_cumulative_input.md §8) — 필수 UI 만: Case 배지, ① 누적 입력 카드, 값 표기 도우미.
import type { CumulativeDiagnosis, CumulativeSummary, TstarPoint } from "../api/types";
import { bytes, fmt } from "../lib/format";
import { Badge, Card, Stat } from "./ui";

const MODE_KO: Record<string, string> = { cumulative: "누적값", incremental: "증분(이번 낙하분)", trivial: "이전 소성 거의 없음" };
const KIND_KO: Record<string, string> = { geometry: "형상", initial: "초기 소성" };

export const hasCum = (p: { value_inc?: number } | null | undefined): p is TstarPoint & { value_inc: number; value_prev: number } =>
  !!p && typeof p.value_inc === "number";

/** `누적 0.123 (이전 0.080 + 이번 0.043)` */
export function cumText(p: { value: number; value_inc?: number; value_prev?: number }, d = 4): string {
  if (typeof p.value_inc !== "number") return fmt(p.value, d);
  return `누적 ${fmt(p.value, d)} (이전 ${fmt(p.value_prev ?? p.value - p.value_inc, d)} + 이번 ${fmt(p.value_inc, d)})`;
}

function modeText(d: CumulativeDiagnosis | undefined, fallback: string): { text: string; tip: string } {
  const m = d?.mode ?? fallback;
  let text = MODE_KO[m] ?? m;
  if (d?.detected === "ambiguous") text = "판정 불확실 → 증분으로 보고 합";
  if (d?.forced) text += " (설정)";
  const tip = d && d.r0 != null ? `r0 = ${fmt(d.r0, 3)} · 일치 비율 ${fmt(d.mono, 3)} · 비교 요소 ${d.n_S}` : "frame 0 비교 요소 부족";
  return { text, tip };
}

export function CumulativeBadge({ s }: { s: CumulativeSummary | undefined }) {
  if (!s) return null;
  const tip = s.files.map((f) => `${f.name}${f.runname ? ` (${f.runname})` : ""}`).join("\n");
  return (
    <span title={tip} data-testid="cum-badge">
      <Badge kind="info">누적 씬</Badge>
    </span>
  );
}

/** ① 추출 결과의 "누적 입력" 카드: 상태 파일·좌표 출처·두께 변화·이전 소성·h3d 판정·경고 코드 */
export function CumulativeCard({ s }: { s: CumulativeSummary }) {
  const th = s.thickness;
  const r = th?.ratio;
  const ep = modeText(s.diagnosis?.epsp, s.epsp_mode);
  const eq = modeText(s.diagnosis?.eq, s.eq_mode);
  return (
    <Card title="누적 입력" right={<span className="small muted">이전 낙하 해석 상태 파일을 include</span>}>
      <div data-testid="cum-card">
        <div className="table-wrap">
          <table className="table compact" aria-label="상태 파일">
            <thead>
              <tr>
                <th>상태 파일</th>
                <th>종류</th>
                <th className="num">크기</th>
                <th>이전 런</th>
              </tr>
            </thead>
            <tbody>
              {s.files.map((f) => (
                <tr key={f.name}>
                  <td className="mono">{f.name}</td>
                  <td>{f.kinds.map((k) => KIND_KO[k] ?? k).join(" · ") || "–"}</td>
                  <td className="num">{f.size != null ? bytes(f.size) : "–"}</td>
                  <td className="mono small">{f.runname ?? "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="stats">
          <Stat
            label="좌표 출처"
            value={`상태 ${s.n_nodes_state.toLocaleString()} / rad ${(s.n_nodes_rad ?? 0).toLocaleString()}`}
            sub="계산 형상 = 이전 런 변형 좌표"
          />
          <Stat
            label="두께 t/t₀"
            value={r ? `${fmt(r.min, 4)} ~ ${fmt(r.max, 4)}` : "–"}
            sub={r ? `평균 ${fmt(r.mean, 4)} · K_L 두께 ${th.k_l_source === "prop" ? "원두께" : "상태 THK"}` : "원두께 없음"}
          />
          <Stat
            label="두께 변화 >1 %"
            value={th?.n_changed != null ? th.n_changed.toLocaleString() : "–"}
            sub={th?.max_thinning_pct != null ? `최대 감육 ${fmt(th.max_thinning_pct, 3)} % · 요소 ${th.elem_max_thinning}` : undefined}
          />
          <Stat
            label="이전 소성 변형률"
            value={fmt(s.prev_max, 4)}
            sub={`P99 ${fmt(s.prev_p99, 4)} · 양수 ${s.n_prev_elems.toLocaleString()}요소 · 집계 ${s.agg}`}
          />
          <Stat label="h3d 소성" value={ep.text} hint={ep.tip} />
          <Stat label="h3d 총변형률" value={eq.text} hint={eq.tip} />
        </div>
        {s.warning_codes.length > 0 && (
          <div className="small warn-text" data-testid="cum-warn">
            경고: {s.warning_codes.join(", ")}
          </div>
        )}
        <div className="small muted">t* 는 누적(이전 + 이번) 순위, 시점은 이번 낙하 증분 기준. 총변형률의 이전 값은 이전 소성 변형률로 근사합니다.</div>
      </div>
    </Card>
  );
}
