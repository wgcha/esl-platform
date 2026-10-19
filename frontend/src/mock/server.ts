// 목 서버: fetch 래퍼 수준. 계약 esl_platform_p1b §4 응답 모양을 흉내 낸다. tick()마다 작업 진행.
import type {
  Artifact, Case, EslRun, ExportTarget, Job, JobState, JobType, Me, Metric, StageStatus, SupportSet, Validation,
} from "../api/types";
import {
  CANDIDATE_FRAMES, CORNER_IDS, EXTRACT_SUMMARY, HOTSPOTS, N_NODES, PLANE, PROJECTS, USERS, baseCase, makeEslRun,
  makeForces, makePreview, makeSupportSet, makeTstarMetrics, makeValidation, toXYZ, type MockUserKey,
} from "./data";

interface MockResponse {
  status: number;
  body?: unknown;
}

const STEPS: Record<JobType, string[]> = {
  CASE_EXTRACT: ["RAD_PARSE", "PACK_RESULTS", "TSTAR_SCAN"],
  ESL_SOLVE: ["KABSCH", "ASSEMBLE", "SOLVE", "ESL_REGISTER"],
  VALIDATE: ["VAL_SOLVE", "VAL_COMPARE"],
  EXPORT: ["EXP_RADIOSS", "EXP_FEM", "EXP_CSV"],
};
const STAGE_OF: Record<JobType, number> = { CASE_EXTRACT: 1, ESL_SOLVE: 4, VALIDATE: 5, EXPORT: 6 };

const err = (status: number, code: string, message: string, extra: Record<string, unknown> = {}): MockResponse => ({
  status,
  body: { detail: { code, message, ...extra } },
});

export class MockServer {
  user: MockUserKey;
  cases: Case[] = [];
  jobs: Job[] = [];
  logs: Record<string, string[]> = {};
  supportSets: SupportSet[] = [];
  runs: (EslRun & { inputs: string })[] = [];
  validations: Validation[] = [];
  artifacts: Record<string, Artifact[]> = {};
  tstarMetrics = makeTstarMetrics();
  preview = makePreview();
  seq = 10;
  workerOnline = true;

  constructor(opts: { user?: MockUserKey } = {}) {
    this.user = opts.user ?? "power";
    this.seed();
  }

  get me(): Me {
    return USERS[this.user];
  }

  private id(prefix: string) {
    this.seq += 1;
    return `${prefix}-${this.seq}`;
  }

  private now() {
    return new Date(Date.UTC(2026, 9, 19, 1, 0, this.seq)).toISOString();
  }

  private seed() {
    // 완료 Case
    const a = baseCase("c-demo", "p-body", "후방 충돌 40kph", "rear40");
    this.cases.push(a);
    this.finishExtract(a);
    const ss = makeSupportSet("ss-1", a.id);
    this.supportSets.push(ss);
    a.current_support_set_id = ss.id;
    const run = { ...makeEslRun("run-1", a.id, ss.id, a.tstar!.frame_index, a.tstar!.time), inputs: this.inputsKey(a) };
    this.runs.push(run);
    a.current_esl_run_id = run.id;
    const v = makeValidation("val-1", run.id);
    this.validations.push(v);
    run.latest_validation_id = v.id;
    this.artifacts[a.id] = this.makeArtifacts("exp-1", ["radioss_inc", "fem", "csv"]);

    // stale Case: t*를 바꾼 뒤 ESL 결과가 남아 있음
    const b = baseCase("c-stale", "p-body", "후방 충돌 56kph", "rear56");
    this.cases.push(b);
    this.finishExtract(b);
    const ss2 = makeSupportSet("ss-2", b.id);
    this.supportSets.push(ss2);
    b.current_support_set_id = ss2.id;
    const run2 = { ...makeEslRun("run-2", b.id, ss2.id, 78, 0.078), inputs: this.inputsKey(b) };
    this.runs.push(run2);
    b.current_esl_run_id = run2.id;
    b.tstar = { ...b.tstar!, frame_index: 92, time: 0.092, source: "user" };

    // 새 Case
    this.cases.push(baseCase("c-new", "p-body", "후방 오프셋 충돌", "rear_offset"));
  }

