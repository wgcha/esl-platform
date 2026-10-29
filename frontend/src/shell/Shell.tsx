import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import type { Role } from "../api/types";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { DONE_SHOW_MS, uploadPath, uploadStore } from "../lib/uploadStore";
import { ROLE_LABEL, useApp } from "../app/AppContext";
import { StatusChips, StatusDrawer, useRunStatus } from "./RunStatus";
import { SEEN_EVENT, isNewVersion, lastSeenVersion } from "../lib/changelog";
import { dt } from "../lib/format";

export const GUIDE_PATH = "/guide";
export const UPDATES_PATH = "/updates";

/** 상단 바 업로드 진행 표시: 전송 중이면 '업로드 37%'(여러 개면 '업로드 2건 · 45%'), 끝나면 '업로드 완료 — 열기'를 잠깐. 클릭 = 그 업로드(?upload=) 화면 */
export function UploadChip() {
  useSyncExternalStore(uploadStore.subscribe, uploadStore.getVersion);
  const nav = useNavigate();
  const [, tick] = useState(0);
  const c = uploadStore.chip();
  useEffect(() => {
    if (c?.kind !== "done") return;
    const left = Math.max(50, DONE_SHOW_MS - (Date.now() - (c.session.finishedAt ?? 0)));
    const t = setTimeout(() => tick((n) => n + 1), left + 20);
    return () => clearTimeout(t);
  }, [c?.kind, c?.session.finishedAt]);
  if (!c) return null;
  const text = c.kind === "done" ? "업로드 완료 — 열기" : c.n > 1 ? `업로드 ${c.n}건 · ${c.pct}%` : `업로드 ${c.pct}%`;
  return (
    <button type="button" className={`upload-chip ${c.kind}`} data-testid="upload-chip" title="업로드 화면 열기" onClick={() => nav(uploadPath(c.session))}>
      {c.kind === "active" && <span className="upload-chip-bar" style={{ width: `${c.pct}%` }} aria-hidden="true" />}
      <span className="upload-chip-text">{text}</span>
    </button>
  );
}

/** 상단 바 버전 표기: v0.4.0(툴팁 commit·배포 시각) + 마지막으로 본 버전보다 새로우면 점 배지 → 업데이트 내역 */
export function VersionChip() {
  const { version } = useApp();
  const [seen, setSeen] = useState(lastSeenVersion);
  useEffect(() => {
    const on = () => setSeen(lastSeenVersion());
    window.addEventListener(SEEN_EVENT, on);
    return () => window.removeEventListener(SEEN_EVENT, on);
  }, []);
  if (!version) return null;
  const fresh = isNewVersion(version.version, seen);
  const tip = [`commit ${version.commit ?? "–"}`, `배포 ${version.built_at ? dt(version.built_at) : "–"}`].join(" · ");
  return (
    <Link to={UPDATES_PATH} className="version-chip" title={tip} data-testid="version-chip" aria-label={`버전 v${version.version}${fresh ? " (새 버전)" : ""} — 업데이트 내역`}>
      v{version.version}
      {fresh && <span className="new-dot" data-testid="version-new" aria-hidden="true" />}
    </Link>
  );
}

export interface Crumb {
  label: string;
  to?: string;
}

/** v0.10.0 최상단 메뉴 2개(esl_menu_restructure.md §4.1) */
export const MENU_CREATE = "ESL 생성";
export const MENU_LIBRARY = "ESL 라이브러리";
/** 라이브러리 메뉴 활성: /p/:pid/library·/opt·/doe 로 시작. 그 외(케이스 목록·새 케이스·케이스·이력·작업)는 ESL 생성 */
export const isLibraryPath = (pathname: string) => /^\/p\/[^/]+\/(library|opt|doe)(\/|$)/.test(pathname);

/** 앱 첫 경로 조각(PhysicsAI 의 "AI 예측"에 해당) */
export const ROOT_CRUMB: Crumb = { label: "등가정적하중", to: "/" };

export function PathBar({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav className="pathbar" aria-label="경로">
      {crumbs.map((c, i) => (
        <span key={i} className="crumb">
          {i > 0 && <span className="crumb-sep">›</span>}
          {c.to && i < crumbs.length - 1 ? <Link to={c.to}>{c.label}</Link> : <span aria-current={i === crumbs.length - 1 ? "page" : undefined}>{c.label}</span>}
        </span>
      ))}
    </nav>
  );
}

/** 상단 바(PhysicsAI TopBar 와 같은 구조): 브랜드 · 경로 · 대시보드로 · 사용자 */
export function TopBar({ crumbs, projectId }: { crumbs: Crumb[]; projectId?: string }) {
  const { me } = useApp();
  const role = projectId && me ? (me.roles[projectId] as Role | undefined) : undefined;
  const loc = useLocation();
  const libOn = isLibraryPath(loc.pathname);
  return (
    <header className="topbar">
      <Link to="/" className="brand" aria-label="ESL 처음으로">
        <span className="brand-mark">E</span>
        <span className="brand-name">ESL</span>
      </Link>
      <PathBar crumbs={[ROOT_CRUMB, ...crumbs]} />
      {projectId && (
        <nav className="topbar-menus" aria-label="전역 메뉴">
          <Link to={`/p/${projectId}`} className={!libOn ? "topbar-menu on" : "topbar-menu"} aria-current={!libOn ? "page" : undefined}>
            {MENU_CREATE}
          </Link>
          <Link to={`/p/${projectId}/library`} className={libOn ? "topbar-menu on" : "topbar-menu"} aria-current={libOn ? "page" : undefined}>
            {MENU_LIBRARY}
          </Link>
        </nav>
      )}
      <div className="topbar-right">
        <UploadChip />
        <StatusChips />
        <Link className="topbar-link" to={GUIDE_PATH}>
          사용 가이드
        </Link>
        <VersionChip />
        <a className="topbar-link" href="/">
          대시보드로
        </a>
        {me && (
          <span className="user" data-testid="user" title={me.username}>
            <span className="user-name">{me.display_name}</span>
            {me.is_global_admin ? (
              <span className="role-chip admin">전역 관리자</span>
            ) : role ? (
              <span className={`role-chip ${role}`}>{ROLE_LABEL[role] ?? role}</span>
            ) : null}
          </span>
        )}
      </div>
    </header>
  );
}

/** 상단 바(상태 칩 2개) + (스텝퍼) + 작업영역 + 오른쪽 비모달 서랍(열면 본문을 밀어낸다) */
export function Shell({ crumbs, projectId, stepper, children }: { crumbs: Crumb[]; projectId?: string; stepper?: ReactNode; children: ReactNode }) {
  const { error } = useApp();
  const { open } = useRunStatus();
  return (
    <div className={open ? "page drawer-open" : "page"}>
      <TopBar crumbs={crumbs} projectId={projectId} />
      {stepper}
      {error && (
        <div className="warn-box" role="alert">
          {error}
        </div>
      )}
      <div className="workgrid">
        <main className="workarea" aria-label="작업영역">
          {children}
        </main>
      </div>
      <StatusDrawer />
    </div>
  );
}
