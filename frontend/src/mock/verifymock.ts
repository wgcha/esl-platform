// 목 서버 v0.12.0 Radioss 검증 낙하(계약 esl_scx_relay.md §3 SR-D-10·11·15·16, §7·§7.1·§8·§9.2·§9.3 — 기능 B).
// 서버(backend esl_platform/api/schemas.py Verify*·openapi_p1b.json)와 같은 응답 형태·오류 코드를 따른다.
// 작업: VERIFY_DROP(XFER: VD_PREP → VD_STAGE → VD_SUBMIT → VD_WAIT → VD_FETCH) 끝에 VERIFY_POST(SLOT) 큐, 끝나면 비교 결과.
import type {
  DoeResultOut, DoeScenario, EntryOut, JobOut, ScxAvail, StepOut, VerifyCompare, VerifyCompareRow, VerifyDropOut, VerifyExcludedOut, VerifyPlanOut, VerifySceneOut, VerifySubmissionOut,
} from "../api/types";

interface MockResponse {
  status: number;
  body?: unknown;
}
const err = (status: number, code: string, message: string, extra: Record<string, unknown> = {}): MockResponse => ({
  status,
  body: { detail: { code, message, ...extra } },
});
const ok = (body: unknown, status = 200): MockResponse => ({ status, body });

export interface VerifyStudyView {
  project_id: string;
  scenario: DoeScenario;
  phase: string;
  entry_ids: string[];
  result: DoeResultOut | null;
}
interface Ctx {
  study: (id: string) => VerifyStudyView | null;
  entries: () => EntryOut[];
  canRun: (pid: string) => boolean;
  avail: (pid: string) => ScxAvail;
  newJob: (pid: string, jt: "VERIFY_DROP" | "VERIFY_POST", params: Record<string, unknown>) => JobOut;
  jobs: () => JobOut[];
  log: (jobId: string, line: string) => void;
  now: () => string;
  userName: () => string;
}
type Drop = Omit<VerifyDropOut, "job_ids" | "job"> & { attempt: number };
/** 목 계산용: r_c 가 늘 있음 */
type Scene = VerifySceneOut & { r_c: number };
const sub = (request_id: string, state: VerifySubmissionOut["state"], attempt: number, error_code: string | null = null, error_message: string | null = null): VerifySubmissionOut => ({ request_id, state, attempt, error_code, error_message });

const TERMINAL = ["DONE", "FAILED", "CANCELED"];
const JOB_TERMINAL = ["SUCCEEDED", "FAILED", "INTERRUPTED", "CANCELED"];
const HPC_VERSION = /^\d{2,4}(\.\d{1,3}){0,2}$/;
const MB = 1024 ** 2;

export class VerifyMock {
  /** 목 설정 verify_drop.* · paicad.keep_files_top · hpc.scx.* */
  maxScenes = 5;
  defaultN = 3;
  estHours = 3;
  keepTop = 3;
  hpcDefault = { version: "26.1", ncpu: 16 };
  sameTol = 0.02;
  /** include 그래프에 상태 파일(.sta·.str)이 있는 Case(목) — 누적 씬 제외(SR-D-15) */
  stateCases = new Set<string>(["c-lib-2"]);
  /** 원 Case 추출 결과가 없는 Case(목) — VD_CASE_NOT_READY 제외 */
  notReadyCases = new Set<string>();
  /** 다음 VD_SUBMIT 결과를 UNKNOWN 으로(시험·시연) */
  unknownNext = false;
  /** 목 SCX 잡 ID 가 실제로 있는지(resolve attach 404 시험) */
  scxJobs = new Set<string>(["SCX-26-4410"]);
  drops: Drop[] = [];
  /** 시험: 마지막 POST /verify-drops(/plan) 본문 · 마지막 POST /verify-drops(제출) 본문 */
  lastIn: Record<string, unknown> | null = null;
  lastCreateIn: Record<string, unknown> | null = null;
  private seq = 0;
  private scxSeq = 4410;

