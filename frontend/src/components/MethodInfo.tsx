// 하중 선정 방법·출처 ⓘ 팝오버(esl_opt_run.md §9.1·§10.4): 요약 2~3줄 + 전략별 한 줄 + 목표 기준 한 줄 + 출처 목록(새 탭).
// 문구·링크는 GET /opt/settings 의 method_sources(원본 resources/opt_method_sources.json) — 프런트는 표시 구성만.
import { useEffect, useRef, useState } from "react";
import type { LoadStrategy, ObjectiveNorm, OptMethodSources } from "../api/types";
import { methodSourcesOk } from "../api/opt";

const STRATS: LoadStrategy[] = ["A", "B", "C"];
const NORMS: ObjectiveNorm[] = ["abs", "rel"];

export function MethodInfo({ src: raw, strategy, norm }: { src: OptMethodSources | null | undefined; strategy?: LoadStrategy | null; norm?: ObjectiveNorm | null }) {
  const [open, setOpen] = useState(false);
  // 자료를 못 읽은 서버({error}) = 버튼 비활성 + 사유 툴팁
  const src = methodSourcesOk(raw) ? raw : null;
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
            <div className="sub-title">하중 선정 전략</div>
            <ul>
              {STRATS.map((k) => (
                <li key={k} className={k === strategy ? "on" : undefined} data-current={k === strategy || undefined}>
                  <b>{k}</b> {src.strategies[k]}
                </li>
              ))}
            </ul>
          </div>
          <div className="method-sec">
            <div className="sub-title">목표 기준</div>
            <ul>
              {NORMS.map((k) => (
                <li key={k} className={k === norm ? "on" : undefined} data-current={k === norm || undefined}>
                  {src.objective_norms[k]}
                </li>
              ))}
            </ul>
          </div>
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
