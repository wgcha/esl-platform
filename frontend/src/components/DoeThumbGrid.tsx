// 비드 DOE ④ 미리보기 썸네일 격자(esl_bead_doe.md §5·§12.2): d000 공칭 + 안별 썸네일(320×240 축소), 스킵 = 회색 + 사유 배지,
// 마우스를 올리면 값 툴팁. 2560 폭 8열 · 1920 폭 6열(가로 스크롤 없음).
import { useEffect, useState } from "react";
import { cellStatusName, isFailed, isSkipped } from "../api/doe";
import { HeightLegend } from "./BeadSelectCard";
import type { DoeParam, DoePreviewCell, DoePreviewOut } from "../api/types";
import { Empty } from "./ui";

/** 같은 출처 이미지 → blob URL(인증 쿠키·목 서버 통과). 실패 = error */
export function useBlobUrl(url: string | null): { src: string | null; error: string | null } {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setSrc(null);
    setError(null);
    if (!url) return;
    let made: string | null = null;
    let alive = true;
    fetch(url, { credentials: "same-origin" })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(`그림을 불러오지 못했습니다(${r.status})`))))
      .then((b) => {
        if (!alive || typeof URL.createObjectURL !== "function") return;
        made = URL.createObjectURL(b);
        setSrc(made);
      })
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [url]);
  return { src, error };
}

/** 변수 짧은 이름(B1 D) — 표·툴팁용 */
export function shortName(params: DoeParam[], name: string): string {
  const p = params.find((x) => x.name === name);
  // v0.15.0 select: B1_D2 → "B1 D2"
  if (p?.tier != null || /^B\d+_(D\d+|W)$/.test(name)) return name.replace("_", " ");
  return p ? `${p.bead} ${p.type}` : name;
}

export const valuesText = (params: DoeParam[], values: Record<string, number>) =>
  Object.entries(values)
    .map(([k, v]) => `${shortName(params, k)} ${v}`)
    .join(" · ");

function Thumb({ id, url, cell, params, select, onOpen }: { id: string; url: string | null; cell: DoePreviewCell | null; params: DoeParam[]; select?: boolean; onOpen?: (id: string) => void }) {
  const { src, error } = useBlobUrl(url);
  const skipped = cell ? isSkipped(cell.status) || (!!select && isFailed(cell.status)) : false;
  const tip = cell ? `${id} · ${valuesText(params, cell.values)}${cell.code ? ` · ${cell.code}` : ""}` : `${id} 공칭`;
  const open = onOpen ? () => onOpen(id) : undefined;
  return (
    <li
      className={`doe-thumb${skipped ? " skipped" : ""}${open ? " clickable" : ""}`}
      title={open ? `${tip} — 클릭하면 3D 로 봅니다` : tip}
      data-testid={`thumb-${id}`}
      data-status={cell?.status ?? "NOMINAL"}
      tabIndex={0}
      aria-label={tip}
      onClick={open}
      onKeyDown={open ? (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), open()) : undefined}
    >
      <div className="doe-thumb-img">
        {src ? <img src={src} alt="" /> : <span className="small muted">{error || !url ? "그림 없음" : "…"}</span>}
      </div>
      <div className="doe-thumb-cap">
        <span className="mono">{id}</span>
        {!cell && <span className="badge info">공칭</span>}
        {cell && skipped && <span className="badge bad">⨯{cellStatusName(cell.status, !!select)}</span>}
        {cell && select && !skipped && <span className="badge ok">OK</span>}
        {cell && !skipped && !cell.thumb && <span className="badge warn" title="썸네일을 만들지 못했습니다(형상 변경은 성공)">그림 없음</span>}
      </div>
    </li>
  );
}

export function previewSummary(p: DoePreviewOut, n: number): string {
  const s = p.skipped;
  return `(${n}) OK ${p.ok}${s.collision ? ` · 충돌 ${s.collision}` : ""}${s.fixed ? ` · 고정 침범 ${s.fixed}` : ""}${s.geom ? ` · 형상 불가 ${s.geom}` : ""}${s.mesh ? ` · 품질 실패 ${s.mesh}` : ""}`;
}

/** select = v0.15.0 비드 직접 선택(범례 1개·품질 실패 배지·클릭 → 3D) */
export function DoeThumbGrid({ preview, params, thumbUrl, select, onOpen }: { preview: DoePreviewOut | null; params: DoeParam[]; thumbUrl: (did: string) => string; select?: boolean; onOpen?: (did: string) => void }) {
  if (!preview) return <Empty>미리보기를 실행하면 안별 썸네일이 보입니다</Empty>;
  const cells = preview.cells ?? [];
  return (
    <>
      {select && preview.color && <HeightLegend vmax={preview.color.v_max} unit={preview.color.unit} />}
      <ul className="doe-thumbs" aria-label="미리보기 썸네일">
        <Thumb id="d000" url={thumbUrl("d000")} cell={null} params={params} select={select} onOpen={onOpen} />
        {cells.map((c) => (
          <Thumb key={c.id} id={c.id} url={c.thumb ? thumbUrl(c.id) : null} cell={c} params={params} select={select} onOpen={onOpen} />
        ))}
      </ul>
    </>
  );
}