  constructor(private ctx: Ctx) {}

  private id(prefix: string) {
    this.seq += 1;
    return `${prefix}-${700 + this.seq}`;
  }

  private jobsOf(id: string) {
    return this.ctx.jobs().filter((j) => j.params.verify_drop_id === id);
  }

  /** 마지막 작업 상태 → phase(취소·실패), job_ids */
  out(d: Drop): VerifyDropOut {
    const js = this.jobsOf(d.id);
    const last = js[js.length - 1];
    if (last && !TERMINAL.includes(d.phase)) {
      if (last.state === "CANCELED") d.phase = "CANCELED";
      else if (last.state === "FAILED" || last.state === "INTERRUPTED") d.phase = "FAILED";
    }
    const { attempt: _a, ...rest } = d;
    return { ...rest, job_ids: js.map((j) => j.id), job: last ?? null };
  }

  private activeFor(studyId: string, design: string, caseId: string) {
    return this.drops.some((d) => d.bead_doe_id === studyId && d.design_id === design && d.case_id === caseId && !TERMINAL.includes(this.out(d).phase));
  }

  /** 검사 + 씬 선택(SR-D-10·15). plan·create 공용 */
  private planOf(b: Record<string, unknown>): { plan: VerifyPlanOut; pid: string } | MockResponse {
    this.lastIn = b;
    const st = this.ctx.study(String(b.bead_doe_id ?? ""));
    if (!st) return err(404, "DOE_NOT_FOUND", "강성 평가 스터디를 찾을 수 없습니다.");
    if (!this.ctx.canRun(st.project_id)) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
    const av = this.ctx.avail(st.project_id);
    if (!av.enabled) return err(503, "SCX_UNAVAILABLE", av.reason ?? "SCX 를 쓸 수 없습니다", { reason_code: av.reason_code });
    if (st.scenario !== "same") return err(422, "VD_SCENARIO_UNSUPPORTED", "검증 낙하는 ① 같은 모델 스터디만 됩니다(②③ 은 원 모델에 다른 형상을 넣을 수 없음)");
    if (st.phase !== "DONE" || !st.result) return err(409, "RESULT_NOT_READY", "스터디 결과가 아직 없습니다");
    const designs = st.result.ranking.filter((r) => r.rank <= this.keepTop).map((r) => ({ id: r.id, rank: r.rank }));
    const design = String(b.design_id ?? "");
    const row = st.result.ranking.find((r) => r.id === design);
    if (!row || !designs.some((d) => d.id === design)) return err(422, "VD_DESIGN_NO_FILES", `안 ${design} 은 모핑 사본(best/)이 없습니다 — 순위 1~${this.keepTop} 안만`);
    const mode = b.mode;
    if (mode !== "worst" && mode !== "all") return err(422, "INVALID_PARAMS", "씬 선택 방식이 올바르지 않습니다");
    const n = b.n === undefined || b.n === null ? this.defaultN : Number(b.n);
    if (mode === "worst" && !(Number.isInteger(n) && n >= 1)) return err(422, "INVALID_PARAMS", "N 은 1 이상 정수입니다");
    if (mode === "worst" && n > this.maxScenes) return err(422, "VD_TOO_MANY_SCENES", `씬은 한 번에 최대 ${this.maxScenes}개입니다`, { max_scenes: this.maxScenes });
    const hpc = (b.hpc ?? {}) as { version?: unknown; ncpu?: unknown };
    if (hpc.version != null && hpc.version !== "" && !HPC_VERSION.test(String(hpc.version))) return err(422, "INVALID_PARAMS", "Radioss 버전 형식이 올바르지 않습니다(예 26.1)");
    if (hpc.ncpu != null && !(Number.isInteger(hpc.ncpu) && (hpc.ncpu as number) >= 1 && (hpc.ncpu as number) <= 4096)) return err(422, "INVALID_PARAMS", "ncpu 는 1~4096 정수입니다");
    const es = this.ctx.entries();
    const excluded: VerifyExcludedOut[] = [];
    const byCase = new Map<string, Scene>();
    for (const eid of st.entry_ids) {
      const e = es.find((x) => x.id === eid);
      const p = row.per_esl?.find((x) => x.entry_id === eid);
      if (!e || !p) {
        if (!e) return err(422, "VD_ENTRY_NOT_IN_STUDY", "스터디에 없는 ESL 입니다");
        continue;
      }
      if (this.stateCases.has(e.case_id)) {
        excluded.push({ entry_id: eid, case_id: e.case_id, case_title: e.case_title ?? null, code: "VD_CUMULATIVE_EXCLUDED", reason: "이전 런 상태를 쓰는 누적 씬은 검증 낙하 대상이 아닙니다 — 연쇄 실행은 후속" });
        continue;
      }
      if (this.activeFor(String(b.bead_doe_id), design, e.case_id)) {
        excluded.push({ entry_id: eid, case_id: e.case_id, case_title: e.case_title ?? null, code: "VD_ALREADY_ACTIVE", reason: "같은 안·씬의 검증 낙하가 진행 중입니다" });
        continue;
      }
      if (this.notReadyCases.has(e.case_id)) {
        excluded.push({ entry_id: eid, case_id: e.case_id, case_title: e.case_title ?? null, code: "VD_CASE_NOT_READY", reason: "원 Case 의 추출 결과(01_extract)가 없어 비교할 수 없습니다 — Case 추출을 먼저 끝내세요" });
        continue;
      }
      const sc: Scene = { entry_id: eid, case_id: e.case_id, case_title: e.case_title ?? e.case_id, label: `${e.case_title ?? e.case_id} · ${eid}`, r_c: p.ratio, r_umax: +(p.ratio ** 0.9).toFixed(4), r_epsmax: +(p.ratio ** 0.7).toFixed(4) };
      const cur = byCase.get(e.case_id);
      if (!cur || sc.r_c > cur.r_c) byCase.set(e.case_id, sc);
    }
    const all = [...byCase.values()].sort((x, y) => y.r_c - x.r_c || x.entry_id.localeCompare(y.entry_id));
    const scenes = mode === "worst" ? all.slice(0, n) : all;
    if (mode === "all" && scenes.length > this.maxScenes)
      return err(422, "VD_TOO_MANY_SCENES", `고른 ESL 씬 ${scenes.length}개 — 한 번에 최대 ${this.maxScenes}개입니다('가장 나쁜 씬 N개'로)`, { max_scenes: this.maxScenes, n: scenes.length });
    if (!scenes.length) return err(409, "VD_NO_SCENES", "검증 낙하할 씬이 없습니다 — 고른 ESL 이 모두 누적 씬이거나 진행 중입니다", { excluded });
    return {
      pid: st.project_id,
      plan: {
        design_id: design, mode, scenes, excluded, n_submit: scenes.length, est_hours: this.estHours, max_scenes: this.maxScenes,
        default_worst_n: this.defaultN, default_n: this.defaultN, designs, hpc: { ...this.hpcDefault }, hpc_default: { ...this.hpcDefault },
      },
    };
  }

