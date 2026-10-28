// 실행 상태(계약 esl_3d_load.md §9): 상단 바 칩 2개(대기열·워커) + 오른쪽 비모달 서랍. 우측 고정 패널(RightPanel) 폐지.
//  - 폴링은 RunStatusProvider 1곳(앱 루트, Shell 바깥): api.queue·api.status 를 POLL_MS 마다. 칩·서랍은 useRunStatus() 만 읽는다.
//  - 서랍 열림 상태는 localStorage["esl.statusDrawer"] = "open"|"closed"(기본 닫힘, 브라우저별). 읽기·쓰기 try/catch — 실패해도 닫힘으로 동작.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../api/endpoints";
import type { JobOut, QueueOut, StatusOut } from "../api/types";
import { useApp } from "../app/AppContext";
import { usePolling } from "../lib/usePolling";
import { DrawerSection } from "../panels/DrawerSection";
import { LightQueueSection, QueuePanel } from "../panels/QueuePanel";
import { WorkerPanel } from "../panels/WorkerPanel";

/** ui.poll_queue_ms 현행값(프런트 상수 유지) */
export const POLL_MS = 5000;
export const DRAWER_KEY = "esl.statusDrawer";
export const DRAWER_ID = "status-drawer";

export function readDrawerOpen(): boolean {
  try {
    return window.localStorage.getItem(DRAWER_KEY) === "open";
  } catch {
    return false;
  }
}
function writeDrawerOpen(open: boolean) {
  try {
    window.localStorage.setItem(DRAWER_KEY, open ? "open" : "closed");
  } catch {
    /* 저장소를 쓸 수 없어도 화면 상태로 동작 */
  }
}

export type DrawerSectionId = "queue" | "worker";

export interface RunStatus {
  queue: QueueOut | null;
  status: StatusOut | null;
  queueError: string | null;
  statusError: string | null;
  open: boolean;
  /** 마지막으로 서랍을 연 칩 — Esc 로 닫을 때 포커스를 돌려준다 */
  opener: DrawerSectionId;
  /** 열 때 스크롤할 구획 */
  target: DrawerSectionId | null;
  toggle: (from: DrawerSectionId) => void;
  close: () => void;
}

const Ctx = createContext<RunStatus>({
  queue: null,
  status: null,
  queueError: null,
  statusError: null,
  open: false,
  opener: "queue",
  target: null,
  toggle: () => undefined,
  close: () => undefined,
});

export const useRunStatus = () => useContext(Ctx);

