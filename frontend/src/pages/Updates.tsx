// 업데이트 내역(버전 게시판, 계약 esl_p3_ux.md §3): GET /changelog 버전별 카드(추가·변경·수정). 열면 현재 버전을 '본 것'으로 기록.
import { useEffect } from "react";
import { p3 } from "../api/p3";
import { useApp } from "../app/AppContext";
import { Shell } from "../shell/Shell";
import { Badge, Empty, ErrorLine } from "../components/ui";
import { usePolling } from "../lib/usePolling";
import { SECTIONS, cmpVersion, markVersionSeen } from "../lib/changelog";
import { dt } from "../lib/format";

const SECTION_KIND = { 추가: "ok", 변경: "info", 수정: "warn" } as const;

export function Updates() {
  const { version } = useApp();
  const log = usePolling(p3.changelog, 0);
  useEffect(() => {
    if (version) markVersionSeen(version.version);
  }, [version]);
  return (
    <Shell crumbs={[{ label: "업데이트 내역" }]}>
      <div className="page-title-row">
        <h1 className="page-title">업데이트 내역</h1>
        {version && (
          <span className="muted small" data-testid="current-version">
            지금 버전 v{version.version}
            {version.commit ? ` · ${version.commit}` : ""}
            {version.built_at ? ` · 배포 ${dt(version.built_at)}` : ""}
          </span>
        )}
      </div>
      <ErrorLine text={log.error} />
      {log.data && log.data.length === 0 && <Empty>내역이 없습니다</Empty>}
      <div className="release-list">
        {(log.data ?? []).map((r) => {
          const isCur = !!version && cmpVersion(r.version, version.version) === 0;
          return (
            <article key={r.version} className={isCur ? "release current" : "release"} aria-label={`v${r.version}`}>
              <header className="release-head">
                <h2>v{r.version}</h2>
                {isCur && <Badge kind="info">지금 버전</Badge>}
                <span className="spacer" />
                <span className="muted small">{r.date ?? ""}</span>
              </header>
              {SECTIONS.filter((s) => r.sections[s]?.length).map((s) => (
                <section key={s} className="release-sec">
                  <Badge kind={SECTION_KIND[s]}>{s}</Badge>
                  <ul>
                    {r.sections[s]!.map((it) => (
                      <li key={it}>{it}</li>
                    ))}
                  </ul>
                </section>
              ))}
            </article>
          );
        })}
      </div>
    </Shell>
  );
}