  handle(method: string, path: string, query: URLSearchParams, b: Record<string, unknown>): MockResponse | null {
    if (!path.startsWith("/verify-drops")) return null;
    let r: RegExpMatchArray | null;
    if (method === "POST" && path === "/verify-drops/plan") {
      const p = this.planOf(b);
      return "plan" in p ? ok(p.plan) : p;
    }
    if (method === "POST" && path === "/verify-drops") {
      this.lastCreateIn = b;
      const p = this.planOf(b);
      if (!("plan" in p)) return p;
      const batch = this.id("vb");
      const hpc = (b.hpc ?? {}) as Record<string, unknown>;
      const drops = p.plan.scenes.map((sc) => {
        const d: Drop = {
          id: this.id("vd"),
          batch_id: batch,
          project_id: p.pid,
          bead_doe_id: String(b.bead_doe_id),
          design_id: String(b.design_id),
          case_id: sc.case_id,
          case_title: sc.case_title,
          entry_id: sc.entry_id,
          title: (b.title as string) ?? null,
          phase: "PREP",
          version: 1,
          drive_dir_display: null,
          scx_job_id: null,
          scx_status: null,
          submission: null,
          files_n: 0,
          files_bytes: 0,
          predicted: { r_umax: sc.r_umax, r_epsmax: sc.r_epsmax, r_c: sc.r_c },
          result: null,
          created_by_name: this.ctx.userName(),
          created_at: this.ctx.now(),
          updated_at: this.ctx.now(),
          attempt: 1,
        };
        this.drops.push(d);
        this.ctx.newJob(p.pid, "VERIFY_DROP", { verify_drop_id: d.id, hpc });
        return this.out(d);
      });
      return ok({ batch_id: batch, drops, excluded: p.plan.excluded }, 201);
    }
    if (method === "GET" && path === "/verify-drops") {
      const sid = query.get("bead_doe_id") ?? "";
      return ok(this.drops.filter((d) => d.bead_doe_id === sid).sort((x, y) => y.created_at.localeCompare(x.created_at) || y.id.localeCompare(x.id)).map((d) => this.out(d)));
    }
    if ((r = path.match(/^\/verify-drops\/([^/]+)(\/resolve|\/compare\.csv)?$/))) {
      const d = this.drops.find((x) => x.id === r![1]);
      if (!d) return err(404, "VD_NOT_FOUND", "검증 낙하를 찾을 수 없습니다");
      if (method === "GET" && !r[2]) return ok(this.out(d));
      if (method === "GET" && r[2] === "/compare.csv") {
        if (!d.result) return err(409, "RESULT_NOT_READY", "비교 결과가 아직 없습니다");
        const head = "key,label,orig,verify,ratio,predicted,verdict,agree";
        return ok([head, ...d.result.rows.map((x) => [x.key, `"${x.label}"`, x.orig, x.verify, x.ratio, x.predicted ?? "", x.verdict, x.agree ?? ""].join(","))].join("\n") + "\n");
      }
      if (method === "POST" && r[2] === "/resolve") {
        if (!this.ctx.canRun(d.project_id)) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
        if (b.version !== d.version) return err(409, "VERSION_CONFLICT", "다른 사용자가 먼저 바꿨습니다. 새로고침하세요.");
        if (d.submission?.state !== "UNKNOWN") return err(409, "VD_NOT_UNKNOWN", "결과 모름 상태가 아닙니다");
        const action = b.action === "link" ? "attach" : b.action; // 서버: link = attach
        if (action === "attach") {
          const sj = String(b.scx_job_id ?? "").trim();
          if (!sj || !this.scxJobs.has(sj)) return err(404, "SCX_JOB_NOT_FOUND", "SCX 에 그 잡 ID 가 없습니다");
          if (this.drops.some((x) => x !== d && x.scx_job_id === sj)) return err(409, "SCX_JOB_ID_IN_USE", "다른 검증 낙하에 연결된 잡 ID 입니다");
          if (this.jobsOf(d.id).some((j) => !JOB_TERMINAL.includes(j.state))) return err(409, "JOB_ACTIVE", "이 검증 낙하의 작업이 대기 중이거나 실행 중입니다");
          d.submission = { ...d.submission, state: "ATTACHED" };
          d.scx_job_id = sj;
          d.scx_status = "Queued";
          d.phase = "SUBMITTED";
          // 서버와 같이: 연결하면 VD_WAIT(폴링)부터 새 VERIFY_DROP 작업을 자동으로 큐([재시도] 불필요)
          const last = [...this.jobsOf(d.id)].reverse().find((j) => j.job_type === "VERIFY_DROP");
          if (last) {
            const nj = this.ctx.newJob(d.project_id, "VERIFY_DROP", { ...last.params });
            nj.retry_of_job_id = last.id;
            nj.resume_from_step = 4;
            for (const st of nj.steps ?? []) if (st.step_no < 4) Object.assign(st, { state: "SUCCEEDED", progress_pct: 100 });
          }
        } else if (action === "abandon") {
          d.submission = { ...d.submission, state: "ABANDONED" };
          d.scx_status = null;
          d.attempt += 1;
        } else return err(422, "INVALID_PARAMS", "action 은 attach·link·abandon 입니다");
        d.version += 1;
        d.updated_at = this.ctx.now();
        return ok(this.out(d));
      }
    }
    return null;
  }

