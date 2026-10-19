import { useState } from "react";
import { api } from "../api/endpoints";
import type { ExportTarget } from "../api/types";
import { Card, Empty } from "../components/ui";
import { usePolling } from "../lib/usePolling";
import { bytes } from "../lib/format";
import { StageFrame, type StageProps } from "./StageFrame";
import { blockReason, useAction } from "./common";

const TARGETS: { key: ExportTarget; label: string }[] = [
  { key: "radioss_inc", label: "Radioss inc (/CLOAD·/BCS)" },
  { key: "fem", label: "OptiStruct fem" },
  { key: "csv", label: "CSV" },
];

export function Stage6({ c, reload, allowed }: StageProps) {
  const [targets, setTargets] = useState<ExportTarget[]>(["radioss_inc", "fem", "csv"]);
  const arts = usePolling(() => api.artifacts(c.id), 0, [c.id, c.version, c.stage_status?.["6"]?.state]);
  const act = useAction(reload);
  const [copied, setCopied] = useState(false);
  const runId = c.current_esl_run_id;
  const folder = c.folder_path ?? c.folder_name;
  const prereq = !runId ? "④ ESL을 먼저 계산하세요." : targets.length === 0 ? "내보낼 대상을 하나 이상 고르세요." : null;

  async function copy() {
    try {
      await navigator.clipboard.writeText(folder);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* 클립보드 사용 불가 */
    }
  }

  return (
    <StageFrame
      title="⑥ 내보내기"
      status={c.stage_status?.["6"]}
      error={act.error ?? arts.error}
      onJobDone={() => void reload()}
      primary={{
        label: "내보내기",
        onClick: () => act.run(() => api.exportJob(c.id, runId!, targets)),
        disabledReason: blockReason(allowed, c, 6, prereq),
        busy: act.busy,
      }}
    >
      <div className="grid2">
        <Card title="대상">
          <div className="checks">
            {TARGETS.map((t) => (
              <label key={t.key} className="check">
                <input
                  type="checkbox"
                  checked={targets.includes(t.key)}
                  disabled={!allowed}
                  onChange={(e) => setTargets((old) => (e.target.checked ? [...old, t.key] : old.filter((x) => x !== t.key)))}
                />
                {t.label}
              </label>
            ))}
          </div>
        </Card>
        <Card title="결과 폴더">
          <div className="row">
            <span className="mono path" data-testid="folder-path">
              {folder}
            </span>
            <button type="button" className="btn" onClick={copy}>
              {copied ? "복사됨" : "복사"}
            </button>
          </div>
        </Card>
      </div>
      <Card title="파일">
        {arts.data && arts.data.length ? (
          <table className="tbl compact">
            <thead>
              <tr>
                <th>파일</th>
                <th>종류</th>
                <th>크기</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {arts.data.map((a) => (
                <tr key={a.id}>
                  <td className="mono">{a.rel}</td>
                  <td>{a.kind}</td>
                  <td>{bytes(a.size)}</td>
                  <td>
                    <a href={api.downloadUrl(a.id)} download>
                      다운로드
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{arts.data ? "아직 내보낸 파일이 없습니다." : "불러오는 중…"}</Empty>
        )}
      </Card>
    </StageFrame>
  );
}
