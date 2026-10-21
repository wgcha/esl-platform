import { useState } from "react";
import { api } from "../api/endpoints";
import { errorText } from "../api/client";
import type { InspectRadResult, InspectResultsResult } from "../api/types";
import { normPartTitle } from "../lib/partTitle";
import { Badge } from "./ui";

type Purpose = "RAD" | "RESULTS";
type ResultOf<P extends Purpose> = P extends "RAD" ? InspectRadResult : InspectResultsResult;

/** 경로 입력 + "확인"(POST /paths/inspect) */
export function usePathInspect<P extends Purpose>(purpose: P, initial = "") {
  const [path, setPathRaw] = useState(initial);
  const [result, setResult] = useState<ResultOf<P> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const setPath = (v: string) => {
    setPathRaw(v);
    setResult(null);
    setError(null);
  };

  async function inspect(p = path, partTitle?: string) {
    setBusy(true);
    setError(null);
    try {
      const r = (purpose === "RAD" ? await api.inspectRad(p, partTitle) : await api.inspectResults(p)) as ResultOf<P>;
      setResult(r);
    } catch (e) {
      setResult(null);
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const field = (label: string, placeholder: string) => (
    <div className="pathinput path-field">
      <span className="field-label">{label}</span>
      <div className="pathinput-row">
        <input type="text" className="mono" value={path} placeholder={placeholder} aria-label={label} spellCheck={false} onChange={(e) => setPath(e.target.value)} />
        <button type="button" className="btn" disabled={!path.trim() || busy} onClick={() => inspect()}>
          {busy ? "확인 중…" : "확인"}
        </button>
      </div>
      {error && (
        <div className="small error-text" role="alert">
          {error}
        </div>
      )}
    </div>
  );

  return { path, setPath, result, error, busy, inspect, field };
}

export function RadInspectView({ r, partTitle, onPickPart }: { r: InspectRadResult; partTitle: string; onPickPart?: (title: string) => void }) {
  const want = normPartTitle(partTitle);
  // 대상 파트를 못 찾았거나 둘 이상일 때만 행을 눌러 title 입력을 채운다
  const pickable = !!onPickPart && r.problems.some((p) => p.startsWith("PART_NOT_FOUND") || p.startsWith("PART_AMBIGUOUS"));
  return (
    <div className={r.ok ? "inspect ok" : "inspect bad"} aria-label="rad 확인 결과">
      <div>
        {r.ok ? <Badge kind="ok">rad 읽기 가능</Badge> : <Badge kind="bad">문제 있음</Badge>}
        {r.target_part && (
          <span className="muted">
            {" "}
            대상 파트 {r.target_part.title} (id {r.target_part.id})
          </span>
        )}
        {r.problems.map((p) => (
          <div key={p} className="small error-text">
            {p}
          </div>
        ))}
      </div>
      {pickable && <div className="small muted">표에서 파트를 누르면 채워집니다</div>}
      <table className="table compact">
        <thead>
          <tr>
            <th>파트 id</th>
            <th>title</th>
            <th className="num">요소 수</th>
          </tr>
        </thead>
        <tbody>
          {r.parts.map((p) => (
            <tr
              key={p.id}
              className={[want && normPartTitle(p.title) === want ? "hl" : "", pickable ? "pickable" : ""].filter(Boolean).join(" ") || undefined}
              onClick={pickable ? () => onPickPart!(p.title) : undefined}
              onKeyDown={pickable ? (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onPickPart!(p.title)) : undefined}
              tabIndex={pickable ? 0 : undefined}
              title={pickable ? "누르면 파트 title 입력에 채웁니다" : undefined}
            >
              <td>{p.id}</td>
              <td>{p.title}</td>
              <td className="num">{p.n_elems?.toLocaleString() ?? "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {r.includes.length > 0 && (
        <div className="small">
          include:{" "}
          {r.includes.map((i) => (
            <span key={i.path} className={i.ok ? "muted" : "error-text"}>
              {i.path.split(/[\\/]/).pop()} {i.ok ? "✓" : "✗"}{" "}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function ResultsInspectView({ r }: { r: InspectResultsResult }) {
  const d = r.done;
  const cf = d?.candidate_frames ?? {};
  return (
    <div className={r.ok && d?.ok ? "inspect ok" : "inspect bad"} aria-label="결과 폴더 확인 결과">
      <div>
        {r.ok && d?.ok ? <Badge kind="ok">done.json 정상</Badge> : <Badge kind="bad">done.json 문제</Badge>}
        <span className="muted">
          {" "}
          파트 {d?.part_spec ?? "–"} (id {d?.part_id ?? "–"}) · 프레임 {r.n_frames ?? "–"} · hot_k {d?.hot_k ?? "–"} · 후보 프레임 Max_Strain [
          {(cf.max_strain ?? []).join(", ")}], Plastic [{(cf.plastic_strain ?? []).join(", ")}]
        </span>
      </div>
      {[...r.problems, ...(d?.warnings ?? [])].map((p) => (
        <div key={p} className="small error-text">
          {p}
        </div>
      ))}
    </div>
  );
}