  private inputsKey(c: Case) {
    return `${c.tstar?.metric}:${c.tstar?.frame_index}:${c.current_support_set_id}:${c.part_title}`;
  }

  private finishExtract(c: Case) {
    c.extract_summary = EXTRACT_SUMMARY;
    c.part_id = 10;
    const t = this.tstarMetrics.max_strain.tstar;
    c.tstar = { metric: "max_strain", ...t, source: "auto" };
  }

  private makeArtifacts(exportId: string, targets: ExportTarget[]): Artifact[] {
    const files: [ExportTarget, string, string, number][] = [
      ["radioss_inc", "esl_cload", "esl_cload.inc", 1_482_331],
      ["radioss_inc", "esl_bcs", "esl_bcs.inc", 2_118],
      ["fem", "esl_fem", "esl_force.fem", 31_904_772],
      ["csv", "csv", "f_eq.csv", 402_118],
      ["csv", "csv", "u_rel.csv", 398_511],
      ["csv", "csv", "reactions_321.csv", 311],
      ["csv", "csv", "validation.csv", 1_204],
    ];
    return files
      .filter(([t]) => targets.includes(t))
      .map(([, kind, name, size], k) => ({ id: `${exportId}-a${k}`, kind, rel: `06_export/${exportId}/${name}`, size }));
  }

  private canRun(projectId: string) {
    const me = this.me;
    if (me.is_global_admin) return true;
    const r = me.roles[projectId];
    return r === "power" || r === "admin";
  }

  private activeJob(caseId: string, stage: number) {
    return this.jobs.find((j) => j.case_id === caseId && j.stage === stage && (j.state === "QUEUED" || j.state === "RUNNING"));
  }

  private lastJob(caseId: string, stage: number) {
    return [...this.jobs].reverse().find((j) => j.case_id === caseId && j.stage === stage);
  }

  private currentRun(c: Case) {
    return this.runs.find((r) => r.id === c.current_esl_run_id);
  }

  stageStatus(c: Case): Record<string, StageStatus> {
    const run = this.currentRun(c);
    const runStale = !!run && run.inputs !== this.inputsKey(c);
    const out: Record<string, StageStatus> = {};
    const has: Record<number, boolean> = {
      1: !!c.extract_summary,
      2: !!c.tstar,
      3: !!c.current_support_set_id,
      4: !!run,
      5: !!run?.latest_validation_id,
      6: (this.artifacts[c.id] ?? []).length > 0,
    };
    for (let n = 1; n <= 6; n++) {
      const active = this.activeJob(c.id, n);
      const last = this.lastJob(c.id, n);
      let st: StageStatus = { state: has[n] ? "done" : "none" };
      if (n >= 4 && has[n] && runStale) st = { state: "stale" };
      if (last && (last.state === "FAILED" || last.state === "INTERRUPTED")) st = { state: "failed", job_id: last.id };
      if (active) st = { state: "running", job_id: active.id };
      out[String(n)] = st;
    }
    return out;
  }

  private caseOut(c: Case): Case {
    const run = this.currentRun(c);
    if (run) run.stale = run.inputs !== this.inputsKey(c);
    return { ...c, stage_status: this.stageStatus(c) };
  }

  /** 테스트·스크린샷용: 특정 Case 상태를 직접 바꾼다 */
  findCase(id: string) {
    return this.cases.find((c) => c.id === id);
  }

