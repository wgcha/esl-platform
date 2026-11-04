// 비드 DOE ② 비드·변수(esl_bead_doe.md §5·§12.2, BD-D-7): 비드별 D·W·U/V 포함 체크·범위(기본 = feasible), 범위 밖 경고 배지(차단 아님),
// 하한 ≥ 상한·깊이/폭 ≤ 0 은 오류. DOE 방식·안 수(풀 팩토리얼은 수준)·시드 + 실제 안 수(POST /matrix). 방법·출처 ⓘ.
import { useEffect, useRef, useState } from "react";
import { METHOD_NAME, TYPE_NAME, doeSourcesOk, outsideFeasible, rowProblem, warnText, type ParamRow, type SpecForm } from "../api/doe";
import type { DoeBead, DoeMatrixOut, DoeMethod, DoeMethodSources, DoeParamsOut, DoeSettingsOut } from "../api/types";
import { useBlobUrl } from "./DoeThumbGrid";
import { Field } from "./ui";

const SHAPE: Record<string, string> = { linear: "선형", circular: "원형" };
const SENSE: Record<string, string> = { concave: "오목", convex: "볼록" };

/** 방법·출처 ⓘ(기존 MethodInfo 방식 — 문구·링크는 GET /doe/settings.method_sources) */
export function DoeMethodInfo({ src: raw, method }: { src: DoeMethodSources | null | undefined; method?: DoeMethod | null }) {
  const [open, setOpen] = useState(false);
  const src = doeSourcesOk(raw) ? raw : null;
  const btn = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node) && !btn.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    box.current?.focus();
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);
  const close = () => {
    setOpen(false);
    btn.current?.focus();
  };
  return (
    <span className="method-info">
      <button ref={btn} type="button" className="info-btn" aria-label="방법·출처" aria-expanded={open} aria-haspopup="dialog" disabled={!src} title={!src && raw?.error ? raw.error : undefined} onClick={() => setOpen((o) => !o)}>
        ⓘ
      </button>
      {open && src && (
        <div
          ref={box}
          className="method-pop"
          role="dialog"
          aria-label="방법·출처"
          tabIndex={-1}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              close();
            }
          }}
        >
          <div className="method-sec">
            {src.summary_ko.map((s) => (
              <p key={s}>{s}</p>
            ))}
          </div>
          <div className="method-sec">
            <div className="sub-title">DOE 방식</div>
            <ul>
              {Object.entries(src.methods).map(([k, v]) => (
                <li key={k} className={k === method ? "on" : undefined} data-current={k === method || undefined}>
                  {v}
                </li>
              ))}
            </ul>
          </div>
          {src.metrics && Object.keys(src.metrics).length > 0 && (
            <div className="method-sec">
              <div className="sub-title">지표</div>
              <ul>
                {Object.entries(src.metrics).map(([k, v]) => (
                  <li key={k}>{v}</li>
                ))}
              </ul>
            </div>
          )}
          {src.limits && src.limits.length > 0 && (
            <div className="method-sec">
              <div className="sub-title">한계</div>
              <ul>
                {src.limits.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="method-sec">
            <div className="sub-title">출처</div>
            <ol>
              {src.sources.map((s) => (
                <li key={s.title}>
                  {s.url ? (
                    <a href={s.url} target="_blank" rel="noopener noreferrer">
                      {s.title}
                    </a>
                  ) : (
                    <span>{s.title}</span>
                  )}
                  {s.authors && <span className="muted"> — {s.authors}</span>}
                  {s.note && <span className="muted small"> ({s.note})</span>}
                </li>
              ))}
            </ol>
          </div>
          <div className="method-foot">
            <span className="small muted">자료 v{src.version}</span>
            <button type="button" className="btn small ghost" onClick={close}>
              닫기
            </button>
          </div>
        </div>
      )}
    </span>
  );
}

function BeadPng({ url, id }: { url: string | null; id: string }) {
  const { src } = useBlobUrl(url);
  return src ? <img className="doe-bead-png" src={src} alt={`${id} 비드 그림`} /> : <span className="doe-bead-png" />;
}

function beadText(b: DoeBead) {
  const n = b.nominal;
  return `${SHAPE[b.shape] ?? b.shape} ${SENSE[b.sense] ?? b.sense} · 공칭 D ${n.depth} · W ${n.width}${n.length ? ` · L ${n.length}` : ""} mm`;
}

