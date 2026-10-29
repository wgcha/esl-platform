// ② t*·지지점의 지지 요약 카드(v0.10.0, esl_menu_restructure.md §5.3): 자동 3-2-1 결과 표시만(편집 UI 없음).
// 자동 선택이 품질 검사에 걸린 BLOCKED 일 때만 접힌 '고급 — 지지 노드 직접 지정'(노드 ID 3칸 → 기존 POST /support-sets, 같은 검사).
import { useState } from "react";
import { api } from "../api/endpoints";
import { ApiError, errorText } from "../api/client";
import type { Case, SupportChecks, SupportProblem, SupportSetOut } from "../api/types";
import { usePolling } from "../lib/usePolling";
import { Badge, Card, Empty } from "./ui";

import { dofText } from "../lib/format";

export { dofText } from "../lib/format";

export const SUPPORT_ROLES = ["1번 (3방향)", "2번 (2방향)", "3번 (1방향)"] as const;
export const SUPPORT_BLOCKED_TITLE = "지지점을 자동으로 정하지 못했습니다";
export const SUPPORT_BLOCKED_HINT = "모델(대상 파트) 형상을 확인하거나 관리자에게 기준(support.auto_check) 조정을 요청하세요";
export const SUPPORT_PENDING_TEXT = "t* 확정 시 자동으로 정합니다";
export const SUPPORT_ADVANCED_LABEL = "고급 — 지지 노드 직접 지정";

const fx = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? "–" : Math.abs(v) < 0.01 ? v.toExponential(1) : v.toFixed(d));
export const checksText = (k: SupportChecks) => `면적비 ${fx(k.area_ratio)} · 최소 거리 ${fx(k.min_dist_rel)} · 조건비 ${fx(k.cond_ratio)}`;

/** 지지 세트 출처 배지: 자동 / 사용자 지정(고급 칸) / 사용자 지정(이전 버전에서 편집) */
function SourceBadge({ s, manual }: { s: SupportSetOut; manual: boolean }) {
  if (s.source === "auto") return <Badge kind="ok">자동</Badge>;
  return <Badge kind="info">{manual ? "사용자 지정(고급)" : "사용자 지정(이전 버전에서 편집)"}</Badge>;
}

function Problems({ items }: { items: SupportProblem[] }) {
  if (!items.length) return null;
  return (
    <ul className="reasons small" data-testid="support-problems">
      {items.map((p, i) => (
        <li key={`${p.code}-${i}`} className="error-text" title={p.code}>
          {p.message}
        </li>
      ))}
    </ul>
  );
}

/** BLOCKED 일 때만: 노드 ID 3칸 + [지정 저장](보조). 422 SUPPORT_CHECK_FAILED 면 problems 를 그대로 보인다 */
function AdvancedSupport({ c, reload }: { c: Case; reload: () => Promise<void> }) {
  const [ids, setIds] = useState(["", "", ""]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<SupportProblem[]>([]);
  const nums = ids.map((v) => Number(v.trim()));
  const valid = ids.every((v) => /^\d+$/.test(v.trim()));
  const block = !valid ? "노드 ID 3개를 숫자로 입력하세요" : new Set(nums).size < 3 ? "세 노드가 서로 달라야 합니다" : null;
  async function save() {
    setBusy(true);
    setError(null);
    setProblems([]);
    try {
      await api.createSupport(c.id, nums);
      await reload();
    } catch (e) {
      if (e instanceof ApiError && Array.isArray(e.detail.problems)) setProblems(e.detail.problems as SupportProblem[]);
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="card support-adv" data-testid="support-advanced">
      <summary>{SUPPORT_ADVANCED_LABEL}</summary>
      <div className="card-body">
        <div className="small muted">자동 선택과 같은 품질 검사(공선·근접·조건비)를 거쳐 저장합니다.</div>
        <div className="support-adv-fields">
          {SUPPORT_ROLES.map((r, k) => (
            <label key={r} className="field">
              <span className="field-label">{r}</span>
              <input
                className="mono"
                inputMode="numeric"
                aria-label={`지지 노드 ${k + 1}`}
                value={ids[k]}
                onChange={(e) => setIds((old) => old.map((v, i) => (i === k ? e.target.value : v)))}
              />
            </label>
          ))}
          <span className="primary-wrap" title={block ?? undefined}>
            <button type="button" className="btn" disabled={!!block || busy} onClick={() => void save()}>
              {busy ? "저장 중…" : "지정 저장"}
            </button>
          </span>
        </div>
        {error && (
          <div className="error-text small" role="alert">
            {error}
          </div>
        )}
        <Problems items={problems} />
      </div>
    </details>
  );
}

export function SupportSummary({ c, allowed, reload }: { c: Case; allowed: boolean; reload: () => Promise<void> }) {
  const sets = usePolling(() => (c.current_support_set_id ? api.supportSets(c.id) : Promise.resolve([])), 0, [c.id, c.current_support_set_id]);
  const cur = sets.data?.find((s) => s.id === c.current_support_set_id) ?? null;
  const sa = c.tstar?.support_auto ?? null;
  const blocked = !c.current_support_set_id && sa?.status === "BLOCKED";
  const checks = sa?.checks ?? null;
  return (
    <>
      <Card title="지지점 (3-2-1, 자동)" right={cur ? <SourceBadge s={cur} manual={sa?.status === "MANUAL"} /> : undefined}>
        <div data-testid="support-summary">
          {c.current_support_set_id ? (
            !cur ? (
              <Empty>{sets.error ?? "불러오는 중…"}</Empty>
            ) : (
              <>
                <table className="table compact" aria-label="지지 노드">
                  <thead>
                    <tr>
                      <th>역할</th>
                      <th>노드 ID</th>
                      <th>dof</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cur.node_ids.map((id, k) => (
                      <tr key={k}>
                        <td>{SUPPORT_ROLES[k]}</td>
                        <td className="mono">{id}</td>
                        <td className="mono">{dofText(cur.dofs[k] ?? "")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {checks && (
                  <div className="small muted" data-testid="support-checks">
                    {checksText(checks)}
                  </div>
                )}
              </>
            )
          ) : blocked ? (
            <div className="warn-box" role="status" data-testid="support-blocked">
              <strong>{SUPPORT_BLOCKED_TITLE}</strong>
              <Problems items={sa?.problems ?? []} />
              <div className="small">{SUPPORT_BLOCKED_HINT}</div>
            </div>
          ) : (
            <div className="small muted">{SUPPORT_PENDING_TEXT}</div>
          )}
        </div>
      </Card>
      {blocked && allowed && <AdvancedSupport c={c} reload={reload} />}
    </>
  );
}