  handle(method: string, rawPath: string, query: URLSearchParams, body: unknown): MockResponse {
    const path = rawPath.replace(/^\/esl\/api/, "");
    const b = (body ?? {}) as Record<string, unknown>;
    const m = (re: RegExp) => path.match(re);
    let r: RegExpMatchArray | null;

    if (method === "GET" && path === "/health") return { status: 200, body: { status: "ok", version: "mock" } };
    if (method === "GET" && path === "/me") return { status: 200, body: this.me };
    if (method === "GET" && path === "/projects") return { status: 200, body: PROJECTS };
    if (method === "GET" && path === "/status")
      return {
        status: 200,
        body: {
          config: { ok: true, errors: [] },
          worker: { online: this.workerOnline, last_seen_at: this.now(), limiter: null },
          tools: { solver_backend: "cholmod", solver_backends_available: ["cholmod", "superlu"] },
        },
      };
    if (method === "GET" && path === "/queue") {
      const live = this.jobs.filter((j) => j.state === "QUEUED" || j.state === "RUNNING");
      const sum = (j: Job) => ({ ...j, steps: undefined, params: undefined });
      const slot = live.filter((j) => j.lane === "SLOT");
      const light = live.filter((j) => j.lane === "LIGHT");
      return {
        status: 200,
        body: {
          running: slot.find((j) => j.state === "RUNNING") ? sum(slot.find((j) => j.state === "RUNNING")!) : null,
          queued: slot.filter((j) => j.state === "QUEUED").map(sum),
          light: {
            running: light.find((j) => j.state === "RUNNING") ? sum(light.find((j) => j.state === "RUNNING")!) : null,
            queued: light.filter((j) => j.state === "QUEUED").map(sum),
          },
        },
      };
    }
    if (method === "POST" && path === "/paths/inspect") {
      const p = String(b.path ?? "").trim();
      if (!p) return err(422, "PATH_NOT_FOUND", "경로를 입력하세요.");
      if (!/^[A-Za-z]:\\ESL_INPUT\\|^\/data\/esl_input\//i.test(p))
        return err(422, "PATH_OUTSIDE_ROOT", "허용된 입력 폴더(input_roots) 밖의 경로입니다.");
      if (b.purpose === "RAD")
        return {
          status: 200,
          body: {
            normalized_path: p,
            ok: true,
            problems: [],
            parts: [
              { id: 10, title: "chassis_rear", n_elems: 223415 },
              { id: 11, title: "bumper_beam", n_elems: 18220 },
              { id: 12, title: "crash_box_L", n_elems: 6402 },
            ],
            includes: [
              { path: p.replace(/[^\\/]+$/, "inc_mat.inc"), ok: true },
              { path: p.replace(/[^\\/]+$/, "inc_mesh.inc"), ok: true },
            ],
            units_label: "mm·ton·s",
          },
        };
      return {
        status: 200,
        body: {
          normalized_path: p,
          ok: true,
          problems: [],
          done: { ok: true, part_id: 10, part_spec: "chassis_rear", candidate_frames: CANDIDATE_FRAMES, hot_k: 200, warnings: [] },
          n_frames: 126,
          files: ["done.json", "nodes.csv", "elems.csv", "history.csv", "hot_strain.csv", "disp_f0078.csv"],
        },
      };
    }
    if (method === "GET" && path === "/cases") {
      const pid = query.get("project_id");
      return { status: 200, body: this.cases.filter((c) => !pid || c.project_id === pid).map((c) => this.caseOut(c)) };
    }
    if (method === "POST" && path === "/cases") {
      if (!this.canRun(String(b.project_id))) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
      const folder = String(b.folder_name ?? "");
      if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(folder))
        return err(422, "INVALID_FOLDER_NAME", "폴더 이름은 영문·숫자·_·- 만 쓸 수 있습니다.");
      if (this.cases.some((c) => c.folder_name === folder)) return err(409, "FOLDER_EXISTS", "같은 폴더 이름이 이미 있습니다.");
      const c = baseCase(this.id("c"), String(b.project_id), String(b.title || folder), folder);
      c.rad_path = String(b.rad_path);
      c.results_dir = String(b.results_dir);
      c.part_title = String(b.part_title || "chassis_rear");
      this.cases.push(c);
      return { status: 201, body: this.caseOut(c) };
    }
    if ((r = m(/^\/cases\/([^/]+)$/))) {
      const c = this.findCase(r[1]);
      if (!c) return err(404, "CASE_NOT_FOUND", "Case를 찾을 수 없습니다.");
      if (method === "GET") return { status: 200, body: this.caseOut(c) };
      if (method === "PATCH") {
        if (!this.canRun(c.project_id)) return err(403, "FORBIDDEN", "권한이 없습니다.");
        if (b.version !== c.version) return err(409, "VERSION_CONFLICT", "다른 사용자가 먼저 바꿨습니다. 새로고침하세요.");
        if (typeof b.title === "string") c.title = b.title;
        if (typeof b.part_title === "string") c.part_title = b.part_title;
        c.version += 1;
        return { status: 200, body: this.caseOut(c) };
      }
    }
    if ((r = m(/^\/cases\/([^/]+)\/(.+)$/))) {
      const c = this.findCase(r[1]);
      if (!c) return err(404, "CASE_NOT_FOUND", "Case를 찾을 수 없습니다.");
      return this.caseSub(c, method, r[2], b);
    }
    if ((r = m(/^\/jobs\/([^/]+)(\/log)?$/)) && method === "GET") {
      const j = this.jobs.find((x) => x.id === r![1]);
      if (!j) return err(404, "JOB_NOT_FOUND", "작업을 찾을 수 없습니다.");
      if (!r[2]) return { status: 200, body: j };
      const lines = this.logs[j.id] ?? [];
      const cur = Number(query.get("cursor") ?? 0) || 0;
      const terminal = !["QUEUED", "RUNNING"].includes(j.state);
      return { status: 200, body: { lines: lines.slice(cur), next_cursor: String(lines.length), eof: terminal } };
    }
    if ((r = m(/^\/esl-runs\/([^/]+)(\/forces)?$/)) && method === "GET") {
      const run = this.runs.find((x) => x.id === r![1]);
      if (!run) return err(404, "ESL_RUN_NOT_FOUND", "ESL 결과를 찾을 수 없습니다.");
      if (r[2]) return { status: 200, body: { rows: makeForces().slice(0, Number(query.get("top") ?? 50)) } };
      const c = this.findCase(run.case_id)!;
      const { inputs, ...rest } = run;
      return { status: 200, body: { ...rest, stale: inputs !== this.inputsKey(c) } };
    }
    if ((r = m(/^\/validations\/([^/]+)$/)) && method === "GET") {
      const v = this.validations.find((x) => x.id === r![1]);
      if (!v) return err(404, "VALIDATION_NOT_FOUND", "검증 결과를 찾을 수 없습니다.");
      const run = this.runs.find((x) => x.id === v.esl_run_id)!;
      const c = this.findCase(run.case_id)!;
      return { status: 200, body: { ...v, stale: run.inputs !== this.inputsKey(c) } };
    }
    return err(404, "NOT_FOUND", `목 서버에 없는 경로: ${method} ${path}`);
  }

