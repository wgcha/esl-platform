// v0.19.0 목록 항목 삭제 목 API(계약 esl_item_delete.md §1·§2·§4). MockServer.handle 이 delete-check·DELETE 4종을 여기로 넘긴다.
// can_delete = 실행 권한 + (등록자 또는 전역 관리자), delete_blocked = 비종료 job·검증 낙하·SCX 제출 사유(백엔드 §2 와 같은 규칙).
import type { DeleteBlockOut, DeleteCheckOut, DeleteKind, DeleteOut, JobOut } from "../api/types";
import type { MockServer } from "./server";

interface MockResponse {
  status: number;
  body?: unknown;
}
const err = (status: number, code: string, message: string, extra: Record<string, unknown> = {}): MockResponse => ({ status, body: { detail: { code, message, ...extra } } });
const ok = (body: unknown, status = 200): MockResponse => ({ status, body });

const JOB_DONE = ["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"];
const DROP_DONE = ["DONE", "FAILED", "CANCELED"];
const SCX_ACTIVE = ["SUBMITTING", "SUBMITTED", "UNKNOWN"];
const NOT_FOUND: Record<DeleteKind, [string, string]> = {
  DOE: ["DOE_NOT_FOUND", "강성 평가 스터디를 찾을 수 없습니다."],
  OPT: ["OPT_RUN_NOT_FOUND", "최적화 실행을 찾을 수 없습니다."],
  ANALYSIS: ["ANALYSIS_NOT_FOUND", "분석을 찾을 수 없습니다"],
  COMPARE: ["COMPARISON_NOT_FOUND", "비교를 찾을 수 없습니다"],
};
const ROUTES: [RegExp, DeleteKind][] = [
  [/^\/doe\/studies\/([^/]+?)(\/delete-check)?$/, "DOE"],
  [/^\/opt\/runs\/([^/]+?)(\/delete-check)?$/, "OPT"],
  [/^\/library\/analyses\/([^/]+?)(\/delete-check)?$/, "ANALYSIS"],
  [/^\/library\/comparisons\/([^/]+?)(\/delete-check)?$/, "COMPARE"],
];
const DIR: Record<DeleteKind, string> = { DOE: "_doe", OPT: "_opt", ANALYSIS: "_analysis", COMPARE: "_compare" };

export class ItemDeleteMock {
  /** 시험·시연: 다음 DELETE 를 409 FILE_LOCKED 로(한 번) */
  lockedNext = false;
  /** 삭제된 (kind:id) — 두 번째 DELETE = 404 ITEM_DELETED */
  deleted = new Set<string>();
  /** 시험: 마지막 DELETE 경로 */
  calls: string[] = [];

  constructor(private s: MockServer) {}

  private item(kind: DeleteKind, id: string): { project_id: string; title: string; by: (me: { user_id: string; display_name: string }) => boolean } | null {
    const s = this.s;
    if (kind === "DOE") {
      const r = s.doe.recs.find((x) => x.out.id === id);
      return r ? { project_id: r.out.project_id, title: r.out.title, by: (me) => r.out.created_by_name === me.display_name } : null;
    }
    if (kind === "OPT") {
      const r = s.opt.runs.find((x) => x.id === id);
      return r ? { project_id: r.project_id, title: r.title ?? r.id, by: (me) => r.created_by_name === me.display_name } : null;
    }
    if (kind === "ANALYSIS") {
      const a = s.analyses.find((x) => x.id === id);
      return a ? { project_id: a.project_id, title: a.title ?? a.id, by: (me) => a.created_by === me.user_id } : null;
    }
    const c = s.comparisons.find((x) => x.id === id);
    return c ? { project_id: c.project_id, title: c.title ?? `${c.model} ${c.base_version} → ${c.new_version}`, by: (me) => c.created_by === me.user_id } : null;
  }

  private drops(id: string) {
    return this.s.verify.drops.filter((d) => d.bead_doe_id === id);
  }

  /** 항목의 job(스터디는 검증 낙하 job 포함) */
  private jobsOf(kind: DeleteKind, id: string): JobOut[] {
    const s = this.s;
    const all = [...s.jobs, ...s.doe.seededJobs, ...s.opt.runs.flatMap((r) => (r.seededJob ? [r.seededJob] : []))];
    const uniq = [...new Map(all.map((j) => [j.id, j])).values()];
    if (kind === "DOE") {
      const dropIds = new Set(this.drops(id).map((d) => d.id));
      return uniq.filter((j) => j.params.bead_doe_id === id || (typeof j.params.verify_drop_id === "string" && dropIds.has(j.params.verify_drop_id)));
    }
    if (kind === "OPT") return uniq.filter((j) => (j.opt_run_id ?? j.params.opt_run_id) === id);
    if (kind === "ANALYSIS") return uniq.filter((j) => (j.analysis_id ?? j.params.analysis_id) === id);
    return uniq.filter((j) => (j.comparison_id ?? j.params.comparison_id) === id);
  }

