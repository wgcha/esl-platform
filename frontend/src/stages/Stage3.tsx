import { useEffect, useMemo, useState } from "react";
import { api } from "../api/endpoints";
import type { Plane, SupportSuggest } from "../api/types";
import { Card, Empty } from "../components/ui";
import { PlaneScatter, type Marker } from "../components/PlaneScatter";
import { usePolling } from "../lib/usePolling";
import { StageFrame, type StageProps } from "./StageFrame";
import { blockReason, useAction } from "./common";

const ROLE = ["1번 (3방향 고정)", "2번 (2방향 고정)", "3번 (1방향 고정)"];
const AX: Record<string, string> = { "1": "x", "2": "y", "3": "z" };
export const dofText = (d: string) => (/^[123]+$/.test(d) ? `${d} (${d.split("").map((k) => AX[k]).join("·")})` : d);

function project(p: Plane, xyz: number[]): [number, number] {
  const d = xyz.map((v, k) => v - p.origin[k]);
  return [d[0] * p.e1[0] + d[1] * p.e1[1] + d[2] * p.e1[2], d[0] * p.e2[0] + d[1] * p.e2[1] + d[2] * p.e2[2]];
}

export function Stage3({ c, reload, allowed }: StageProps) {
  const ready = !!c.extract_summary;
  const preview = usePolling(() => (ready ? api.preview(c.id, c.tstar?.frame_index) : Promise.resolve(null)), 0, [c.id, ready, c.tstar?.frame_index]);
  const sets = usePolling(() => (ready ? api.supportSets(c.id) : Promise.resolve([])), 0, [c.id, ready, c.current_support_set_id]);
  const [suggest, setSuggest] = useState<SupportSuggest | null>(null);
  const [ids, setIds] = useState<string[]>(["", "", ""]);
  const act = useAction(reload);
  const current = sets.data?.find((s) => s.id === c.current_support_set_id) ?? null;

  // 자동값: 현재 지지점이 있으면 그것, 없으면 자동 제안(POST suggest, 저장 안 함)
  useEffect(() => {
    if (!ready || !sets.data) return;
    if (current) {
      setIds(current.node_ids.map(String));
      return;
    }
    if (!allowed) return;
    api
      .suggestSupport(c.id)
      .then((s) => {
        setSuggest(s);
        setIds(s.node_ids.map(String));
      })
      .catch((e) => act.setError(String(e?.message ?? e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, sets.data, current?.id]);

  const nums = ids.map((v) => Number(v.trim()));
  const valid = ids.every((v) => /^\d+$/.test(v.trim()));
  const known = current ?? suggest;
  const sameAsKnown = !!known && valid && known.node_ids.every((x, k) => x === nums[k]);
  const sameAsCurrent = !!current && valid && current.node_ids.every((x, k) => x === nums[k]);
  const prereq = !ready
    ? "① 추출을 먼저 실행하세요."
    : !valid
      ? "노드 ID 3개를 숫자로 입력하세요."
      : new Set(nums).size < 3
        ? "세 노드가 서로 달라야 합니다."
        : sameAsCurrent
          ? "현재 저장된 지지점과 같습니다."
          : null;

  const markers = useMemo<Marker[]>(() => {
    const pv = preview.data;
    if (!pv) return [];
    const byId = new Map<number, [number, number]>();
    for (const [id, a, b] of pv.points) byId.set(id, [a, b]);
    const out: Marker[] = [];
    if (suggest) suggest.corners.forEach((xyz, k) => out.push({ label: `C${k + 1}`, ...toAB(project(pv.plane, xyz)), kind: "corner" }));
    nums.forEach((id, k) => {
      const ab = byId.get(id);
      if (ab) out.push({ label: `${k + 1}: ${id}`, a: ab[0], b: ab[1], kind: "support" });
    });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview.data, suggest, ids.join(",")]);

  const save = () => act.run(() => api.createSupport(c.id, nums));

  return (
    <StageFrame
      title="③ 지지점"
      status={c.stage_status?.["3"]}
      error={act.error ?? preview.error ?? sets.error}
      primary={{ label: "지지점 저장", onClick: save, disabledReason: blockReason(allowed, c, 3, prereq), busy: act.busy }}
    >
      {!ready ? (
        <Empty>① 입력 단계에서 추출을 먼저 실행하세요.</Empty>
      ) : (
        <div className="grid-main">
          <Card title={`PCA 평면 (t* 프레임 ${c.tstar?.frame_index ?? "–"})`}>
            {preview.data ? (
              <PlaneScatter points={preview.data.points} markers={markers} valueLabel="|u| (mm)" />
            ) : (
              <Empty>불러오는 중…</Empty>
            )}
            {preview.data?.decimated && <div className="small muted">점이 많아 일부만 표시했습니다.</div>}
          </Card>
          <Card title="3-2-1 지지 노드">
            <div className="form">
              {ROLE.map((r, k) => (
                <label key={k}>
                  {r}
                  <input
                    className="mono"
                    inputMode="numeric"
                    aria-label={`지지 노드 ${k + 1}`}
                    value={ids[k]}
                    disabled={!allowed}
                    onChange={(e) => setIds((old) => old.map((v, i) => (i === k ? e.target.value : v)))}
                  />
                  <span className="small muted">
                    dof {sameAsKnown && known ? dofText(known.dofs[k]) : "저장 시 자동 결정"}
                  </span>
                </label>
              ))}
            </div>
            <div className="small muted">
              {current ? `저장됨 · ${current.source === "auto" ? "자동" : "사용자 지정"}` : suggest ? "자동 제안값 (아직 저장 안 함)" : ""}
            </div>
          </Card>
        </div>
      )}
    </StageFrame>
  );
}

function toAB([a, b]: [number, number]) {
  return { a, b };
}
