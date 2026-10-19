import { useState } from "react";
import { api } from "../api/endpoints";
import { errorText } from "../api/client";
import type { InspectRadResult, InspectResultsResult } from "../api/types";
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

  async function inspect(p = path) {
    setBusy(true);
    setError(null);
    try {
      const r = (purpose === "RAD" ? await api.inspectRad(p) : await api.inspectResults(p)) as ResultOf<P>;
      setResult(r);
    } catch (e) {
      setResult(null);
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const field = (label: string, placeholder: string) => (
    <div className="path-field">
      <label>
        {label}
        <span className="row">
          <input className="mono" value={path} placeholder={placeholder} onChange={(e) => setPath(e.target.value)} />
          <button type="button" className="btn" disabled={!path.trim() || busy} onClick={() => inspect()}>
            {busy ? "확인 중…" : "확인"}
          </button>
        </span>
      </label>
      {error && <div className="small bad-text">{error}</div>}
    </div>
  );

  return { path, setPath, result, error, busy, inspect, field };
}

export function RadInspectView({ r, partTitle }: { r: InspectRadResult; partTitle: string }) {
  const want = partTitle.trim().toLowerCase();
  return (
    <div className="inspect" aria-label="rad 확인 결과">
      <div>
        {r.ok ? <Badge kind="ok">rad 읽기 가능</Badge> : <Badge kind="bad">문제 있음</Badge>}
        {r.units_label && <span className="muted"> 단위 {r.units_label}</span>}
        {r.problems.map((p) => (
          <div key={p} className="small bad-text">
            {p}
          </div>
        ))}
      </div>
      <table className="tbl compact">
        <thead>
          <tr>
            <th>파트 id</th>
            <th>title</th>
            <th>요소 수</th>
          </tr>
        </thead>
        <tbody>
          {r.parts.map((p) => (
            <tr key={p.id} className={want && p.title.toLowerCase() === want ? "hl" : undefined}>
              <td>{p.id}</td>
              <td>{p.title}</td>
              <td>{p.n_elems.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {r.includes.length > 0 && (
        <div className="small">
          include:{" "}
          {r.includes.map((i) => (
            <span key={i.path} className={i.ok ? "muted" : "bad-text"}>
              {i.path.split(/[\\/]/).pop()} {i.ok ? "✓" : "✗"}{" "}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function ResultsInspectView({ r }: { r: InspectResultsResult }) {
  const cf = r.done.candidate_frames;
  return (
    <div className="inspect" aria-label="결과 폴더 확인 결과">
      <div>
        {r.ok && r.done.ok ? <Badge kind="ok">done.json 정상</Badge> : <Badge kind="bad">done.json 문제</Badge>}
        <span className="muted">
          {" "}
          파트 {r.done.part_spec ?? "–"} (id {r.done.part_id ?? "–"}) · 프레임 {r.n_frames} · 후보 프레임 Max_Strain {cf.max_strain?.length ?? 0}개, Plastic {cf.plastic_strain?.length ?? 0}개
        </span>
      </div>
      {[...r.problems, ...r.done.warnings].map((p) => (
        <div key={p} className="small bad-text">
          {p}
        </div>
      ))}
    </div>
  );
}
