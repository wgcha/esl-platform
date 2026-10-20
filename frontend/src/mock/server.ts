// 목 서버: fetch 래퍼 수준. 백엔드 실제 응답 모양(openapi_p1b.json + 자유 형식 응답은 서비스 코드)을 흉내 낸다.
// tick()마다 작업이 한 걸음 진행된다.
import type {
  AnalysisCreate, AnalysisFilters, AnalysisOut, ComparisonCreate, ComparisonOut, EntryOut, FieldLayer, SectionAxis,
  ArtifactOut, CaseOut, ConfigIssue, EslRunOut, ExportTarget, JobOut, JobState, JobType, Me, Metric, StageState, SupportSetOut,
  ValidationOut,
} from "../api/types";
import {
  CANDIDATE_FRAMES, CORNER_IDS, EXTRACT_SUMMARY, FRAMES_D, MAX_ARTIFACT_BYTES, N_NODES, PLANE, PROJECTS, USERS, baseCase,
  makeArtifact, makeEslRun, makeForces, makePreview, makeSupportSet, makeTstarMetrics, makeValidation, toXYZ,
  type MockUserKey,
} from "./data";
import { envelopeCsv, makeAnalysisFiles, makeAnalysisResult, makeComparisonResult, makeEntries, makeField, makeFieldSummary, makeSection, reportHtml } from "./p2data";
import { modelVersions, pairEntries, prevVersion } from "../pages/library/common";

interface MockResponse {
  status: number;
  body?: unknown;
}

const STEPS: Record<JobType, string[]> = {
  CASE_EXTRACT: ["EXTRACT", "TSTAR_SCAN", "EXTRACT_REGISTER"],
  ESL_SOLVE: ["ESL", "ESL_REGISTER"],
  VALIDATE: ["VALIDATE", "VALIDATE_REGISTER"],
  EXPORT: ["EXPORT", "EXPORT_REGISTER"],
  CASE_REPORT: ["REPORT", "REPORT_REGISTER"],
  LIB_ANALYZE: ["LIB_ANALYZE", "OPTDECK", "REPORT", "LIB_REGISTER"],
  LIB_COMPARE: ["COMPARE", "COMPARE_REGISTER"],
};
/** 라이브러리 작업(LIB_ANALYZE·LIB_COMPARE)·보고서는 Case 단계가 아님(0) */
const STAGE_OF: Record<JobType, number> = { CASE_EXTRACT: 1, ESL_SOLVE: 4, VALIDATE: 5, EXPORT: 6, CASE_REPORT: 0, LIB_ANALYZE: 0, LIB_COMPARE: 0 };
const LIGHT: JobType[] = ["EXPORT", "CASE_REPORT", "LIB_COMPARE"];
const ACTIVE: JobState[] = ["QUEUED", "RUNNING"];
const TERMINAL: JobState[] = ["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"];

const err = (status: number, code: string, message: string, extra: Record<string, unknown> = {}): MockResponse => ({
  status,
  body: { detail: { code, message, ...extra } },
});

type Run = EslRunOut & { inputs: string };

export class MockServer {
  user: MockUserKey;
  cases: CaseOut[] = [];
  jobs: JobOut[] = [];
  logs: Record<string, string[]> = {};
  supportSets: SupportSetOut[] = [];
  runs: Run[] = [];
  validations: ValidationOut[] = [];
  artifacts: Record<string, ArtifactOut[]> = {};
  tstarMetrics = makeTstarMetrics();
  seq = 10;
  workerOnline = true;
  /** GET /status config.errors (백엔드 형식 {key, message}[]) */
  configErrors: ConfigIssue[] = [];
  entries: EntryOut[] = [];
  analyses: AnalysisOut[] = [];
  comparisons: ComparisonOut[] = [];

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
    const run: Run = { ...makeEslRun("run-1", a.id, ss.id, a.tstar!.frame_index, a.tstar!.time), inputs: this.inputsKey(a) };
    this.runs.push(run);
    a.current_esl_run_id = run.id;
    const v = makeValidation("val-1", run.id, a.id);
    this.validations.push(v);
    run.latest_validation_id = v.id;
    this.artifacts[a.id] = this.makeArtifacts(a, "j-exp-1", ["radioss_inc", "fem", "csv"]);

    // stale Case: t*를 바꾼 뒤 ESL 결과가 남아 있음
    const b = baseCase("c-stale", "p-body", "후방 충돌 56kph", "rear56");
    this.cases.push(b);
    this.finishExtract(b);
    const ss2 = makeSupportSet("ss-2", b.id);
    this.supportSets.push(ss2);
    b.current_support_set_id = ss2.id;
    const t0 = this.tstarMetrics.max_strain.candidates[0];
    const run2: Run = { ...makeEslRun("run-2", b.id, ss2.id, t0.frame_index, t0.time), inputs: this.inputsKey(b) };
    this.runs.push(run2);
    b.current_esl_run_id = run2.id;
    const c1 = this.tstarMetrics.max_strain.candidates[1];
    b.tstar = { metric: "max_strain", frame_index: c1.frame_index, time: c1.time, elem_id: c1.elem_id, value: c1.value, source: "user" };

    // 새 Case
    this.cases.push(baseCase("c-new", "p-body", "후방 오프셋 충돌", "rear_offset"));