  private caseSub(c: Case, method: string, sub: string, b: Record<string, unknown>): MockResponse {
    const write = method !== "GET";
    if (write && !this.canRun(c.project_id)) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
    if (sub === "tstar" && method === "GET") {
      if (!c.extract_summary) return err(409, "PREREQUISITE_MISSING", "추출을 먼저 실행하세요.", { missing: ["extract"] });
      return { status: 200, body: { selected: c.tstar, metrics: this.tstarMetrics, hotspots: HOTSPOTS } };
    }
    if (sub === "tstar" && method === "PUT") {
      if (b.version !== c.version) return err(409, "VERSION_CONFLICT", "다른 사용자가 먼저 바꿨습니다. 새로고침하세요.");
      const metric = b.metric as Metric;
      const blk = this.tstarMetrics[metric];
      const cand = blk?.candidates.find((x) => x.frame_index === b.frame_index);
      if (!cand) return err(422, "FRAME_NOT_CANDIDATE", "후보 목록에 없는 프레임입니다.");
      c.tstar = { metric, frame_index: cand.frame_index, time: cand.time, elem_id: cand.elem_id, value: cand.value, source: "user" };
      c.version += 1;
      return { status: 200, body: this.caseOut(c) };
    }
    if (sub === "preview" && method === "GET") return { status: 200, body: this.preview };
    if (sub === "support-sets/suggest" && method === "POST") {
      const ids = [CORNER_IDS[0], CORNER_IDS[1], CORNER_IDS[3]];
      return {
        status: 200,
        body: {
          node_ids: ids,
          dofs: ["123", "23", "3"],
          coords: ids.map(toXYZ),
          plane: PLANE,
          corners: CORNER_IDS.map(toXYZ),
        },
      };
    }
    if (sub === "support-sets" && method === "GET")
      return { status: 200, body: this.supportSets.filter((s) => s.case_id === c.id) };
    if (sub === "support-sets" && method === "POST") {
      const ids = (b.node_ids as number[]) ?? [];
      if (ids.length !== 3 || ids.some((x) => !Number.isInteger(x) || x < 1 || x > N_NODES))
        return err(422, "NODE_NOT_IN_PART", "대상 파트에 없는 노드가 있습니다.");
      if (new Set(ids).size < 3) return err(422, "SUPPORT_DEGENERATE", "세 노드가 서로 달라야 합니다.");
      const auto = [CORNER_IDS[0], CORNER_IDS[1], CORNER_IDS[3]];
      const ss: SupportSet = {
        id: this.id("ss"),
        case_id: c.id,
        node_ids: ids,
        dofs: ["123", "23", "3"],
        source: ids.every((x, k) => x === auto[k]) ? "auto" : "user",
        plane: PLANE,
        created_by: this.me.user_id,
        created_at: this.now(),
      };
      this.supportSets.push(ss);
      c.current_support_set_id = ss.id;
      c.version += 1;
      return { status: 201, body: ss };
    }
    if (sub === "artifacts" && method === "GET") return { status: 200, body: this.artifacts[c.id] ?? [] };
    if (sub === "jobs" && method === "POST") {
      const jt = b.job_type as JobType;
      if (!STEPS[jt]) return err(422, "INVALID_JOB_TYPE", "알 수 없는 작업 유형입니다.");
      if (this.jobs.some((j) => j.case_id === c.id && j.job_type === jt && (j.state === "QUEUED" || j.state === "RUNNING")))
        return err(409, "CASE_JOB_BUSY", "같은 작업이 이미 진행 중입니다.");
      const missing: string[] = [];
      if (jt === "ESL_SOLVE") {
        if (!c.tstar) missing.push("tstar");
        if (!c.current_support_set_id) missing.push("support_set");
      }
      if ((jt === "VALIDATE" || jt === "EXPORT") && !c.current_esl_run_id) missing.push("esl_run");
      if (missing.length) return err(409, "PREREQUISITE_MISSING", "앞 단계를 먼저 완료하세요.", { missing });
      const job: Job = {
        id: this.id("j"),
        case_id: c.id,
        case_title: c.title,
        job_type: jt,
        stage: STAGE_OF[jt],
        lane: jt === "EXPORT" ? "LIGHT" : "SLOT",
        state: "QUEUED",
        queue_seq: this.seq,
        created_by_name: this.me.display_name,
        created_at: this.now(),
        started_at: null,
        finished_at: null,
        failure_code: null,
        params: (b.params as Record<string, unknown>) ?? {},
        steps: STEPS[jt].map((k, i) => ({ step_no: i + 1, step_key: k, state: "PENDING", progress_pct: 0, exit_code: null, failure_code: null })),
      };
      this.jobs.push(job);
      this.logs[job.id] = [`[${job.job_type}] 대기열 등록 (#${job.queue_seq})`];
      return { status: 201, body: job };
    }
    return err(404, "NOT_FOUND", `목 서버에 없는 경로: ${method} /cases/${c.id}/${sub}`);
  }

