// v0.24.1 Case ③ 3D 하중 출처 탭 + 보기 + 하중 색 + 재현 줄(esl_view3d_sources.md §6.1).
// 카드 머리 줄 오른쪽 = 출처 탭, 도구 줄 앞 = 보기 세그먼트·하중 색 선택, 끝 = 재현 한 줄 — 새 블록 줄 없음(세로 높이 불변).
// 출처·응답 가능 여부·사유는 서버 /view3d/sources 응답의 열만 읽는다(출처 이름 분기 없음).
import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { Range } from "../components/ColorLegend";
import { LoadTable } from "./LoadTable";
import { SourceTabs } from "./SourceTabs";
import { View3DCard, type View3DOptions } from "./View3DCard";
import { LOAD_COMPS, VIEW_MODES, caseTabItems, defaultCaseSource, isLegacySource, needsRecon, reconLineText, sourceRowOf, type LoadComp, type ViewMode } from "./sources";
import { useCaseSources, useRecon } from "./useRecon";
import { useLoadView } from "./useLoadView";
import { loadUnitOf } from "./values";

const MODE_LABEL: Record<Exclude<ViewMode, "load">, string> = {
  tgt: "목표 변위 |u_tgt| (mm)",
  fit: "응답 변위 |u_fit| (mm)",
  err: "오차 |u_fit − u_tgt| (mm)",
};

export function CaseView3D({ runId, enabled, note }: { runId: string; enabled: boolean; note?: ReactNode }) {
  const srcs = useCaseSources(runId, enabled);
  const items = useMemo(() => caseTabItems(srcs.sources), [srcs.sources]);
  const def = defaultCaseSource(srcs.sources);
  const [pick, setPick] = useState<string | null>(null);
  const cur = srcs.sources ? (pick && items?.find((i) => i.key === pick)?.ok ? pick : def) : null;
  // 출처를 바꾸면 보기·하중 색 초기화(선택·화살표 단계는 useLoadView 가 초기화). 수동 범위는 출처를 바꿔도 유지(v0.24.6 §2.6) — Case(runId)가 바뀔 때만 초기화
  const [vmode, setVmode] = useState<ViewMode>("load");
  const [comp, setComp] = useState<LoadComp>("pa");
  const [manTF, setManTF] = useState<Range | null>(null);
  const [manErr, setManErr] = useState<Range | null>(null);
  useEffect(() => {
    setVmode("load");
    setComp("pa");
  }, [cur, runId]);
  useEffect(() => {
    setManTF(null);
    setManErr(null);
  }, [runId]);
  useEffect(() => setPick(null), [runId]);

  // 출처 목록을 기다린 뒤(또는 실패해 legacy 로) manifest 를 받는다
  const view = useLoadView(runId, enabled && !srcs.loading, cur);
  const row = sourceRowOf(srcs.sources, cur);
  const resp = !!row?.resp;
  const reconSrc = isLegacySource(cur) ? null : cur;
  const rc = useRecon(runId, reconSrc, enabled && resp && vmode !== "load");
  const manifest = view?.manifest ?? null;
  const n = manifest?.n_nodes ?? 0;
  const zeros = useMemo(() => new Float32Array(n * 3), [n]);
  if (!view) return null;

  const pa = manifest ? loadUnitOf(manifest) === "MPa" : true;
  const ready = !!rc.disp && !!rc.recon;
  // 목표: 재현 파일 tgt(있으면) → 없으면 values.bin u(= 목표 u_rel). 응답·오차: 재현 파일 필수(없으면 0 장 — 틀린 값을 보이지 않음)
  let dispOverride: View3DOptions["dispOverride"] = null;
  let range: Range | null | undefined;
  let rangeManual = false;
  let onRangeChange: ((r: Range | null) => void) | undefined;
  if (vmode !== "load") {
    const arr = !ready ? null : vmode === "fit" ? rc.disp!.fit : vmode === "err" ? rc.disp!.err : rc.disp!.tgt;
    if (arr && arr.length === n * 3) dispOverride = { u: arr, label: MODE_LABEL[vmode] };
    else if (needsRecon(vmode)) dispOverride = { u: zeros, label: MODE_LABEL[vmode] };
    const rg = rc.recon?.ranges;
    const autoMax = vmode === "err" ? rg?.err_max : rg ? Math.max(rg.tgt_max, rg.fit_max) : undefined;
    const man = vmode === "err" ? manErr : manTF;
    const auto = ready && autoMax && autoMax > 0 ? { min: 0, max: autoMax } : null;
    // 재현 자료를 기다리는 동안(또는 목표 = values.bin) 범위는 그림 자신의 u_max — View3DCard 가 정한다(range 안 줌)
    range = man ?? auto ?? undefined;
    rangeManual = !!man;
    onRangeChange = vmode === "err" ? setManErr : setManTF;
  }
  const tail = vmode !== "load" && (rc.recon || rc.error || rc.loading) ? (
    rc.recon ? (
      <span className="small mono" data-testid="v3d-recon-line" title={reconLineText(rc.recon)} style={{ flex: "1 1 0", minWidth: 0, overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis" }}>
        {reconLineText(rc.recon)}
      </span>
    ) : (
      <span className={`small${rc.error ? " warn-text" : " muted"}`} data-testid="v3d-recon-line" title={rc.error ?? undefined} style={{ flex: "1 1 0", minWidth: 0, overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis" }}>
        {rc.error ?? "재현 자료 만드는 중…"}
      </span>
    )
  ) : null;

  const effComp: LoadComp = pa ? comp : comp === "pa" ? "fn" : comp;
  const lead = srcs.failed ? null : (
    <>
      <div className="seg" role="group" aria-label="3D 보기" data-testid="v3d-mode">
        {VIEW_MODES.map((m) => {
          const off = needsRecon(m.key) && !resp;
          return (
            <button key={m.key} type="button" className={vmode === m.key ? "on" : ""} aria-pressed={vmode === m.key} aria-disabled={off} data-mode={m.key} title={off ? row?.resp_reason ?? "응답 변위 없음" : m.title} onClick={() => !off && setVmode(m.key)}>
              {m.label}
            </button>
          );
        })}
      </div>
      {vmode === "load" && (
        <select className="select small" aria-label="하중 색" data-testid="v3d-load-field" value={effComp} onChange={(e) => setComp(e.target.value as LoadComp)} title="하중 색: 면압 |Fn|/A · 법선 |Fn| · 크기 |F|">
          {LOAD_COMPS.map((c) => (
            <option key={c.key} value={c.key} disabled={c.key === "pa" && !pa}>
              {c.label}
            </option>
          ))}
        </select>
      )}
    </>
  );
  const options: View3DOptions = {
    colorBy: vmode === "load" ? "load" : "disp",
    headRight: items ? <SourceTabs items={items} tab={cur ?? ""} setTab={setPick} label="3D 하중 출처" prefix="v3d-src" testId="v3d-src-tab" whyTestId="v3d-src-tab-why" /> : undefined,
    toolsLead: lead,
    toolsTail: tail,
    loadField: vmode === "load" && !srcs.failed ? effComp : null,
    dispOverride,
    plan: vmode === "load" ? "case_load" : "case_disp",
    ...(vmode !== "load" ? { dispLabel: MODE_LABEL[vmode as Exclude<ViewMode, "load">] } : {}),
    ...(range !== undefined ? { range, rangeManual, onRangeChange } : {}),
  };
  return (
    <>
      <View3DCard view={view} options={options} />
      {note}
      <LoadTable view={view} />
    </>
  );
}