  /** 재시도 409(결과 모름 미정리) — server /jobs/{id}/retry 앞 */
  retryBlocked(j: JobOut): MockResponse | null {
    const d = this.drops.find((x) => x.id === j.params.verify_drop_id);
    if (d?.submission?.state === "UNKNOWN") return err(409, "SCX_SUBMISSION_UNKNOWN", "제출 결과를 알 수 없습니다. SCX 화면에서 잡을 확인한 뒤 [잡 ID 연결] 또는 [포기]를 고르세요");
    return null;
  }
  onRetry(nj: JobOut) {
    const d = this.drops.find((x) => x.id === nj.params.verify_drop_id);
    if (!d) return;
    d.phase = nj.job_type === "VERIFY_POST" ? "POST" : d.scx_job_id ? "SUBMITTED" : "PREP";
    d.version += 1;
  }

  /** 워커 1틱. step 진행 + phase 갱신 */
  advance(j: JobOut, step: StepOut): "running" | "step_done" | "failed" {
    const d = this.drops.find((x) => x.id === j.params.verify_drop_id);
    if (!d) return "step_done";
    const inc = (p: number) => {
      step.progress_pct = Math.min(100, (step.progress_pct ?? 0) + p);
      return step.progress_pct >= 100 ? "step_done" : "running";
    };
    const set = (ph: Drop["phase"]) => {
      if (d.phase !== ph) {
        d.phase = ph;
        d.version += 1;
        d.updated_at = this.ctx.now();
      }
    };
    let res: "running" | "step_done" | "failed";
    switch (step.step_key) {
      case "VD_PREP":
        set("PREP");
        j.progress_label = "파일 세트·노드 좌표 패치";
        if (!d.files_n) {
          d.files_n = 7;
          d.files_bytes = Math.round(186.4 * MB);
        }
        res = inc(100);
        break;
      case "VD_STAGE":
        set("STAGING");
        if (!d.drive_dir_display) d.drive_dir_display = `/Users/vd.dashboard/esl/body/VD${d.id.split("-").pop()}_20261030T091200`;
        res = inc(50);
        j.progress_label = `올리는 중 ${Math.round(((step.progress_pct ?? 0) / 100) * d.files_n)} / ${d.files_n} 파일`;
        break;
      case "VD_SUBMIT": {
        const rid = `esl-vd-${d.id}-a${d.attempt}`;
        j.progress_label = "Radioss 제출";
        if (d.scx_job_id) {
          res = inc(100);
          break;
        }
        if (this.unknownNext) {
          this.unknownNext = false;
          d.submission = sub(rid, "UNKNOWN", d.attempt, "SCX_SUBMISSION_UNKNOWN", "제출 응답을 받지 못했습니다");
          d.version += 1;
          return this.fail(j, step, "SCX_SUBMISSION_UNKNOWN", "제출 결과를 알 수 없습니다. SCX 화면에서 잡을 확인한 뒤 [잡 ID 연결] 또는 [포기]를 고르세요");
        }
        this.scxSeq += 1;
        d.scx_job_id = `SCX-26-${this.scxSeq}`;
        this.scxJobs.add(d.scx_job_id);
        d.submission = sub(rid, "SUBMITTED", d.attempt);
        d.scx_status = "Queued";
        set("SUBMITTED");
        res = inc(100);
        break;
      }
      case "VD_WAIT":
        res = inc(25);
        if ((step.progress_pct ?? 0) < 50) {
          d.scx_status = "Queued";
          set("SUBMITTED");
          j.progress_label = "SCX 대기 Queued";
        } else {
          d.scx_status = (step.progress_pct ?? 0) >= 100 ? "Completed" : "Running";
          set("RUNNING");
          j.progress_label = `SCX ${d.scx_status}`;
        }
        break;
      case "VD_FETCH":
        set("FETCHED");
        res = inc(50);
        j.progress_label = `h3d ${(((step.progress_pct ?? 0) / 100) * 21.6).toFixed(1)} / 21.6 GB`;
        break;
      default:
        set("POST");
        j.progress_label = null;
        res = inc(step.step_key === "H3D_EXTRACT" ? 50 : 100);
    }
    this.ctx.log(j.id, `  ${step.step_key}: ${step.progress_pct}%${j.progress_label ? ` — ${j.progress_label}` : ""}`);
    return res;
  }

