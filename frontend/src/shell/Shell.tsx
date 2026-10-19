import type { ReactNode } from "react";
import type { Role } from "../api/types";
import { Link, useLocation } from "react-router-dom";
import { ROLE_LABEL, useApp } from "../app/AppContext";
import { RightPanel } from "./RightPanel";

export interface Crumb {
  label: string;
  to?: string;
}

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
  const libOn = /\/library(\/|$)/.test(loc.pathname);
  return (
    <header className="topbar">
      <Link to="/" className="brand" aria-label="ESL 처음으로">
        <span className="brand-mark">E</span>
        <span className="brand-name">ESL</span>
      </Link>
      <PathBar crumbs={[ROOT_CRUMB, ...crumbs]} />
      {projectId && (
        <nav aria-label="전역 메뉴">
          <Link to={`/p/${projectId}/library`} className={libOn ? "topbar-menu on" : "topbar-menu"} aria-current={libOn ? "page" : undefined}>
            라이브러리
          </Link>
        </nav>
      )}
      <div className="topbar-right">
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

/** 상단 바 + (스텝퍼) + 작업영역 + 우측 패널 */
export function Shell({ crumbs, projectId, stepper, children }: { crumbs: Crumb[]; projectId?: string; stepper?: ReactNode; children: ReactNode }) {
  const { error } = useApp();
  return (
    <div className="page">
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
        <RightPanel />
      </div>
    </div>
  );
}