  /** 작업 1단계 진행 */
  tick() {
    for (const lane of ["SLOT", "LIGHT"] as const) {
      const running = this.jobs.find((j) => j.lane === lane && j.state === "RUNNING");
      if (running) {
        this.advance(running);
        continue;
      }
      const next = this.jobs.find((j) => j.lane === lane && j.state === "QUEUED");
      if (next) {
        next.state = "RUNNING";
        next.started_at = this.now();
        next.steps[0].state = "RUNNING";
        this.logs[next.id].push(`작업 시작 — step 1 ${next.steps[0].step_key}`);
      }
    }
  }

  private advance(j: Job) {
    const step = j.steps.find((s) => s.state === "RUNNING");
    if (!step) return;
    step.progress_pct = Math.min(100, (step.progress_pct ?? 0) + 50);
    this.logs[j.id].push(`  ${step.step_key}: ${step.progress_pct}%`);
    if (step.progress_pct < 100) return;
    step.state = "SUCCEEDED";
    step.exit_code = 0;
    const nxt = j.steps.find((s) => s.state === "PENDING");
    if (nxt) {
      nxt.state = "RUNNING";
      this.logs[j.id].push(`step ${nxt.step_no} ${nxt.step_key} 시작`);
      return;
    }
    this.complete(j, "SUCCEEDED");
  }