  private fail(j: JobOut, step: StepOut, code: string, message: string): "failed" {
    step.state = "FAILED";
    step.failure_code = code;
    j.state = "FAILED";
    j.failure_code = code;
    j.failure_message = message;
    j.progress_label = null;
    j.finished_at = this.ctx.now();
    this.ctx.log(j.id, `  ${step.step_key}: ${code} — ${message}`);
    this.ctx.log(j.id, "작업 종료: FAILED");
    return "failed";
  }

  /** 작업 SUCCEEDED: VERIFY_DROP → VERIFY_POST 큐(같은 트랜잭션), VERIFY_POST → 비교 결과 */
  finished(j: JobOut) {
    const d = this.drops.find((x) => x.id === j.params.verify_drop_id);
    if (!d) return;
    j.progress_label = null;
    if (j.job_type === "VERIFY_DROP") {
      d.phase = "POST";
      d.scx_status = "Completed";
      d.version += 1;
      this.ctx.newJob(d.project_id, "VERIFY_POST", { verify_drop_id: d.id });
      return;
    }
    d.result = this.compareOf(d);
    d.phase = "DONE";
    d.version += 1;
    d.updated_at = this.ctx.now();
  }

  /** §9.3 목 비교: 검증 비 = 예측 비 근처(결정적), t* 변위 1행은 예측과 반대 방향(일치 '아니오' 시연) */
  compareOf(d: Pick<Drop, "predicted" | "case_id">): VerifyCompare {
    const pe = d.predicted?.r_epsmax ?? 1;
    const pu = d.predicted?.r_umax ?? 1;
    const tol = this.sameTol;
    const verdict = (x: number) => (x < 1 - tol ? "better" : x > 1 + tol ? "worse" : "same") as VerifyCompareRow["verdict"];
    const row = (key: string, label: string, orig: number, ratio: number, predicted: number | null): VerifyCompareRow => {
      const v = verdict(ratio);
      const agree = predicted === null ? null : (ratio - 1) * (predicted - 1) > 0 || (v === "same" && verdict(predicted) === "same");
      return { key, label, orig, verify: +(orig * ratio).toPrecision(5), ratio: +ratio.toFixed(4), predicted: predicted === null ? null : +predicted.toFixed(4), verdict: v, agree };
    };
    const h = d.case_id.length % 3;
    return {
      rows: [
        row("eps_peak", "최대 변형률 ε_eq(시간·요소 최대)", 0.01842, pe * 1.04, pe),
        row("eps_hot", "원 낙하 상위 20요소 ε_eq(평균)", 0.01391, pe * 1.07, pe),
        row("disp_peak", "최대 상대 변위 ‖u_rel‖ (mm)", 6.84, pu * 0.97, pu),
        row("eps_tstar", "t* 시점 최대 ε_eq", 0.01522, pe * 1.02, pe),
        row("disp_tstar", "t* 시점 최대 ‖u_rel‖ (mm)", 5.91, h === 0 ? 1.034 : pu * 1.01, pu),
      ],
      hot: { n: 20, mean_ratio: +(pe * 1.07).toFixed(4), max_ratio: +(pe * 1.21).toFixed(4) },
      warnings: [],
      tstar: { orig_time: 0.0124, verify_time: 0.0125 },
    };
  }