/** v0.15.0 select: 블렌딩 반경 편집(선택 상태 — 바꾸면 [선택 저장])·행 고르기(평면도 범위 표시) */
export interface SelectTableOpts {
  blendOf: (bead: string) => "auto" | number | null;
  setBlend: (bead: string, v: "auto" | number) => void;
  /** select.blend.k(서버) — 없으면 "R 작음" 배지 없음 */
  kBlend: number | null;
  blendMax: number;
  active: string | null;
  onActive: (name: string) => void;
}

/** "R 작음"(§5.6): R < k × 최대 한쪽 이동(|W − W_nom|/2) */
export function blendSmall(R: number | null | undefined, k: number | null, nominal: number, lo: number, hi: number): boolean {
  if (R == null || !k || !Number.isFinite(lo) || !Number.isFinite(hi)) return false;
  return R < (k * Math.max(Math.abs(hi - nominal), Math.abs(lo - nominal))) / 2;
}

function BlendField({ bead, opts, readOnly, resolved }: { bead: string; opts: SelectTableOpts; readOnly: boolean; resolved: number | null | undefined }) {
  const v = opts.blendOf(bead);
  const auto = v === "auto" || v === null;
  return (
    <span className="bs-blend">
      블렌딩
      <select aria-label={`${bead.toUpperCase()} 블렌딩 반경`} value={auto ? "auto" : "num"} disabled={readOnly} onChange={(e) => opts.setBlend(bead, e.target.value === "auto" ? "auto" : Math.round(resolved ?? 20))}>
        <option value="auto">auto{resolved != null && auto ? ` ${resolved} mm` : ""}</option>
        <option value="num">숫자</option>
      </select>
      {!auto && (
        <input type="number" className="doe-num short" aria-label={`${bead.toUpperCase()} 블렌딩 mm`} min={0} max={opts.blendMax} step={1} value={v as number} disabled={readOnly} onChange={(e) => {
          const x = Number(e.target.value);
          if (Number.isFinite(x) && x >= 0 && x <= opts.blendMax) opts.setBlend(bead, x);
        }} />
      )}
    </span>
  );
}

