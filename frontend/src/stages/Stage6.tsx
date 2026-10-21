import { useState } from "react";
import { api } from "../api/endpoints";
import { ApiError, downloadFile } from "../api/client";
import type { ArtifactOut, ExportTarget } from "../api/types";
import { Card, Empty } from "../components/ui";
import { usePolling } from "../lib/usePolling";
import { bytes } from "../lib/format";
import { StageFrame, type StageProps } from "./StageFrame";
import { blockReason, useAction } from "./common";
import { CopyPath, TOO_LARGE_TEXT } from "../components/CopyPath";
import { BundleButton } from "../components/BundleButton";
import { p3 } from "../api/p3";

const TARGETS: { key: ExportTarget; label: string }[] = [
  { key: "radioss_inc", label: "Radioss inc (/CLOAD·/BCS)" },
  { key: "fem", label: "OptiStruct fem" },
  { key: "csv", label: "CSV" },
];

export { CopyPath, TOO_LARGE_TEXT } from "../components/CopyPath";

/** 다운로드: 413 ARTIFACT_TOO_LARGE(또는 downloadable=false)면 안내 + 경로 복사 */
function DownloadCell({ a }: { a: ArtifactOut }) {
  const [tooLarge, setTooLarge] = useState<{ path: string; size?: number; limit?: number } | null>(
    a.downloadable ? null : { path: a.path, size: a.size },
  );
  const [error, setError] = useState<string | null>(null);
  if (tooLarge)
    return (
      <div className="too-large" role="status" data-testid="too-large">
        <div className="small warn-text">
          {TOO_LARGE_TEXT}
          {tooLarge.limit ? ` (한도 ${bytes(tooLarge.limit)})` : ""}
        </div>
        <CopyPath path={tooLarge.path} />
      </div>
    );
  return (
    <>
      <a
        href={api.downloadUrl(a.id)}
        download
        onClick={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            await downloadFile(api.downloadUrl(a.id), a.rel.split("/").pop() ?? "download");
          } catch (x) {
            if (x instanceof ApiError && x.status === 413)
              setTooLarge({ path: String(x.detail.path ?? a.path), size: x.detail.size, limit: x.detail.limit });
            else setError(x instanceof Error ? x.message : String(x));
          }
        }}
      >
        다운로드
      </a>
      {error && <div className="small error-text">{error}</div>}
    </>
  );
}

function FileTable({ files }: { files: ArtifactOut[] }) {
  return (
    <div className="table-wrap scroll">
      <table className="table compact">
        <thead>
          <tr>
            <th>파일</th>
            <th>종류</th>
            <th className="num">크기</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {files.map((a) => (
            <tr key={a.id}>
              <td className="mono">{a.rel}</td>
              <td>{a.kind}</td>
              <td className="num">{bytes(a.size)}</td>
              <td>
                <DownloadCell a={a} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Stage6({ c, reload, allowed }: StageProps) {
  const [targets, setTargets] = useState<ExportTarget[]>(["radioss_inc", "fem", "csv"]);
  const arts = usePolling(() => api.artifacts(c.id), 0, [c.id, c.version, c.stage_status?.["6"]?.state]);
  const act = useAction(reload);
  const exported = (arts.data ?? []).filter((a) => a.rel.startsWith("06_export/"));
  const others = (arts.data ?? []).filter((a) => !a.rel.startsWith("06_export/"));
  const runId = c.current_esl_run_id;
  const folder = c.folder_path;
  const prereq = !runId ? "④ ESL을 먼저 계산하세요" : targets.length === 0 ? "내보낼 대상을 하나 이상 고르세요" : null;

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
        <Card title="결과 폴더" right={<BundleButton url={p3.caseBundleUrl(c.id)} filename={`${c.folder_name}_result.zip`} fallbackPath={folder} />}>
          <CopyPath path={folder} testId="folder-path" />
          <div className="small muted">내보낸 파일은 이 폴더의 06_export 아래에 있습니다. 내 PC로 한 번에 받으려면 '결과 받기(zip)'.</div>
        </Card>
      </div>
      <Card title="내보낸 파일 (06_export)">
        {exported.length ? (
          <FileTable files={exported} />
        ) : (
          <Empty>{arts.data ? "아직 내보낸 파일이 없습니다" : "불러오는 중…"}</Empty>
        )}
      </Card>
      {others.length > 0 && (
        <details className="card">
          <summary>다른 단계 산출물 {others.length}개 (추출·t*·ESL·검증·로그)</summary>
          <FileTable files={others} />
        </details>
      )}
    </StageFrame>
  );
}