    // 라이브러리: 항목 8개(1개 폐기) + 완료된 종합분석 1개
    this.entries = makeEntries("p-body");
    const pass = this.entries.filter((e) => e.status === "ACTIVE" && e.quality.verdict === "PASS");
    const an = this.makeAnalysis("an-1", { project_id: "p-body", title: "QN80H 꼭지점·모서리 강건 비드", target_entry_id: "le-1", filters: { verdict: ["PASS"] }, options: { normalization: "inch2", n_representative: 4, objective: "minmax" } }, pass);
    an.created_at = an.updated_at = "2026-10-18T05:00:00Z";
    this.finishAnalysis(an);
    this.analyses.push(an);
    // 설계 버전 비교 1개(완료): 75QN80H v072 → v073
    const cmp = this.makeComparison("cmp-1", { project_id: "p-body", model: "75QN80H", base_version: "v072", new_version: "v073", title: "비드 1차 반영 검증" });
    cmp.created_at = cmp.updated_at = "2026-10-19T05:00:00Z";
    this.finishComparison(cmp);
    this.comparisons.push(cmp);
  }

  private makeComparison(id: string, body: ComparisonCreate & { base_version: string }): ComparisonOut {
    const { pairs } = pairEntries(this.entries, body.model, body.base_version, body.new_version);
    return {
      id,
      project_id: body.project_id,
      title: body.title ?? null,
      model: body.model,
      base_version: body.base_version,
      new_version: body.new_version,
      filters: body.filters ?? {},
      options: body.options ?? {},
      base_entry_ids: pairs.map((p) => p.base.id),
      new_entry_ids: pairs.map((p) => p.next.id),
      n_paired: pairs.length,
      status: "QUEUED",
      verdict: null,
      job_id: null,
      job: null,
      result: null,
      result_rel: null,
      report_rel: null,
      dir_rel: `_compare/${id}`,
      folder_path: `E:\\ESL_ROOT\\_compare\\${id}`,
      created_by: this.me.user_id,
      created_by_name: this.me.display_name,
      created_at: this.now(),
      updated_at: this.now(),
    };
  }

  private finishComparison(c: ComparisonOut) {
    const { pairs } = pairEntries(this.entries, c.model, c.base_version, c.new_version);
    c.status = "SUCCEEDED";
    c.result = makeComparisonResult(pairs, c.options.cos_min ?? 0.95);
    c.verdict = c.result.convergence.verdict;
    c.result_rel = `${c.dir_rel}/compare.json`;
    c.report_rel = `${c.dir_rel}/report.html`;
  }

  private comparisonOut(c: ComparisonOut): ComparisonOut {
    const j = c.job_id ? this.jobs.find((x) => x.id === c.job_id) : undefined;
    return { ...c, status: j ? j.state : c.status, job: j ?? null };
  }

  private makeAnalysis(id: string, body: AnalysisCreate, hit: EntryOut[]): AnalysisOut {
    const dir = `_analysis/${id}`;
    return {
      id,
      project_id: body.project_id,
      title: body.title ?? null,
      target_entry_id: body.target_entry_id ?? null,
      filters: body.filters ?? {},
      options: body.options ?? {},
      entry_ids: hit.map((e) => e.id),
      n_entries: hit.length,
      status: "QUEUED",
      job_id: null,
      job: null,
      result: null,
      dir_rel: dir,
      folder_path: `E:\\ESL_ROOT\\_analysis\\${id}`,
      result_rel: null,
      report_rel: null,
      optdeck_rel: null,
      created_by: this.me.user_id,
      created_by_name: this.me.display_name,
      created_at: this.now(),
      updated_at: this.now(),
    };
  }

  private finishAnalysis(a: AnalysisOut) {
    const hit = this.entries.filter((e) => a.entry_ids.includes(e.id));
    const target = this.entries.find((e) => e.id === a.target_entry_id) ?? null;
    a.status = "SUCCEEDED";
    a.result = makeAnalysisResult(hit, target, a.options.n_representative ?? 5, !!a.options.worst_case, a.options.objective ?? "minmax", a.options.optdeck_cases ?? "all");
    a.result_rel = `${a.dir_rel}/analysis.json`;
    a.report_rel = `${a.dir_rel}/report.html`;
    a.optdeck_rel = target ? `${a.dir_rel}/opt` : null;
  }

  private inputsKey(c: CaseOut) {
    return `${c.tstar?.metric}:${c.tstar?.frame_index}:${c.current_support_set_id}:${c.part_title}`;
  }

  private finishExtract(c: CaseOut) {
    c.extract_summary = EXTRACT_SUMMARY;
    c.part_id = 10;
    c.h3d_path = c.results_dir.replace(/h3d_csv$/, "chassis_rear.h3d");
    const t = this.tstarMetrics.max_strain.tstar!;
    c.tstar = { metric: "max_strain", ...t, source: "auto" };
  }

  private makeArtifacts(c: CaseOut, jobId: string, targets: ExportTarget[]): ArtifactOut[] {
    const files: [ExportTarget, string, string, number][] = [
      ["radioss_inc", "radioss_inc", "esl_cload.inc", 1_482_331],
      ["radioss_inc", "radioss_inc", "esl_bcs.inc", 2_118],
      ["fem", "fem", "esl_force.fem", 31_904_772],
      ["csv", "csv", "f_eq.csv", 402_118],
      ["csv", "csv", "u_rel.csv", 398_511],
      ["csv", "csv", "reactions_321.csv", 311],
      ["csv", "csv", "validation.csv", 1_204],
    ];
    return files
      .filter(([t]) => targets.includes(t))
      .map(([, kind, name, size], k) => makeArtifact(`${jobId}-a${k}`, c, `06_export/${name}`, size, kind, jobId));
  }

  private canRun(projectId: string) {
    const me = this.me;
    if (me.is_global_admin) return true;
    const r = me.roles[projectId];
    return r === "power" || r === "admin";
  }

  private activeJob(caseId: string, stage: number) {
    return this.jobs.find((j) => j.case_id === caseId && j.stage === stage && ACTIVE.includes(j.state));
  }

  private lastJob(caseId: string, stage: number) {
    return [...this.jobs].reverse().find((j) => j.case_id === caseId && j.stage === stage);
  }

  private currentRun(c: CaseOut) {
    return this.runs.find((r) => r.id === c.current_esl_run_id);
  }

  stageStatus(c: CaseOut): Record<string, StageState> {
    const run = this.currentRun(c);
    const runStale = !!run && run.inputs !== this.inputsKey(c);
    const out: Record<string, StageState> = {};
    const has: Record<number, boolean> = {
      1: !!c.extract_summary,
      2: !!c.tstar,
      3: !!c.current_support_set_id,
      4: !!run,
      5: !!run?.latest_validation_id,
      6: (this.artifacts[c.id] ?? []).length > 0,
    };
    for (let n = 1; n <= 6; n++) {
      const stage = n === 2 ? 1 : n;
      const active = this.activeJob(c.id, stage);
      const last = this.lastJob(c.id, stage);
      let st: StageState = { state: has[n] ? "done" : "none", job_id: last?.id ?? null };
      if (n >= 4 && has[n] && runStale) st = { state: "stale", job_id: last?.id ?? null };
      if (!has[n] && last && (last.state === "FAILED" || last.state === "INTERRUPTED")) st = { state: "failed", job_id: last.id };
      if (active) st = { state: "running", job_id: active.id };
      out[String(n)] = st;
    }
    return out;
  }

  private caseOut(c: CaseOut): CaseOut {
    const run = this.currentRun(c);
    if (run) run.stale = run.inputs !== this.inputsKey(c);
    return { ...c, stage_status: this.stageStatus(c) };
  }

  private runOut(run: Run): EslRunOut {
    const c = this.findCase(run.case_id)!;
    const { inputs, ...rest } = run;
    return { ...rest, stale: inputs !== this.inputsKey(c), is_current: c.current_esl_run_id === run.id };
  }

  private validationOut(v: ValidationOut): ValidationOut {
    const run = this.runs.find((x) => x.id === v.esl_run_id)!;
    const c = this.findCase(run.case_id)!;
    return { ...v, stale: run.inputs !== this.inputsKey(c) || c.current_esl_run_id !== run.id, field: makeFieldSummary() };
  }

  /** 테스트·스크린샷용: 특정 Case 상태를 직접 바꾼다 */
  findCase(id: string) {
    return this.cases.find((c) => c.id === id);
  }

  findArtifact(id: string) {
    return Object.values(this.artifacts).flat().find((a) => a.id === id);
  }

  private queuePositions() {
    for (const lane of ["SLOT", "LIGHT"] as const) {
      let k = 0;
      for (const j of this.jobs) if (j.lane === lane) j.queue_position = j.state === "QUEUED" ? ++k : null;
    }
  }

  handle(method: string, rawPath: string, query: URLSearchParams, body: unknown): MockResponse {
    const path = rawPath.replace(/^\/esl\/api/, "");
    const b = (body ?? {}) as Record<string, unknown>;
    const m = (re: RegExp) => path.match(re);
    let r: RegExpMatchArray | null;
    this.queuePositions();

    if (method === "GET" && path === "/health") return { status: 200, body: { status: "ok", version: "mock" } };
    if (method === "GET" && path === "/me") return { status: 200, body: this.me };
    if (method === "GET" && path === "/projects") return { status: 200, body: PROJECTS };
    if (method === "GET" && path === "/status")
      return {
        status: 200,
        body: {
          config: { ok: this.configErrors.length === 0, errors: this.configErrors },
          worker: { online: this.workerOnline, last_seen_at: this.now(), limiter: "posix" },
          tools: { solver_backend: "cholmod", solver_backends_available: ["cholmod", "pardiso", "superlu", "iterative"] },
          version: "mock",
          core_version: "mock",
        },
      };
    if ((r = m(/^\/cases\/([^/]+)\/report$/)) && method === "GET") {
      const c = this.findCase(r[1]);
      if (!c) return err(404, "CASE_NOT_FOUND", "Case를 찾을 수 없습니다.");
      if (!this.runs.some((x) => x.case_id === c.id && x.latest_validation_id)) return err(404, "REPORT_NOT_FOUND", "보고서가 아직 없습니다(검증 후 생성)");
      return { status: 200, body: reportHtml(`Case 보고서 — ${c.title}`) };
    }
    if (method === "GET" && path === "/queue") {
      const live = this.jobs.filter((j) => ACTIVE.includes(j.state));
      const sum = (j: JobOut) => ({ ...j, steps: null });
      const lane = (name: "SLOT" | "LIGHT") => {
        const js = live.filter((j) => j.lane === name);
        const run = js.find((j) => j.state === "RUNNING");
        return { running: run ? sum(run) : null, queued: js.filter((j) => j.state === "QUEUED").map(sum) };
      };
      const slot = lane("SLOT");
      return { status: 200, body: { running: slot.running, queued: slot.queued, light: lane("LIGHT") } };
    }
    if (method === "POST" && path === "/paths/inspect") {
      const p = String(b.path ?? "").trim();
      if (!p) return err(422, "PATH_NOT_FOUND", "경로를 입력하세요.");
      if (!/^[A-Za-z]:\\ESL_INPUT\\|^\/data\/esl_input\//i.test(p))
        return err(422, "PATH_OUTSIDE_ROOT", "허용된 입력 폴더(input_roots) 밖의 경로입니다.");
      if (b.purpose === "RAD") {
        const parts = [
          { id: 10, title: "chassis_rear", n_elems: 223415 },
          { id: 11, title: "bumper_beam", n_elems: 18220 },
          { id: 12, title: "crash_box_L", n_elems: 6402 },
        ];
        return {
          status: 200,
          body: {
            normalized_path: p,
            ok: true,
            problems: [],
            parts,
            includes: [
              { path: p.replace(/[^\\/]+$/, "inc_mat.inc"), ok: true },
              { path: p.replace(/[^\\/]+$/, "inc_mesh.inc"), ok: true },
            ],
            part_title: "chassis_rear",
            target_part: parts[0],
          },
        };
      }
      const files = ["done.json", "frames.csv", "model.csv", "final.csv", "history.csv", "disp.csv", "strain_frames.csv"].map((name, k) => ({
        name,
        size: 1000 * (k + 1),
        mtime: 1760000000 + k,
      }));
      return {
        status: 200,
        body: {
          normalized_path: p,
          ok: true,
          problems: [],
          done: {
            ok: true,
            part_id: 10,
            part_spec: "chassis_rear",
            candidate_frames: CANDIDATE_FRAMES,
            hot_k: 200,
            warnings: [],
            h3d: "D:\\CAE\\chassis_rear.h3d",
          },
          n_frames: 126,
          files,
        },
      };
    }
    if (method === "GET" && path === "/cases") {
      const pid = query.get("project_id");
      return { status: 200, body: this.cases.filter((c) => !pid || c.project_id === pid).map((c) => ({ ...this.caseOut(c), stage_status: this.stageStatus(c) })) };
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
      c.part_id = 10;
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
    if ((r = m(/^\/jobs\/([^/]+)(\/log|\/cancel|\/retry)?$/))) {
      const j = this.jobs.find((x) => x.id === r![1]);
      if (!j) return err(404, "JOB_NOT_FOUND", "작업을 찾을 수 없습니다.");
      if (method === "GET" && !r[2]) return { status: 200, body: j };
      if (method === "GET" && r[2] === "/log") {
        const lines = this.logs[j.id] ?? [];
        const cur = Number(query.get("cursor") ?? 0) || 0;
        return { status: 200, body: { step: j.current_step_no ?? 1, lines: lines.slice(cur), next_cursor: lines.length, eof: TERMINAL.includes(j.state) } };
      }
      if (method === "POST" && r[2] === "/cancel") {
        if (TERMINAL.includes(j.state)) return err(409, "JOB_TERMINAL", "이미 끝난 작업입니다");
        j.cancel_requested = true;
        this.complete(j, "CANCELED");
        return { status: 200, body: j };
      }
      if (method === "POST" && r[2] === "/retry") {
        if (!["FAILED", "INTERRUPTED", "CANCELED"].includes(j.state)) {
          const code = TERMINAL.includes(j.state) ? "JOB_TERMINAL" : "JOB_NOT_TERMINAL";
          return err(409, code, "실패·중단·취소된 작업만 재시도할 수 있습니다");
        }
        const nj = this.newJob({ id: j.case_id, project_id: j.project_id }, j.job_type, j.params);
        nj.analysis_id = j.analysis_id ?? null;
        nj.comparison_id = j.comparison_id ?? null;
        const a = this.analyses.find((x) => x.job_id === j.id);
        if (a) a.job_id = nj.id;
        const cp = this.comparisons.find((x) => x.job_id === j.id);
        if (cp) cp.job_id = nj.id;
        nj.retry_of_job_id = j.id;
        return { status: 201, body: nj };
      }
    }
    if ((r = m(/^\/esl-runs\/([^/]+)(\/forces)?$/)) && method === "GET") {
      const run = this.runs.find((x) => x.id === r![1]);
      if (!run) return err(404, "ESL_RUN_NOT_FOUND", "ESL 결과를 찾을 수 없습니다.");
      if (r[2]) return { status: 200, body: { esl_run_id: run.id, n_nodes: N_NODES, rows: makeForces().slice(0, Number(query.get("top") ?? 50)) } };
      return { status: 200, body: this.runOut(run) };
    }
    if ((r = m(/^\/validations\/([^/]+)\/(field|section)$/)) && method === "GET") {
      if (!this.validations.some((x) => x.id === r![1])) return err(404, "VALIDATION_NOT_FOUND", "검증 결과를 찾을 수 없습니다.");
      if (r[2] === "field") {
        const layer = (query.get("layer") ?? "rad") as FieldLayer;
        if (!["rad", "esl", "err"].includes(layer)) return err(422, "INVALID_PARAMS", "layer: rad|esl|err");
        return { status: 200, body: makeField(r[1], layer, Number(query.get("max_points") ?? 20000) || 20000) };
      }
      const axis = (query.get("axis") ?? "xi") as SectionAxis;
      if (!["xi", "eta"].includes(axis)) return err(422, "INVALID_PARAMS", "axis: xi|eta");
      return { status: 200, body: makeSection(r[1], axis, Number(query.get("at") ?? 0.5)) };
    }
    if (path.startsWith("/library/")) return this.library(method, path, query, b);
    if ((r = m(/^\/validations\/([^/]+)$/)) && method === "GET") {
      const v = this.validations.find((x) => x.id === r![1]);
      if (!v) return err(404, "VALIDATION_NOT_FOUND", "검증 결과를 찾을 수 없습니다.");
      return { status: 200, body: this.validationOut(v) };
    }
    if ((r = m(/^\/artifacts\/([^/]+)\/download$/)) && method === "GET") {
      const a = this.findArtifact(r[1]);
      if (!a) return err(404, "ARTIFACT_NOT_FOUND", "산출물을 찾을 수 없습니다");
      if (a.size > MAX_ARTIFACT_BYTES)
        return err(413, "ARTIFACT_TOO_LARGE", "파일이 커서 다운로드할 수 없습니다. 경로를 복사해 여세요", {
          rel: a.rel,
          path: a.path,
          size: a.size,
          limit: MAX_ARTIFACT_BYTES,
        });
      return { status: 200, body: "mock file\n" };
    }
    return err(404, "NOT_FOUND", `목 서버에 없는 경로: ${method} ${path}`);
  }

  /** 라이브러리 API (계약 §11, openapi EntryOut·AnalysisOut) */
  private library(method: string, path: string, query: URLSearchParams, b: Record<string, unknown>): MockResponse {
    let r: RegExpMatchArray | null;
    if (path === "/library/entries" && method === "GET") {
      const f = (k: string) => query.get(k);
      const out = this.entries.filter(
        (e) =>
          (!f("project_id") || e.project_id === f("project_id")) &&
          (!f("model") || e.model.name === f("model")) &&
          (!f("inch") || String(e.model.inch) === f("inch")) &&
          (!f("drop_type") || e.scene.drop_type === f("drop_type")) &&
          (!f("orient") || e.scene.orient === f("orient")) &&
          (!f("scenario") || e.scene.scenario === f("scenario")) &&
          (!f("verdict") || e.quality.verdict === f("verdict")) &&
          (!f("status") || e.status === f("status")),
      );
      return { status: 200, body: out };
    }
    if (path === "/library/entries" && method === "POST") {
      const run = this.runs.find((x) => x.id === b.esl_run_id);
      if (!run) return err(404, "ESL_RUN_NOT_FOUND", "ESL 결과를 찾을 수 없습니다.");
      const c = this.findCase(run.case_id)!;
      if (!this.canRun(c.project_id)) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
      const v = this.validations.find((x) => x.id === (b.validation_id ?? run.latest_validation_id));
      if (!v) return err(409, "PREREQUISITE_MISSING", "검증 결과가 필요합니다", { missing: ["validation"] });
      if (this.entries.some((e) => e.esl_run_id === run.id && e.status === "ACTIVE"))
        return err(409, "ENTRY_EXISTS", "이 ESL 결과는 이미 라이브러리에 등록되어 있습니다");
      const reason = typeof b.force_reason === "string" ? b.force_reason.trim() : "";
      if (v.verdict !== "PASS" && !reason) return err(422, "VALIDATION_NOT_PASS", "검증 FAIL 은 사유(force_reason)와 함께만 등록할 수 있습니다");
      const fs = makeFieldSummary();
      const t = this.now();
      const base = makeEntries(c.project_id)[0];
      const id = this.id("le");
      const e: EntryOut = {
        ...base,
        id,
        case_id: c.id,
        case_title: c.title,
        esl_run_id: run.id,
        validation_id: v.id,
        dir_rel: `_library/${id}`,
        summary_rel: `_library/${id}/summary.npz`,
        quality: {
          verdict: v.verdict,
          fail_reasons: v.fail_reasons,
          field_max_err_pct: fs.max?.abs_err_pct ?? null,
          field_p90_err_pct: fs.abs_err_pct?.p90 ?? null,
          noise: { hotspot_strain_rel: 0.0011 },
          confirmed_fail: reason ? { reason, by: this.me.user_id, by_name: this.me.display_name, at: t } : null,
        },
        registered_by: this.me.user_id,
        registered_by_name: this.me.display_name,
        registered_at: t,
        updated_at: t,
        note: typeof b.note === "string" ? b.note : null,
        force_reason: reason || null,
      };
      this.entries.unshift(e);
      return { status: 201, body: e };
    }
    if ((r = path.match(/^\/library\/entries\/([^/]+)(\/retire)?$/))) {
      const e = this.entries.find((x) => x.id === r![1]);
      if (!e) return err(404, "ENTRY_NOT_FOUND", "라이브러리 항목을 찾을 수 없습니다.");
      if (method === "GET" && !r[2]) return { status: 200, body: e };
      if (!this.canRun(e.project_id)) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
      if (method === "POST" && r[2]) {
        if (e.status === "RETIRED") return err(409, "ENTRY_RETIRED", "이미 폐기된 항목입니다");
        e.status = "RETIRED";
        e.retired_by_id = this.me.user_id;
        e.retired_at = this.now();
        e.retire_reason = typeof b.reason === "string" ? b.reason : null;
        e.version += 1;
        return { status: 200, body: e };
      }
      if (method === "PATCH" && !r[2]) {
        if (b.version !== e.version) return err(409, "VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요");
        const mm = (b.model ?? {}) as Record<string, unknown>;
        if ("product_mass" in mm) {
          const v = mm.product_mass;
          if (v !== null && !(typeof v === "number" && v > 0)) return err(422, "INVALID_PARAMS", "product_mass 는 양수(kg)입니다");
          e.model = { ...e.model, product_mass: v as number | null };
        }
        if (b.scene) e.scene = { ...e.scene, ...(b.scene as Record<string, string | null>) };
        e.version += 1;
        e.updated_at = this.now();
        return { status: 200, body: e };
      }
    }
    if (path === "/library/analyses" && method === "GET") {
      const pid = query.get("project_id");
      return { status: 200, body: this.analyses.filter((a) => !pid || a.project_id === pid).map((a) => this.analysisOut(a)).reverse() };
    }
    if (path === "/library/analyses" && method === "POST") {
      const body = b as unknown as AnalysisCreate;
      if (!this.canRun(body.project_id)) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
      const f: AnalysisFilters = body.filters ?? {};
      const inList = (xs: (string | number)[] | null | undefined, v: string | number | null | undefined) => !xs?.length || (v != null && xs.includes(v));
      const hit = this.entries.filter(
        (e) =>
          e.project_id === body.project_id &&
          e.status === "ACTIVE" &&
          (f.entry_ids?.length
            ? f.entry_ids.includes(e.id)
            : inList(f.model, e.model.name) &&
              inList(f.inch, e.model.inch) &&
              inList(f.drop_type, e.scene.drop_type) &&
              inList(f.orient, e.scene.orient) &&
              inList(f.scenario, e.scene.scenario) &&
              inList(f.verdict, e.quality.verdict)),
      );
      if (!hit.length) return err(422, "NO_MATCHING_ENTRIES", "필터에 맞는 활성 라이브러리 항목이 없습니다");
      const o = body.options ?? {};
      if (o.n_representative != null && (!Number.isInteger(o.n_representative) || o.n_representative < 1))
        return err(422, "INVALID_PARAMS", "n_representative 는 1 이상 정수입니다");
      const tgt = this.entries.find((e) => e.id === body.target_entry_id);
      if (body.target_entry_id && (!tgt || tgt.status !== "ACTIVE")) return err(422, "TARGET_INVALID", "대상은 이 프로젝트의 활성 라이브러리 항목이어야 합니다");
      if (o.normalization === "mass" || o.normalization === "inch2") {
        const key = o.normalization === "mass" ? "product_mass" : "inch";
        const miss = hit.filter((e) => !e.model[key]).map((e) => e.id);
        const tval = (o.normalization === "mass" ? o.target_mass : o.target_inch) ?? tgt?.model[key];
        if (miss.length || !tval)
          return err(422, "NORMALIZATION_META_MISSING", `normalization=${o.normalization}: ${key} 가 필요합니다`, { entry_ids: miss, target_missing: !tval });
      }
      const a = this.makeAnalysis(this.id("an"), body, hit);
      const j = this.newJob({ id: null, project_id: body.project_id }, "LIB_ANALYZE", { analysis_id: a.id });
      j.analysis_id = a.id;
      a.job_id = j.id;
      this.analyses.push(a);
      return { status: 201, body: this.analysisOut(a) };
    }
    if ((r = path.match(/^\/library\/analyses\/([^/]+)(\/report|\/files|\/download)?$/)) && method === "GET") {
      const a = this.analyses.find((x) => x.id === r![1]);
      if (!a) return err(404, "ANALYSIS_NOT_FOUND", "분석을 찾을 수 없습니다");
      const out = this.analysisOut(a);
      if (!r[2]) return { status: 200, body: out };
      if (out.status !== "SUCCEEDED") return r[2] === "/files" ? { status: 200, body: [] } : err(404, "REPORT_NOT_FOUND", "보고서가 아직 없습니다(분석 작업 완료 후 생성)");
      if (r[2] === "/files") return { status: 200, body: makeAnalysisFiles(a) };
      if (r[2] === "/report") return { status: 200, body: reportHtml(`종합분석 ${a.title ?? a.id}`) };
      const rel = query.get("rel") ?? "";
      const file = makeAnalysisFiles(a).find((x) => x.rel === rel);
      if (!file) return err(404, "FILE_NOT_FOUND", "파일이 없습니다");
      if (!file.downloadable)
        return err(413, "ARTIFACT_TOO_LARGE", "파일이 커서 다운로드할 수 없습니다. 경로를 복사해 여세요", { rel, path: file.path, size: file.size, limit: MAX_ARTIFACT_BYTES });
      return { status: 200, body: rel === "envelope.csv" ? envelopeCsv() : "mock file\n" };
    }
    if (path === "/library/comparisons" && method === "GET") {
      const pid = query.get("project_id");
      return { status: 200, body: this.comparisons.filter((c) => !pid || c.project_id === pid).map((c) => this.comparisonOut(c)).reverse() };
    }
    if (path === "/library/comparisons" && method === "POST") {
      const body = b as unknown as ComparisonCreate;
      if (!this.canRun(body.project_id)) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
      const mine = this.entries.filter((e) => e.project_id === body.project_id);
      const versions = modelVersions(mine).find((m) => m.model === body.model)?.versions ?? [];
      if (!versions.includes(body.new_version)) return err(422, "VERSION_NOT_FOUND", `모델 ${body.model} 에 비교 버전 ${body.new_version} 의 활성 항목이 없습니다`, { versions });
      const base = body.base_version ?? prevVersion(versions, body.new_version);
      if (!base) return err(422, "NO_PAIRED_SCENES", `비교 버전 ${body.new_version} 이전 버전이 없습니다`, { versions });
      if (base === body.new_version) return err(422, "INVALID_PARAMS", "기준 버전과 비교 버전이 같습니다");
      if (!pairEntries(mine, body.model, base, body.new_version).pairs.length)
        return err(422, "NO_PAIRED_SCENES", "기준·비교 버전에 같은 씬 키의 항목이 없습니다", { base_version: base, new_version: body.new_version });
      const c = this.makeComparison(this.id("cmp"), { ...body, base_version: base });
      const j = this.newJob({ id: null, project_id: body.project_id }, "LIB_COMPARE", { comparison_id: c.id, model: c.model, base_version: base, new_version: c.new_version });
      j.comparison_id = c.id;
      c.job_id = j.id;
      this.comparisons.push(c);
      return { status: 201, body: this.comparisonOut(c) };
    }
    if ((r = path.match(/^\/library\/comparisons\/([^/]+)(\/report)?$/)) && method === "GET") {
      const c = this.comparisons.find((x) => x.id === r![1]);
      if (!c) return err(404, "COMPARISON_NOT_FOUND", "비교를 찾을 수 없습니다");
      const out = this.comparisonOut(c);
      if (!r[2]) return { status: 200, body: out };
      if (out.status !== "SUCCEEDED") return err(404, "REPORT_NOT_FOUND", "보고서가 아직 없습니다(비교 작업 완료 후 생성)");
      return { status: 200, body: reportHtml(`버전 비교 ${c.model} ${c.base_version} → ${c.new_version}`) };
    }
    return err(404, "NOT_FOUND", `목 서버에 없는 경로: ${method} ${path}`);
  }

  private analysisOut(a: AnalysisOut): AnalysisOut {
    const j = a.job_id ? this.jobs.find((x) => x.id === a.job_id) : undefined;
    return { ...a, status: j ? j.state : a.status, job: j ?? null };
  }

  private newJob(c: { id: string | null; project_id: string }, jt: JobType, params: Record<string, unknown>): JobOut {
    const t = this.now();
    const job: JobOut = {
      id: this.id("j"),
      case_id: c.id,
      project_id: c.project_id,
      job_type: jt,
      stage: STAGE_OF[jt],
      lane: LIGHT.includes(jt) ? "LIGHT" : "SLOT",
      state: "QUEUED",
      params,
      result: null,
      warnings: [],
      cancel_requested: false,
      current_step_no: null,
      progress_pct: null,
      queue_position: null,
      queued_at: t,
      started_at: null,
      finished_at: null,
      failure_code: null,
      failure_message: null,
      retry_of_job_id: null,
      resume_from_step: null,
      created_by: this.me.user_id,
      created_by_name: this.me.display_name,
      created_at: t,
      updated_at: t,
      version: 1,
      steps: STEPS[jt].map((k, i) => ({
        step_no: i + 1,
        step_key: k,
        kind: "INTERNAL",
        core_stage: null,
        state: "PENDING",
        progress_pct: 0,
        exit_code: null,
        failure_code: null,
        failure_message: null,
        started_at: null,
        finished_at: null,
      })),
    };
    this.jobs.push(job);
    this.queuePositions();
    this.logs[job.id] = [`[${job.job_type}] 대기열 등록 (#${job.queue_position})`];
    return job;
  }

  private caseSub(c: CaseOut, method: string, sub: string, b: Record<string, unknown>): MockResponse {
    const write = method !== "GET";
    if (write && !this.canRun(c.project_id)) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
    if (sub === "tstar" && method === "GET") {
      if (!c.extract_summary) return err(409, "PREREQUISITE_MISSING", "t* 산출물(02_tstar/tstar.json)이 없습니다", { missing: ["tstar"] });
      const sel = (c.tstar?.metric ?? "max_strain") as Metric;
      return {
        status: 200,
        body: {
          selected: c.tstar,
          default_metric: "max_strain",
          metrics: this.tstarMetrics,
          hotspots: this.tstarMetrics[sel].hotspots,
          frames_D: FRAMES_D,
        },
      };
    }
    if (sub === "tstar" && method === "PUT") {
      if (b.version !== c.version) return err(409, "VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요");
      const metric = b.metric as Metric;
      const blk = this.tstarMetrics[metric];
      if (!blk) return err(422, "INVALID_METRIC", `지표 ${metric} 가 없습니다`);
      const cand = blk.candidates.find((x) => x.frame_index === b.frame_index);
      if (!cand || cand.in_D === false)
        return err(422, "FRAME_NOT_CANDIDATE", `frame ${b.frame_index} 은 ${metric} 후보가 아닙니다`, {
          candidates: blk.candidates.filter((x) => x.in_D !== false).map((x) => x.frame_index),
        });
      c.tstar = { metric, frame_index: cand.frame_index, time: cand.time, elem_id: cand.elem_id, value: cand.value, source: "user" };
      c.version += 1;
      return { status: 200, body: this.caseOut(c) };
    }
    if (sub.startsWith("preview") && method === "GET") {
      const sup = this.supportSets.find((s) => s.id === c.current_support_set_id);
      return {
        status: 200,
        body: makePreview(c.tstar?.frame_index ?? null, sup ? sup.node_ids.map((n, k) => ({ node_id: n, dof: sup.dofs[k] })) : []),
      };
    }
    if (sub === "support-sets/suggest" && method === "POST") {
      const ids = [CORNER_IDS[0], CORNER_IDS[1], CORNER_IDS[3]];
      return { status: 200, body: { node_ids: ids, dofs: ["123", "23", "3"], coords: ids.map(toXYZ), plane: PLANE, corners: CORNER_IDS } };
    }
    if (sub === "support-sets" && method === "GET")
      return {
        status: 200,
        body: this.supportSets.filter((s) => s.case_id === c.id).map((s) => ({ ...s, is_current: s.id === c.current_support_set_id })),
      };
    if (sub === "support-sets" && method === "POST") {
      const ids = (b.node_ids as number[]) ?? [];
      const bad = ids.filter((x) => !Number.isInteger(x) || x < 1 || x > N_NODES);
      if (ids.length !== 3) return err(422, "INVALID_PARAMS", "node_ids 는 3개입니다");
      if (bad.length) return err(422, "NODE_NOT_IN_PART", `대상 파트에 없는 노드: ${bad}`, { node_ids: bad });
      if (new Set(ids).size < 3) return err(422, "INVALID_PARAMS", "세 노드가 서로 달라야 합니다.");
      const auto = [CORNER_IDS[0], CORNER_IDS[1], CORNER_IDS[3]];
      const ss: SupportSetOut = {
        id: this.id("ss"),
        case_id: c.id,
        node_ids: ids,
        dofs: ["123", "23", "3"],
        source: [...ids].sort().join() === [...auto].sort().join() ? "auto" : "user",
        plane: PLANE,
        created_by: this.me.user_id,
        created_at: this.now(),
        is_current: true,
      };
      this.supportSets.push(ss);
      c.current_support_set_id = ss.id;
      c.version += 1;
      return { status: 201, body: ss };
    }
    if (sub === "esl-runs" && method === "GET")
      return { status: 200, body: this.runs.filter((x) => x.case_id === c.id).reverse().map((x) => this.runOut(x)) };
    if (sub === "validations" && method === "GET")
      return { status: 200, body: this.validations.filter((v) => v.case_id === c.id).reverse().map((v) => this.validationOut(v)) };
    if (sub === "artifacts" && method === "GET") return { status: 200, body: this.artifacts[c.id] ?? [] };
    if (sub === "jobs" && method === "GET")
      return { status: 200, body: this.jobs.filter((j) => j.case_id === c.id).reverse().map((j) => ({ ...j, steps: null })) };
    if (sub === "jobs" && method === "POST") {
      const jt = b.job_type as JobType;
      if (!STEPS[jt]) return err(422, "INVALID_PARAMS", "요청 값이 올바르지 않습니다");
      if (this.jobs.some((j) => j.case_id === c.id && j.job_type === jt && ACTIVE.includes(j.state)))
        return err(409, "CASE_JOB_BUSY", "같은 Case 에서 같은 종류의 작업이 대기 중이거나 실행 중입니다");
      const missing: string[] = [];
      if (jt === "ESL_SOLVE") {
        if (!c.extract_summary) missing.push("extract");
        if (!c.tstar) missing.push("tstar");
        if (!c.current_support_set_id) missing.push("support_set");
      }
      if (jt === "VALIDATE" || jt === "EXPORT") {
        const run = this.currentRun(c);
        if (!run || (b.params as Record<string, unknown>)?.esl_run_id !== run.id) missing.push("esl_run");
        else if (jt === "VALIDATE" && run.inputs !== this.inputsKey(c)) missing.push("fresh_esl_run");
      }
      if (missing.length) return err(409, "PREREQUISITE_MISSING", "앞 단계가 필요합니다", { missing });
      return { status: 201, body: this.newJob(c, jt, (b.params as Record<string, unknown>) ?? {}) };
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
        next.current_step_no = 1;
        next.steps![0].state = "RUNNING";
        this.logs[next.id].push(`작업 시작 — step 1 ${next.steps![0].step_key}`);
      }
    }
    this.queuePositions();
  }

  private advance(j: JobOut) {
    const steps = j.steps!;
    const step = steps.find((s) => s.state === "RUNNING");
    if (!step) return;
    step.progress_pct = Math.min(100, (step.progress_pct ?? 0) + 50);
    this.logs[j.id].push(`  ${step.step_key}: ${step.progress_pct}%`);
    j.progress_pct = Math.round(((steps.filter((s) => s.state === "SUCCEEDED").length + step.progress_pct / 100) / steps.length) * 100);
    if (step.progress_pct < 100) return;
    step.state = "SUCCEEDED";
    step.exit_code = 0;
    const nxt = steps.find((s) => s.state === "PENDING");
    if (nxt) {
      nxt.state = "RUNNING";
      j.current_step_no = nxt.step_no;
      this.logs[j.id].push(`step ${nxt.step_no} ${nxt.step_key} 시작`);
      return;
    }
    this.complete(j, "SUCCEEDED");
  }

  private complete(j: JobOut, state: JobState) {
    j.state = state;
    j.finished_at = this.now();
    this.logs[j.id].push(`작업 종료: ${state}`);
    if (state !== "SUCCEEDED") return;
    if (j.job_type === "LIB_ANALYZE") {
      const a = this.analyses.find((x) => x.job_id === j.id);
      if (a) this.finishAnalysis(a);
      return;
    }
    if (j.job_type === "LIB_COMPARE") {
      const c = this.comparisons.find((x) => x.job_id === j.id);
      if (c) this.finishComparison(c);
      return;
    }
    const c = j.case_id ? this.findCase(j.case_id) : undefined;
    if (!c) return;
    if (j.job_type === "CASE_EXTRACT") this.finishExtract(c);
    if (j.job_type === "ESL_SOLVE") {
      const run: Run = {
        ...makeEslRun(this.id("run"), c.id, c.current_support_set_id!, c.tstar!.frame_index, c.tstar!.time, c.tstar!.metric),
        inputs: this.inputsKey(c),
      };
      run.job_id = j.id;
      this.runs.push(run);
      c.current_esl_run_id = run.id;
      this.artifacts[c.id] = [];
    }
    if (j.job_type === "VALIDATE") {
      const run = this.currentRun(c)!;
      const v = { ...makeValidation(this.id("val"), run.id, c.id), job_id: j.id };
      this.validations.push(v);
      run.latest_validation_id = v.id;
    }
    if (j.job_type === "EXPORT") {
      this.artifacts[c.id] = this.makeArtifacts(c, j.id, (j.params.targets as ExportTarget[]) ?? []);
    }
    // 백엔드: 추출·ESL 등록만 cases 를 갱신(version+1). 검증·내보내기는 Case 를 바꾸지 않는다.
    if (j.job_type === "CASE_EXTRACT" || j.job_type === "ESL_SOLVE") c.version += 1;
  }

  /** 테스트용: 작업 끝까지 진행 */
  drain() {
    for (let k = 0; k < 100 && this.jobs.some((j) => ACTIVE.includes(j.state)); k++) this.tick();
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
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    const r = server.handle(method, url.pathname, url.searchParams, body);
    if (typeof r.body === "string")
      return new Response(r.body, { status: r.status, headers: { "Content-Type": "application/octet-stream" } });
    return new Response(r.body === undefined ? null : JSON.stringify(r.body), {
      status: r.status,
      headers: { "Content-Type": "application/json" },
    });
  };
}
