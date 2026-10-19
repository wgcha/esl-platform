import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ROLE_LABEL, useApp } from "../app/AppContext";
import { RightPanel } from "./RightPanel";

export interface Crumb {
  label: string;
  to?: string;
}

/** 상단 경로바 + (스텝퍼) + 본문 + 우측 패널 */
export function Shell({ crumbs, projectId, stepper, children }: { crumbs: Crumb[]; projectId?: string; stepper?: ReactNode; children: ReactNode }) {
  const { me, error } = useApp();
  const role = me?.is_global_admin ? "전역 관리자" : projectId && me?.roles[projectId] ? ROLE_LABEL[me.roles[projectId]] : null;
  return (
    <div className="app">
      <header className="topbar">
        <nav className="crumbs" aria-label="경로">
          {crumbs.map((c, i) => (
            <span key={i} className="crumb">
              {i > 0 && <span className="sep">›</span>}
              {c.to && i < crumbs.length - 1 ? <Link to={c.to}>{c.label}</Link> : <span aria-current={i === crumbs.length - 1 ? "page" : undefined}>{c.label}</span>}
            </span>
          ))}
        </nav>
        <div className="topbar-right">
          {me && (
            <span className="user" data-testid="user">
              {me.display_name}
              {role && <span className="role">{role}</span>}
            </span>
          )}
          <a className="to-dash" href="/">
            대시보드로
          </a>
        </div>
      </header>
      {error && <div className="banner bad">{error}</div>}
      {stepper}
      <div className="body">
        <main className="main">{children}</main>
        <RightPanel />
      </div>
    </div>
  );
}