  private complete(j: Job, state: JobState) {
    j.state = state;
    j.finished_at = this.now();
    this.logs[j.id].push(`작업 종료: ${state}`);
    if (state !== "SUCCEEDED") return;
    const c = this.findCase(j.case_id)!;
    if (j.job_type === "CASE_EXTRACT") this.finishExtract(c);
    if (j.job_type === "ESL_SOLVE") {
      const run = { ...makeEslRun(this.id("run"), c.id, c.current_support_set_id!, c.tstar!.frame_index, c.tstar!.time), inputs: this.inputsKey(c) };
      run.job_id = j.id;
      this.runs.push(run);
      c.current_esl_run_id = run.id;
      this.artifacts[c.id] = [];
    }
    if (j.job_type === "VALIDATE") {
      const run = this.currentRun(c)!;
      const v = { ...makeValidation(this.id("val"), run.id), job_id: j.id };
      this.validations.push(v);
      run.latest_validation_id = v.id;
    }
    if (j.job_type === "EXPORT") {
      this.artifacts[c.id] = this.makeArtifacts(this.id("exp"), ((j.params.targets as ExportTarget[]) ?? []));
    }
    c.version += 1;
  }

  /** 테스트용: 작업 끝까지 진행 */
  drain() {
    for (let k = 0; k < 100 && this.jobs.some((j) => j.state === "QUEUED" || j.state === "RUNNING"); k++) this.tick();
  }
}

export function createMockFetch(server: MockServer, real?: typeof fetch): typeof fetch {
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://mock.local");
    if (!url.pathname.startsWith("/esl/api")) {
      if (real) return real(input, init);
      return new Response("not found", { status: 404 });
    }
    const method = (init?.method ?? "GET").toUpperCase();
    if (method !== "GET") {
      const h = new Headers(init?.headers);
      if (h.get("X-ESL-Request") !== "1")
        return new Response(JSON.stringify({ detail: { code: "CSRF_HEADER_REQUIRED", message: "요청 헤더가 없습니다." } }), { status: 403 });
    }
    if (url.pathname.match(/^\/esl\/api\/artifacts\/[^/]+\/download$/))
      return new Response("mock file\n", { status: 200, headers: { "Content-Type": "application/octet-stream" } });
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    const r = server.handle(method, url.pathname, url.searchParams, body);
    return new Response(r.body === undefined ? null : JSON.stringify(r.body), {
      status: r.status,
      headers: { "Content-Type": "application/json" },
    });
  };
}
