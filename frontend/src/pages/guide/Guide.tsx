// 사용 가이드(계약 esl_p3_ux.md §4): 대시보드 HelpCenter 와 같은 형식 — 작업별 단계 카드 + 해당 화면 바로가기.
// 프로젝트·Case 가 필요한 바로가기는 이 브라우저에서 마지막으로 연 Case(없으면 첫 프로젝트)로 채운다.
import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { useApp } from "../../app/AppContext";
import { Shell, UPDATES_PATH } from "../../shell/Shell";
import { recentCase } from "../../lib/recent";
import { FAQ, GUIDE, GUIDE_FLOW, type GuideTarget } from "./content";

function useResolve() {
  const { projects } = useApp();
  const rc = recentCase();
  const pid = rc?.projectId ?? projects[0]?.id ?? null;
  return (t: GuideTarget): { to: string | null; note?: string } => {
    switch (t.kind) {
      case "updates":
        return { to: UPDATES_PATH };
      case "none":
        return { to: null };
      case "stage":
        if (rc) return { to: `/p/${rc.projectId}/c/${rc.caseId}/stage/${t.n}`, note: rc.title };
        return { to: pid ? `/p/${pid}` : null, note: "Case를 먼저 여세요" };
    }
    if (!pid) return { to: null, note: "프로젝트를 먼저 고르세요" };
    if (t.kind === "cases") return { to: `/p/${pid}` };
    if (t.kind === "new") return { to: `/p/${pid}/cases/new${t.tab ? `?tab=${t.tab}` : ""}` };
    if (t.kind === "library") return { to: `/p/${pid}/library` };
    if (t.kind === "analysisNew") return { to: `/p/${pid}/library/analyses/new` };
    return { to: `/p/${pid}/library/comparisons/new` };
  };
}

export function Guide() {
  const resolve = useResolve();
  const loc = useLocation();
  useEffect(() => {
    const id = loc.hash.replace(/^#/, "");
    if (id) document.getElementById(id)?.scrollIntoView?.({ block: "start" });
  }, [loc.hash]);
  let k = 0;
  return (
    <Shell crumbs={[{ label: "사용 가이드" }]}>
      <section className="guide" aria-label="사용 가이드">
        <header className="guide-head">
          <span className="eyebrow">사용 가이드</span>
          <h1 className="page-title">등가정적하중(ESL) 사용 가이드</h1>
          <p className="muted">하려는 작업을 기준으로 단계와 판단 기준을 안내합니다. 카드 아래 버튼으로 해당 화면을 바로 엽니다.</p>
        </header>
        <div className="guide-flow" aria-label="전체 흐름">
          <strong>전체 흐름</strong>
          <div>
            {GUIDE_FLOW.map((f, i) => (
              <span key={f}>
                {i > 0 && <b aria-hidden="true">→</b>}
                <span className="flow-step">{f}</span>
              </span>
            ))}
          </div>
          <p className="small muted">결과는 모두 Case 폴더 하나에 단계별로 쌓입니다. 앞 단계를 바꾸면 뒤 단계를 다시 실행합니다.</p>
        </div>
        {GUIDE.map((g) => (
          <section key={g.id} className="guide-group" aria-labelledby={`g-${g.id}`}>
            <h2 id={`g-${g.id}`}>{g.title}</h2>
            <div className="guide-cards">
              {g.cards.map((c) => {
                k += 1;
                const r = resolve(c.target);
                return (
                  <article key={c.id} id={c.id} className="guide-card" aria-labelledby={`h-${c.id}`}>
                    <span className="guide-no">{String(k).padStart(2, "0")}</span>
                    <h3 id={`h-${c.id}`}>{c.title}</h3>
                    <p className="guide-what">{c.what}</p>
                    <ol>
                      {c.steps.map((s) => (
                        <li key={s}>{s}</li>
                      ))}
                    </ol>
                    {c.check && (
                      <div className="guide-check">
                        <strong>판단 기준</strong>
                        <ul>
                          {c.check.map((s) => (
                            <li key={s}>{s}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {c.tip && <p className="guide-tip small">{c.tip}</p>}
                    <div className="guide-go">
                      {r.to ? (
                        <Link className="btn small" to={r.to}>
                          {c.label}
                        </Link>
                      ) : (
                        <button type="button" className="btn small" disabled>
                          {c.label}
                        </button>
                      )}
                      {r.note && <span className="small muted ellipsis">{r.note}</span>}
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        ))}
        <section className="guide-group" aria-labelledby="g-faq" id="faq">
          <h2 id="g-faq">자주 묻는 질문</h2>
          <div className="faq">
            {FAQ.map((f) => (
              <details key={f.q} className="card">
                <summary>{f.q}</summary>
                <div className="card-body small">{f.a}</div>
              </details>
            ))}
          </div>
        </section>
        <aside className="guide-aside small">
          새 기능과 고친 점은 상단 바 버전을 누르면 나오는 <Link to={UPDATES_PATH}>업데이트 내역</Link>에 있습니다. 같은 내용 문서: 저장소 docs/manual/user.md
        </aside>
      </section>
    </Shell>
  );
}