export function RunStatusProvider({ children }: { children: ReactNode }) {
  const queue = usePolling(api.queue, POLL_MS);
  const status = usePolling(api.status, POLL_MS);
  const [open, setOpen] = useState(readDrawerOpen);
  const [opener, setOpener] = useState<DrawerSectionId>("queue");
  const [target, setTarget] = useState<DrawerSectionId | null>(null);
  const toggle = useCallback(
    (from: DrawerSectionId) => {
      setOpen((o) => {
        const next = !o;
        writeDrawerOpen(next);
        return next;
      });
      setOpener(from);
      setTarget(from === "worker" ? "worker" : null);
    },
    [],
  );
  const close = useCallback(() => {
    setOpen(false);
    writeDrawerOpen(false);
    setTarget(null);
  }, []);
  const value = useMemo<RunStatus>(
    () => ({ queue: queue.data, status: status.data, queueError: queue.error, statusError: status.error, open, opener, target, toggle, close }),
    [queue.data, queue.error, status.data, status.error, open, opener, target, toggle, close],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

// ---------------------------------------------------------------- 칩
export function runningJobs(q: QueueOut | null): JobOut[] {
  return q ? (q.running_all?.length ? q.running_all : q.running ? [q.running] : []) : [];
}

export function queueChipText(rs: Pick<RunStatus, "queue" | "queueError">): string {
  const q = rs.queue;
  if (!q) return rs.queueError ? "대기열 오류" : "대기열 불러오는 중…";
  const running = runningJobs(q).length;
  const light = (q.light.running ? 1 : 0) + q.light.queued.length;
  return `계산 ${running}/${q.slots ?? 1} · 대기 ${q.queued.length}${light > 0 ? ` · 보고서 ${light}` : ""}`;
}

export function workerChipText(rs: Pick<RunStatus, "status" | "statusError">): { text: string; bad: boolean; ok: boolean } {
  const s = rs.status;
  if (!s) return { text: rs.statusError ? "워커 확인 실패" : "워커 확인 중…", bad: !!rs.statusError, ok: false };
  const errs = s.config.ok ? 0 : s.config.errors.length;
  const base = s.worker.online ? `워커 동작 중 · 솔버 ${s.tools.solver_backend}` : "워커 응답 없음";
  return { text: errs ? `${base} · 설정 오류 ${errs}` : base, bad: !s.worker.online || errs > 0, ok: s.worker.online && errs === 0 };
}

export function StatusChips() {
  const rs = useRunStatus();
  const { me } = useApp();
  const q = rs.queue;
  const running = runningJobs(q);
  const mine = !!me && running.some((j) => j.created_by === me.user_id);
  const w = workerChipText(rs);
  const queueTitle = rs.queueError ?? (mine ? "내 작업이 실행 중입니다" : "계산 대기열 — 누르면 실행 상태 서랍을 엽니다");
  return (
    <div className="status-chips" role="group" aria-label="실행 상태 요약">
      <button
        type="button"
        id="chip-queue"
        className={`status-chip queue${running.length ? " running" : ""}${mine ? " mine" : ""}${rs.queueError ? " bad" : ""}`}
        aria-expanded={rs.open}
        aria-controls={DRAWER_ID}
        title={queueTitle}
        data-testid="chip-queue"
        onClick={() => rs.toggle("queue")}
      >
        <span className={`dot ${rs.queueError ? "bad" : running.length ? "run" : "off"}`} aria-hidden="true" />
        {queueChipText(rs)}
      </button>
      <button
        type="button"
        id="chip-worker"
        className={`status-chip worker${w.bad ? " bad" : ""}`}
        aria-expanded={rs.open}
        aria-controls={DRAWER_ID}
        title={rs.statusError ?? (rs.status ? `사용 가능 솔버: ${rs.status.tools.solver_backends_available.join(", ")}` : "워커 상태")}
        data-testid="chip-worker"
        onClick={() => rs.toggle("worker")}
      >
        <span className={`dot ${w.bad ? "bad" : w.ok ? "ok" : "off"}`} aria-hidden="true" />
        {w.text}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------- 서랍
export function StatusDrawer() {
  const rs = useRunStatus();
  const ref = useRef<HTMLElement>(null);
  const workerRef = useRef<HTMLDivElement>(null);
  const { open, target } = rs;
  useEffect(() => {
    if (open && target === "worker") workerRef.current?.scrollIntoView?.({ block: "start" });
  }, [open, target]);
  if (!open) return null;
  return (
    <aside
      id={DRAWER_ID}
      ref={ref}
      className="status-drawer"
      role="complementary"
      aria-label="실행 상태"
      onKeyDown={(e) => {
        if (e.key !== "Escape") return;
        e.stopPropagation();
        rs.close();
        document.getElementById(rs.opener === "worker" ? "chip-worker" : "chip-queue")?.focus();
      }}
    >
      <header className="drawer-head">
        <h2>실행 상태</h2>
        <button type="button" className="btn small ghost" aria-label="실행 상태 닫기" onClick={() => rs.close()}>
          ✕
        </button>
      </header>
      <div className="drawer-body">
        <DrawerSection title="계산 대기열" id="drawer-queue" right={rs.queue ? <QueueSlots /> : undefined}>
          <QueuePanel />
        </DrawerSection>
        <LightQueueSection />
        <div ref={workerRef}>
          <DrawerSection title="워커" id="drawer-worker">
            <WorkerPanel />
          </DrawerSection>
        </div>
      </div>
    </aside>
  );
}

function QueueSlots() {
  const { queue } = useRunStatus();
  if (!queue) return null;
  return (
    <span className="slots-meta" data-testid="queue-slots" title="동시에 실행하는 계산 수(설정 worker.slots)">
      동시 실행 {runningJobs(queue).length}/{queue.slots ?? 1}
    </span>
  );
}