export function DoeParamTable({ data, rows, setRows, readOnly, beadPngUrl, select }: {
  data: DoeParamsOut;
  rows: ParamRow[];
  setRows: (r: ParamRow[]) => void;
  readOnly: boolean;
  beadPngUrl: (bead: string) => string;
  select?: SelectTableOpts;
}) {
  const byName = new Map(rows.map((r) => [r.name, r]));
  const upd = (name: string, patch: Partial<ParamRow>) => setRows(rows.map((r) => (r.name === name ? { ...r, ...patch } : r)));
  const grouped = new Set(data.params.flatMap((p) => p.group_members));
  return (
    <div className="table-wrap">
      <table className="table compact doe-params" aria-label="비드 변수">
        <thead>
          <tr>
            <th>포함</th>
            <th>변수</th>
            <th className="num">하한</th>
            <th className="num">상한</th>
            <th className="num">공칭</th>
            <th>feasible(추정)</th>
            <th>상태</th>
          </tr>
        </thead>
        <tbody>
          {data.beads.map((b) => {
            const ps = data.params.filter((p) => p.bead === b.id);
            if (select && b.kind === "select") {
              const wp = ps.find((p) => p.type === "W");
              const wr = wp ? byName.get(wp.name) : undefined;
              const own = select.blendOf(b.id);
              const R = typeof own === "number" ? own : b.blend_mm;
              const small = !!wp && !!wr?.on && blendSmall(R, select.kBlend, wp.nominal, Number(wr.lo), Number(wr.hi));
              return [
                <tr key={b.id} className="doe-bead-row">
                  <td colSpan={7}>
                    <span className="doe-bead-head">
                      <b>{b.id.toUpperCase()}</b> <span>{b.name}</span>
                      <span className="small mono">
                        단 {b.n_tiers} · W {b.W_nom ?? "–"} ({b.W_min ?? "–"}–{b.W_max ?? "–"}) mm
                      </span>
                      <BlendField bead={b.id} opts={select} readOnly={readOnly} resolved={b.blend_mm} />
                      {small && (
                        <span className="badge warn" data-testid={`blend-small-${b.id}`} title="블렌딩 반경이 폭 이동량에 비해 작습니다 — 품질 실패가 늘 수 있습니다">
                          R 작음
                        </span>
                      )}
                      {(b.warnings ?? []).map((w, i) => (
                        <span key={i} className="badge warn" title={warnText(w)}>
                          ⚠ {warnText(w).split(" — ")[0].slice(0, 24)}
                        </span>
                      ))}
                    </span>
                  </td>
                </tr>,
                ...ps.map((p) => {
                  const r = byName.get(p.name) ?? { name: p.name, on: false, lo: "", hi: "" };
                  const why = rowProblem(p, r);
                  const label = `${b.id.toUpperCase()} ${p.type === "D" ? `D${p.tier ?? ""}` : "W"}`;
                  const on = select.active === p.name;
                  return (
                    <tr key={p.name} className={`${why ? "bad-row " : ""}${on ? "bs-row-on" : ""}`} data-testid={`param-${p.name}`} aria-selected={on} onClick={() => select.onActive(p.name)}>
                      <td>
                        <input type="checkbox" aria-label={`${label} 포함`} checked={r.on} disabled={readOnly} onChange={(e) => upd(p.name, { on: e.target.checked })} />
                      </td>
                      <td>
                        {p.type === "D" ? `깊이 D${p.tier ?? ""}` : "폭 W"} <span className="mono small muted">{p.name}</span>
                        {p.group_members.length > 0 && <span className="small muted" title={`같은 값: ${p.group_members.join(", ")}`}> · 묶음 {[p.name, ...p.group_members].map((n) => n.split("_")[1]).join("+")}</span>}
                      </td>
                      <td className="num">
                        <input type="number" className="doe-num" aria-label={`${label} 하한`} step="any" value={r.lo} disabled={readOnly || !r.on} onChange={(e) => upd(p.name, { lo: e.target.value })} onFocus={() => select.onActive(p.name)} />
                      </td>
                      <td className="num">
                        <input type="number" className="doe-num" aria-label={`${label} 상한`} step="any" value={r.hi} disabled={readOnly || !r.on} onChange={(e) => upd(p.name, { hi: e.target.value })} onFocus={() => select.onActive(p.name)} />
                      </td>
                      <td className="num mono">{p.nominal}</td>
                      <td className="small mono" title="선택에서 추정한 기본 범위 — 미리보기로 확인">
                        {p.feasible[0]}–{p.feasible[1]}
                      </td>
                      <td>{why ? <span className="small error-text">{why}</span> : outsideFeasible(p, r) ? <span className="badge warn" title="추정 범위 밖 — 미리보기에서 실패 안이 늘 수 있습니다(차단 아님)">⚠ 범위 밖</span> : null}</td>
                    </tr>
                  );
                }),
              ];
            }
            const mirrored = !ps.length && data.params.some((p) => p.group_members.some((m) => m.endsWith(`_${b.k}`)));
            return [
              <tr key={b.id} className="doe-bead-row">
                <td colSpan={7}>
                  <span className="doe-bead-head">
                    <BeadPng url={b.png ? beadPngUrl(b.id) : null} id={b.id} />
                    <b>{b.id}</b> <span className="small">{beadText(b)}</span>
                    {b.fixed_overlap && <span className="badge warn">⚠ 고정 겹침(기본 제외)</span>}
                    {mirrored && <span className="small muted">대칭 비드 — 짝 변수와 같이 바뀜</span>}
                    {data.warnings
                      .filter((w) => w.bead === b.id && w.code !== "BEAD_FIXED_OVERLAP")
                      .map((w) => (
                        <span key={w.code} className="badge warn" title={warnText(w)}>
                          ⚠ {w.code === "BEAD_NEAR_FIXED" ? "체결부 가까움" : w.code}
                        </span>
                      ))}
                  </span>
                </td>
              </tr>,
              ...ps.map((p) => {
                const r = byName.get(p.name) ?? { name: p.name, on: false, lo: "", hi: "" };
                const why = rowProblem(p, r);
                const out = !why && outsideFeasible(p, r);
                const label = `${b.id} ${TYPE_NAME[p.type]}`;
                return (
                  <tr key={p.name} className={why ? "bad-row" : undefined} data-testid={`param-${p.name}`}>
                    <td>
                      <input type="checkbox" aria-label={`${label} 포함`} checked={r.on} disabled={readOnly} onChange={(e) => upd(p.name, { on: e.target.checked })} />
                    </td>
                    <td>
                      {TYPE_NAME[p.type]} <span className="mono small muted">{p.name}</span>
                      {p.group_members.length > 0 && <span className="small muted" title={`같이 바뀜: ${p.group_members.join(", ")}`}> · 대칭 {p.group_members.length}</span>}
                      {(p.type === "U" || p.type === "V") && !r.on && <span className="small muted"> (위치 — 기본 제외)</span>}
                    </td>
                    <td className="num">
                      <input type="number" className="doe-num" aria-label={`${label} 하한`} step="any" value={r.lo} disabled={readOnly || !r.on} onChange={(e) => upd(p.name, { lo: e.target.value })} />
                    </td>
                    <td className="num">
                      <input type="number" className="doe-num" aria-label={`${label} 상한`} step="any" value={r.hi} disabled={readOnly || !r.on} onChange={(e) => upd(p.name, { hi: e.target.value })} />
                    </td>
                    <td className="num mono">{p.nominal}</td>
                    <td className="small mono" title={p.feasible_source === "estimate" ? "형상 엔진 추정치 — 미리보기로 확인" : "스윕 확인값"}>
                      {p.feasible[0]}–{p.feasible[1]}
                    </td>
                    <td>
                      {why ? (
                        <span className="small error-text">{why}</span>
                      ) : out ? (
                        <span className="badge warn" data-testid={`outside-${p.name}`} title="feasible(추정) 밖 — 미리보기에서 실패 안이 늘 수 있습니다(차단 아님)">
                          ⚠ 범위 밖
                        </span>
                      ) : null}
                    </td>
                  </tr>
                );
              }),
            ];
          })}
          {data.params
            .filter((p) => !data.beads.some((b) => b.id === p.bead) && !grouped.has(p.name))
            .map((p) => (
              <tr key={p.name}>
                <td colSpan={7} className="small muted">
                  {p.name}(비드 정보 없음)
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

/** DOE 방식·안 수·수준·시드 + 실제 안 수 한 줄 */
export function DoeSpecRow({ st, form, setForm, matrix, matrixError, readOnly, k }: {
  st: DoeSettingsOut;
  form: SpecForm;
  setForm: (f: SpecForm) => void;
  matrix: DoeMatrixOut | null;
  matrixError: string | null;
  readOnly: boolean;
  /** 포함 변수 수 */
  k: number;
}) {
  const ff = form.method === "fullfact";
  return (
    <div className="doe-spec">
      <div className="form-grid tight doe-spec-fields">
        <Field label="방식">
          <select aria-label="DOE 방식" value={form.method} disabled={readOnly} onChange={(e) => setForm({ ...form, method: e.target.value as DoeMethod })}>
            {st.doe.methods.map((m) => (
              <option key={m} value={m}>
                {METHOD_NAME[m] ?? m}
              </option>
            ))}
          </select>
        </Field>
        {ff ? (
          <Field label="수준" hint={k ? `→ ${Number(form.levels) || 0}^${k} = ${(Number(form.levels) || 0) ** k}안` : undefined}>
            <input type="number" aria-label="수준" min={2} max={st.doe.levels_max} value={form.levels} disabled={readOnly} onChange={(e) => setForm({ ...form, levels: e.target.value })} />
          </Field>
        ) : (
          <Field label="안 수">
            <input type="number" aria-label="안 수" min={2} max={st.max_designs - 1} value={form.n} disabled={readOnly} onChange={(e) => setForm({ ...form, n: e.target.value })} />
          </Field>
        )}
        <Field label="시드">
          <input type="number" aria-label="시드" min={0} value={form.seed} disabled={readOnly} onChange={(e) => setForm({ ...form, seed: e.target.value })} />
        </Field>
      </div>
      <div className="small" data-testid="doe-count">
        {matrixError ? (
          <span className="error-text">{matrixError}</span>
        ) : matrix ? (
          <>
            → 실제 <b>{matrix.n_designs}안</b>(공칭 포함, 중복 {matrix.dropped_duplicates}) · 최대 {st.max_designs}안
            {matrix.warnings.map((w, i) => (
              <span key={i} className="warn-text">
                {" "}
                · {warnText(w)}
              </span>
            ))}
          </>
        ) : (
          <span className="muted">안 수 계산 중…</span>
        )}
      </div>
    </div>
  );
}