  private blocks(kind: DeleteKind, id: string): DeleteBlockOut[] {
    const out: DeleteBlockOut[] = [];
    for (const j of this.jobsOf(kind, id)) {
      if (!JOB_DONE.includes(j.state)) {
        out.push({ code: "JOB_ACTIVE", message: `진행 중인 작업이 있습니다(${j.job_type} ${j.state === "QUEUED" ? "대기" : "실행"} 중)`, job_id: j.id, job_type: j.job_type, state: j.state, verify_drop_id: typeof j.params.verify_drop_id === "string" ? j.params.verify_drop_id : null });
      }
    }
    if (kind === "DOE") {
      for (const d of this.drops(id)) {
        if (!DROP_DONE.includes(d.phase)) out.push({ code: "VERIFY_DROP_ACTIVE", message: "검증 낙하를 먼저 취소·포기하세요", job_id: null, job_type: null, state: d.phase, verify_drop_id: d.id });
        else if (d.submission && SCX_ACTIVE.includes(d.submission.state)) out.push({ code: "SCX_SUBMISSION_ACTIVE", message: "SCX 제출이 아직 끝나지 않았습니다 — 먼저 취소·포기하세요", job_id: null, job_type: null, state: d.submission.state, verify_drop_id: d.id });
      }
    }
    return out;
  }

  /** 목록 행에 실리는 두 칸 */
  flags(kind: DeleteKind, id: string): { can_delete: boolean; delete_blocked: string | null } {
    const it = this.item(kind, id);
    const me = this.s.me;
    if (!it) return { can_delete: false, delete_blocked: null };
    const can = this.s.canRun(it.project_id) && (me.is_global_admin || it.by(me));
    const b = this.blocks(kind, id);
    return { can_delete: can, delete_blocked: b.length ? b[0].message : null };
  }

  private check(kind: DeleteKind, id: string): DeleteCheckOut {
    const it = this.item(kind, id)!;
    const blocked = this.blocks(kind, id);
    const drops = kind === "DOE" ? this.drops(id) : [];
    return {
      kind,
      id,
      title: it.title,
      can_delete: blocked.length === 0,
      blocked,
      n_jobs: this.jobsOf(kind, id).length,
      n_verify_drops: drops.length,
      n_opt_unlinked: kind === "ANALYSIS" ? this.s.opt.runs.filter((r) => r.analysis_id === id).length : 0,
      folders: [{ rel: `${DIR[kind]}/${id}`, exists: true }, ...drops.map((d) => ({ rel: `_verify/${d.id}`, exists: true }))],
    };
  }

  private remove(kind: DeleteKind, id: string): DeleteOut {
    const s = this.s;
    const c = this.check(kind, id);
    const jobIds = new Set(this.jobsOf(kind, id).map((j) => j.id));
    s.jobs = s.jobs.filter((j) => !jobIds.has(j.id));
    s.doe.seededJobs = s.doe.seededJobs.filter((j) => !jobIds.has(j.id));
    if (kind === "DOE") {
      s.verify.drops = s.verify.drops.filter((d) => d.bead_doe_id !== id);
      s.doe.recs = s.doe.recs.filter((x) => x.out.id !== id);
    } else if (kind === "OPT") s.opt.runs = s.opt.runs.filter((x) => x.id !== id);
    else if (kind === "ANALYSIS") {
      for (const r of s.opt.runs) if (r.analysis_id === id) r.analysis_id = null;
      s.analyses = s.analyses.filter((x) => x.id !== id);
    } else s.comparisons = s.comparisons.filter((x) => x.id !== id);
    this.deleted.add(`${kind}:${id}`);
    return { deleted: true, kind, id, purge: "PENDING", deletion_id: `del-${this.deleted.size}`, n_jobs: c.n_jobs, n_verify_drops: c.n_verify_drops, n_opt_unlinked: c.n_opt_unlinked };
  }

  handle(method: string, path: string): MockResponse | null {
    for (const [re, kind] of ROUTES) {
      const m = path.match(re);
      if (!m) continue;
      const isCheck = !!m[2];
      if (!((method === "GET" && isCheck) || (method === "DELETE" && !isCheck))) return null;
      const id = m[1];
      if (!this.item(kind, id)) {
        if (this.deleted.has(`${kind}:${id}`)) return err(404, "ITEM_DELETED", "이미 삭제된 항목입니다.");
        return err(404, ...NOT_FOUND[kind]);
      }
      const f = this.flags(kind, id);
      if (!f.can_delete) return err(403, "NOT_ITEM_OWNER", "등록자 또는 관리자만 삭제할 수 있습니다.");
      if (isCheck) return ok(this.check(kind, id));
      this.calls.push(`DELETE ${path}`);
      const blocked = this.blocks(kind, id);
      if (blocked.length) return err(409, "ITEM_BUSY", "진행 중인 작업이 있어 삭제할 수 없습니다.", { details: { blocked } });
      if (this.lockedNext) {
        this.lockedNext = false;
        return err(409, "FILE_LOCKED", "폴더를 옮기지 못했습니다(파일이 열려 있음).", { details: { path: `…/${DIR[kind]}/${id.slice(0, 8)}` } });
      }
      return ok(this.remove(kind, id));
    }
    return null;
  }
}
