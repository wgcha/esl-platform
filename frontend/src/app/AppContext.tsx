import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "../api/endpoints";
import { errorText } from "../api/client";
import { p3 } from "../api/p3";
import type { Me, Project, Role, VersionOut } from "../api/types";

interface AppState {
  me: Me | null;
  projects: Project[];
  error: string | null;
  /** GET /version(실패해도 앱은 동작) */
  version: VersionOut | null;
}

const Ctx = createContext<AppState>({ me: null, projects: [], error: null, version: null });

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AppState>({ me: null, projects: [], error: null, version: null });
  useEffect(() => {
    let alive = true;
    Promise.all([api.me(), api.projects()])
      .then(([me, projects]) => alive && setState((s) => ({ ...s, me, projects, error: null })))
      .catch((e) => alive && setState((s) => ({ ...s, error: errorText(e) })));
    p3.version()
      .then((version) => alive && setState((s) => ({ ...s, version })))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);
  return <Ctx.Provider value={state}>{children}</Ctx.Provider>;
}

export const useApp = () => useContext(Ctx);

export const ROLE_LABEL: Record<Role, string> = { general: "조회", power: "실행", admin: "관리" };

/** 실행 권한 = 해당 project power 이상 또는 전역 관리자 (esl.md §5) */
export function canRun(me: Me | null, projectId: string | undefined) {
  if (!me || !projectId) return false;
  if (me.is_global_admin) return true;
  const r = me.roles[projectId];
  return r === "power" || r === "admin";
}

export const NO_PERMISSION = "실행 권한이 없습니다 — 이 프로젝트의 '실행(power)' 이상 역할이 필요합니다";