  /** 시연(?demoVerify=1)·시험: 완료 1 + 실행 중 1 + 결과 모름 1(이전 묶음) */
  seedDemo(studyId: string) {
    const st = this.ctx.study(studyId);
    if (!st?.result) return;
    const design = st.result.best?.id ?? st.result.ranking[0]?.id;
    if (!design) return;
    const mk = (caseId: string, batch: string): Drop | null => {
      const e = this.ctx.entries().find((x) => st.entry_ids.includes(x.id) && x.case_id === caseId);
      const p = st.result!.ranking.find((r) => r.id === design)?.per_esl?.find((x) => x.entry_id === e?.id);
      if (!e || !p) return null;
      const d: Drop = {
        id: this.id("vd"), batch_id: batch, project_id: st.project_id, bead_doe_id: studyId, design_id: design, case_id: caseId, case_title: e.case_title ?? null, entry_id: e.id, title: null, phase: "PREP", version: 1,
        drive_dir_display: null, scx_job_id: null, scx_status: null, submission: null, files_n: 0, files_bytes: 0,
        predicted: { r_umax: +(p.ratio ** 0.9).toFixed(4), r_epsmax: +(p.ratio ** 0.7).toFixed(4), r_c: p.ratio },
        result: null, created_by_name: this.ctx.userName(), created_at: this.ctx.now(), updated_at: this.ctx.now(), attempt: 1,
      };
      this.drops.push(d);
      return d;
    };
    const run = (d: Drop, until: string, unknown = false) => {
      const j = this.ctx.newJob(d.project_id, "VERIFY_DROP", { verify_drop_id: d.id });
      j.state = "RUNNING";
      j.started_at = this.ctx.now();
      for (const s of j.steps ?? []) {
        if (s.step_key === until) {
          s.state = "RUNNING";
          j.current_step_no = s.step_no;
          if (unknown) this.unknownNext = true;
          // 한 걸음 진행해 phase·진행 문구를 맞춘다
          const r = this.advance(j, s);
          if (r === "failed") return j;
          if (until === "VD_WAIT") {
            s.progress_pct = 50;
            this.advance(j, s);
            s.progress_pct = 55;
          }
          return j;
        }
        s.state = "SUCCEEDED";
        s.progress_pct = 100;
        this.advance(j, { ...s, progress_pct: 0 });
      }
      return j;
    };
    // 이전 묶음: 결과 모름
    const old = this.id("vb");
    const u = mk("c-lib-3", old);
    if (u) run(u, "VD_SUBMIT", true);
    // 최근 묶음: 완료 + 실행 중
    const b = this.id("vb");
    const a = mk("c-demo", b);
    if (a) {
      const j = run(a, "VD_FETCH");
      j.steps!.forEach((s) => ((s.state = "SUCCEEDED"), (s.progress_pct = 100)));
      j.state = "SUCCEEDED";
      j.progress_pct = 100;
      j.finished_at = this.ctx.now();
      this.finished(j);
      const pj = this.jobsOf(a.id).find((x) => x.job_type === "VERIFY_POST")!;
      pj.steps!.forEach((s) => ((s.state = "SUCCEEDED"), (s.progress_pct = 100)));
      pj.state = "SUCCEEDED";
      pj.progress_pct = 100;
      pj.finished_at = this.ctx.now();
      this.finished(pj);
    }
    const c = mk("c-lib-3", b);
    if (c) run(c, "VD_WAIT");
  }
}
