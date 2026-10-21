// P3-이력 목 서버(계약 esl_p3_history.md §3 응답 키 그대로). MockServer.handle 맨 앞에서 먼저 시도한다.
// 읽기 전용 열람용 과거 ESL run·검증(run-old·val-old·val-old2)은 seedInto 로 MockServer 의 runs·validations 에 넣어
// 기존 /esl-runs·/validations·field·section 핸들러가 그대로 응답하게 한다.
import type { HistoryItem, ReviewDiff, ReviewOut, ReviewResult } from "../api/history";
import type { EslRunOut, FieldLayer, JobType, SectionAxis, ValidationOut } from "../api/types";
import { N_NODES, makeEslRun, makeForces, makeValidation } from "./data";
import { makeField, makeFieldSummary, makeSection } from "./p2data";

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
const STAGE: Record<JobType, number> = { CASE_EXTRACT: 1, ESL_SOLVE: 4, VALIDATE: 5, EXPORT: 6, CASE_REPORT: 0, LIB_ANALYZE: 0, LIB_COMPARE: 0 };
const CASES: Record<string, { title: string; folder: string }> = {
  "c-demo": { title: "후방 충돌 40kph", folder: "rear40" },
  "c-stale": { title: "후방 충돌 56kph", folder: "rear56" },
};
const PROJECT = "p-body";
const T0 = Date.UTC(2026, 9, 20, 9, 0, 0);

type Extra = Partial<HistoryItem> & {
  availability?: "full" | "summary" | "none";
  reasons?: string[];
  files_note?: string;
  diff?: ReviewDiff[];
  past?: Record<string, unknown>;
  links?: ReviewResult["links"];
  warnings?: string[];
};
interface Seed {
  item: HistoryItem;
  extra: Extra;
}

const iso = (ms: number) => new Date(ms).toISOString();
const err = (status: number, code: string, message: string): MockResponse => ({ status, body: { detail: { code, message } } });

export class HistoryMock {
  private seeds: Seed[] = [];

  constructor(private ctx: { userId: () => string; isAdmin: () => boolean; canRun: (pid: string) => boolean }) {
    this.build();
  }

  private add(id: string, type: JobType, caseId: string | null, minAgo: number, state: HistoryItem["state"], by: [string, string], extra: Extra = {}, dur = 95) {
    const created = T0 - minAgo * 60_000;
    const started = state === "QUEUED" ? null : created + 8_000;
    const finished = state === "QUEUED" || state === "RUNNING" ? null : created + 8_000 + dur * 1000;
    const c = caseId ? CASES[caseId] : null;
    const { availability: _a, reasons: _r, diff: _d, past: _p, links: _l, files_note: _f, warnings: _w, ...rest } = extra;
    void [_a, _r, _d, _p, _l, _f, _w];
    const item: HistoryItem = {
      id,
      job_type: type,
      stage: STAGE[type],
      state,
      case_id: caseId,
      case_title: c?.title ?? null,
      case_folder: c?.folder ?? null,
      analysis_id: type === "LIB_ANALYZE" ? "an-1" : null,
      comparison_id: null,
      subject_title: type === "LIB_ANALYZE" ? "SUV-A 종합분석" : null,
      created_by: by[0],
      created_by_name: by[1],
      created_at: iso(created),
      queued_at: iso(created),
      started_at: started ? iso(started) : null,
      finished_at: finished ? iso(finished) : null,
      duration_s: started && finished ? dur : null,
      wait_s: started ? 8 : null,
      current_step_no: null,
      progress_pct: state === "SUCCEEDED" ? 100 : null,
      failure_code: null,
      failure_message: null,
      retry_of_job_id: null,
      retried_by_job_id: null,
      result_ref: null,
      result_state: null,
      stale: false,
      summary: null,
      ...rest,
    };
    this.seeds.push({ item, extra });
  }

  private build() {
    const kim: [string, string] = ["u-power", "김해석"];
    const park: [string, string] = ["u-park", "박검토"];
    this.add("h-val-1", "VALIDATE", "c-demo", 12, "SUCCEEDED", kim, {
      result_ref: { kind: "validation", id: "val-1" },
      result_state: "current",
      summary: { verdict: "PASS", disp_rms_rel: 2.1e-9 },
      availability: "full",
      past: { verdict: "PASS", disp_rms_rel: 2.1e-9, reaction_rel: 4.4e-8, has_field: true },
      links: { stage: 5, query: { val: "val-1" } },
    });
    this.add("h-esl-1", "ESL_SOLVE", "c-demo", 20, "SUCCEEDED", kim, {
      result_ref: { kind: "esl_run", id: "run-1" },
      result_state: "current",
      summary: { frame_index: 7, metric: "max_strain" },
      availability: "full",
      past: { id: "run-1", job_id: "h-esl-1", frame_index: 7, time: 0.0213, metric: "max_strain", status: "READY", kabsch: { rot_deg: 1.84, rms_def: 3.412, max_def: 11.86 }, forces: { n_nodes_loaded: 7146, sum_abs_f: 2.31e6, equilibrium_rel: 2.0e-6 }, warnings: [] },
      links: { stage: 4, query: { run: "run-1" } },
    });
    this.add("h-exp-1", "EXPORT", "c-demo", 33, "SUCCEEDED", kim, {
      result_ref: { kind: "export", id: "h-exp-1" },
      result_state: "current",
      summary: { targets: ["radioss_inc", "fem", "csv"], n_files: 7 },
      availability: "full",
      past: {
        targets: ["radioss_inc", "fem", "csv"],
        id_range: [900001, 907146],
        validation_verdict: "PASS",
        files: [
          { name: "esl_cload.inc", size: 1_482_331, downloadable: true },
          { name: "esl_bcs.inc", size: 2_118, downloadable: true },
          { name: "esl_force.fem", size: 31_904_772, downloadable: true },
        ],
      },
    });
    this.add("h-val-old", "VALIDATE", "c-demo", 140, "SUCCEEDED", kim, {
      result_ref: { kind: "validation", id: "val-old" },
      result_state: "past",
      stale: true,
      summary: { verdict: "FAIL", disp_rms_rel: 3.3e-4 },
      availability: "full",
      reasons: ["tstar", "support_set"],
      past: { verdict: "FAIL", disp_rms_rel: 3.3e-4, reaction_rel: 2.0e-5, has_field: true },
      links: { stage: 5, query: { val: "val-old" } },
      diff: [
        { key: "verdict", label: "판정", past: "FAIL", current: "PASS" },
        { key: "disp_rms_rel", label: "변위 RMS (상대)", past: 3.3e-4, current: 2.1e-9 },
        { key: "hotspot_max_err", label: "hotspot 1위 오차", past: 0.31, current: 0.124 },
      ],
    });
    this.add("h-esl-old", "ESL_SOLVE", "c-demo", 150, "SUCCEEDED", kim, {
      result_ref: { kind: "esl_run", id: "run-old" },
      result_state: "past",
      stale: true,
      summary: { frame_index: 5, metric: "max_strain" },
      availability: "full",
      reasons: ["tstar", "support_set"],
      past: { id: "run-old", job_id: "h-esl-old", frame_index: 5, time: 0.0155, metric: "max_strain", status: "READY", kabsch: { rot_deg: 1.7, rms_def: 3.1, max_def: 10.2 }, forces: { n_nodes_loaded: 7146, sum_abs_f: 1.84e6, equilibrium_rel: 3.1e-4 }, warnings: [] },
      links: { stage: 4, query: { run: "run-old" } },
      diff: [
        { key: "frame_index", label: "t* 프레임", past: 5, current: 7 },
        { key: "support_node_ids", label: "지지 노드", past: [1, 120, 7081], current: [1, 120, 7000] },
        { key: "kabsch.bc_residual", label: "경계 잔차", past: 3.1e-4, current: 2.0e-6 },
        { key: "forces.total_norm", label: "하중 합 |F|", past: 184000, current: 191000 },
      ],
    });
    this.add("h-val-old2", "VALIDATE", "c-demo", 400, "SUCCEEDED", park, {
      result_ref: { kind: "validation", id: "val-old2" },
      result_state: "past",
      summary: { verdict: "PASS", disp_rms_rel: 1.2e-8 },
      availability: "summary",
      files_note: "파일 보존 안 됨 — 기록된 값만 표시",
      past: { verdict: "PASS", disp_rms_rel: 1.2e-8, reaction_rel: 9.0e-8, has_field: false },
      links: { stage: 5, query: { val: "val-old2" } },
      diff: [{ key: "disp_rms_rel", label: "변위 RMS (상대)", past: 1.2e-8, current: 2.1e-9 }],
    });
    this.add("h-ext-fail", "CASE_EXTRACT", "c-stale", 520, "FAILED", park, {
      failure_code: "EXTRACT_FAILED",
      failure_message: "h3d 파트 'chassis_rear' 를 찾지 못했습니다",
      availability: "none",
    });
    this.add("h-esl-cancel", "ESL_SOLVE", "c-stale", 560, "CANCELED", kim, { availability: "none" }, 30);
    this.add("h-ext-old", "CASE_EXTRACT", "c-demo", 700, "SUCCEEDED", kim, {
      result_ref: { kind: "extract", id: "h-ext-old" },
      result_state: "past",
      stale: true,
      summary: { n_elems: 48210, tstar_frame: 5, tstar_value: 0.1382 },
      availability: "summary",
      reasons: ["extract"],
      past: { extract: { part_title: "chassis_rear", n_elems: 48210, n_frames: 31 }, tstar: { frame_index: 5, metric: "max_strain", value: 0.1382, time: 0.0155 } },
      diff: [
        { key: "n_elems", label: "요소 수", past: 48210, current: 48376 },
        { key: "tstar.frame_index", label: "t* 프레임", past: 5, current: 7 },
        { key: "tstar.value", label: "t* 값", past: 0.1382, current: 0.1418 },
      ],
    }, 410);
    this.add("h-rep-old", "CASE_REPORT", "c-demo", 760, "SUCCEEDED", kim, {
      result_ref: { kind: "report", id: "h-rep-old" },
      result_state: "past",
      availability: "full",
      past: { verdict: "PASS", bytes: 482_331 },
    });
    this.add("h-exp-old", "EXPORT", "c-demo", 160, "SUCCEEDED", kim, {
      result_ref: { kind: "export", id: "h-exp-old" },
      result_state: "past",
      summary: { targets: ["radioss_inc"], n_files: 2 },
      availability: "summary",
      past: {
        targets: ["radioss_inc"],
        id_range: [900001, 907000],
        validation_verdict: "PASS",
        files: [
          { name: "esl_cload.inc", size: null, downloadable: false },
          { name: "esl_bcs.inc", size: null, downloadable: false },
        ],
        warnings: [],
      },
      links: { stage: 6 },
    });
    this.add("h-canceled", "ESL_SOLVE", "c-demo", 170, "CANCELED", kim, { warnings: ["사용자가 취소함"] }, 12);
    this.add("h-lib-1", "LIB_ANALYZE", null, 900, "SUCCEEDED", park, {
      result_ref: { kind: "analysis", id: "an-1" },
      result_state: "past",
      availability: "summary",
      past: { n_entries: 12, n_representative: 5 },
      links: { stage: 8, query: { analysis: "an-1" } },
    }, 260);
    // 오래된 추출·ESL·검증 반복(더 보기 시험용)
    const types: JobType[] = ["CASE_EXTRACT", "ESL_SOLVE", "VALIDATE"];
    for (let k = 0; k < 40; k++) {
      const t = types[k % 3];
      const cid = k % 2 ? "c-stale" : "c-demo";
      this.add(`h-old-${k + 1}`, t, cid, 1000 + k * 55, k % 7 === 3 ? "FAILED" : "SUCCEEDED", k % 4 ? kim : park, {
        failure_code: k % 7 === 3 ? "SOLVER_ERROR" : null,
        failure_message: k % 7 === 3 ? "계산이 중단되었습니다" : null,
        availability: k % 7 === 3 ? "none" : "summary",
        result_ref: k % 7 === 3 ? null : { kind: t === "CASE_EXTRACT" ? "extract" : t === "ESL_SOLVE" ? "esl_run" : "validation", id: `old-${k + 1}` },
        result_state: k % 7 === 3 ? null : "past",
        summary: k % 7 === 3 ? null : t === "CASE_EXTRACT" ? { n_elems: 48000 + k, tstar_frame: 5, tstar_value: 0.13 } : t === "ESL_SOLVE" ? { frame_index: 5, metric: "max_strain" } : { verdict: "PASS", disp_rms_rel: 1e-8 },
        past: { note: "예전 실행" },
      }, 40 + k);
    }
    this.seeds.sort((a, b) => (a.item.created_at < b.item.created_at ? 1 : a.item.created_at > b.item.created_at ? -1 : a.item.id < b.item.id ? 1 : -1));
    // 재시도 연결: 실패 추출 → 이후 성공 추출
    const f = this.seeds.find((s) => s.item.id === "h-ext-fail")!;
    f.item.retried_by_job_id = "h-ext-old";
    this.seeds.find((s) => s.item.id === "h-ext-old")!.item.retry_of_job_id = "h-ext-fail";
  }

  /** 읽기 전용 열람용 과거 ESL run·검증(현재 Case 의 목록·상태에는 섞이지 않게 이 목에서만 응답) */
  private past() {
    const run: EslRunOut = { ...makeEslRun("run-old", "c-demo", "ss-1", 5, 0.05), job_id: "h-esl-old", created_at: "2026-10-20T06:30:00Z", is_current: false, stale: true, latest_validation_id: "val-old" };
    const vals: ValidationOut[] = [
      { ...makeValidation("val-old", "run-old", "c-demo"), job_id: "h-val-old", verdict: "FAIL", fail_reasons: ["HOTSPOT_STRAIN"], disp_rms_rel: 3.3e-4, reaction_rel: 2.0e-5, created_at: "2026-10-20T06:40:00Z", stale: true, field: makeFieldSummary() },
      { ...makeValidation("val-old2", "run-old", "c-demo"), job_id: "h-val-old2", disp_rms_rel: 1.2e-8, created_at: "2026-10-20T02:20:00Z", stale: true, field: null },
    ];
    return { run, vals };
  }

  private pastHandle(method: string, path: string, query: URLSearchParams): MockResponse | null {
    if (method !== "GET") return null;
    const { run, vals } = this.past();
    let r: RegExpMatchArray | null;
    if ((r = path.match(/^\/esl-runs\/run-old(\/forces)?$/)))
      return { status: 200, body: r[1] ? { esl_run_id: run.id, n_nodes: N_NODES, rows: makeForces().slice(0, Number(query.get("top") ?? 50)) } : run };
    if ((r = path.match(/^\/validations\/(val-old2?)(\/field|\/section)?$/))) {
      const v = vals.find((x) => x.id === r![1])!;
      if (!r[2]) return { status: 200, body: v };
      if (!v.field) return err(409, "VALIDATION_FILES_GONE", "검증 파일이 보존되어 있지 않습니다.");
      if (r[2] === "/field") return { status: 200, body: makeField(v.id, (query.get("layer") ?? "rad") as FieldLayer, Number(query.get("max_points") ?? 20000) || 20000) };
      return { status: 200, body: makeSection(v.id, (query.get("axis") ?? "xi") as SectionAxis, Number(query.get("at") ?? 0.5)) };
    }
    return null;
  }

  private matches(it: HistoryItem, q: URLSearchParams): boolean {
    const types = (q.get("job_type") ?? "").split(",").filter(Boolean);
    const states = (q.get("state") ?? "").split(",").filter(Boolean);
    if (q.get("case_id") && it.case_id !== q.get("case_id")) return false;
    if (types.length && !types.includes(it.job_type)) return false;
    if (states.length && !states.includes(it.state)) return false;
    if (q.get("mine") === "true" && it.created_by !== this.ctx.userId()) return false;
    const text = (q.get("q") ?? "").toLowerCase();
    if (text && !`${it.case_title ?? ""} ${it.case_folder ?? ""} ${it.subject_title ?? ""}`.toLowerCase().includes(text) && !(text.length >= 8 && it.id.startsWith(text))) return false;
    const from = q.get("from");
    const to = q.get("to");
    if (from && Date.parse(it.created_at) < Date.parse(from)) return false;
    if (to && Date.parse(it.created_at) > Date.parse(to)) return false;
    return true;
  }

  review(seed: Seed): ReviewOut {
    const { item: it, extra } = seed;
    const steps = STEPS[it.job_type].map((key, i) => ({
      step_no: i + 1,
      step_key: key,
      kind: "CORE",
      core_stage: null,
      state: it.state === "FAILED" && i === 0 ? "FAILED" : it.state === "CANCELED" ? "CANCELED" : "SUCCEEDED",
      progress_pct: 100,
      exit_code: it.state === "FAILED" && i === 0 ? 2 : 0,
      failure_code: it.state === "FAILED" && i === 0 ? it.failure_code : null,
      failure_message: it.state === "FAILED" && i === 0 ? it.failure_message : null,
      started_at: it.started_at,
      finished_at: it.finished_at,
      ...(this.ctx.isAdmin() ? { command: ["python", "-m", "esl_core", key.toLowerCase(), "--case", it.case_folder ?? "-"] } : {}),
    }));
    const job = {
      id: it.id,
      case_id: it.case_id,
      analysis_id: it.analysis_id,
      comparison_id: it.comparison_id,
      project_id: PROJECT,
      job_type: it.job_type,
      stage: it.stage,
      lane: "SLOT",
      state: it.state,
      params: {},
      result: null,
      warnings: [],
      cancel_requested: false,
      current_step_no: null,
      progress_pct: it.progress_pct,
      queue_position: null,
      queued_at: it.queued_at,
      started_at: it.started_at,
      finished_at: it.finished_at,
      failure_code: it.failure_code,
      failure_message: it.failure_message,
      retry_of_job_id: it.retry_of_job_id,
      resume_from_step: null,
      created_by: it.created_by,
      created_by_name: it.created_by_name,
      created_at: it.created_at,
      updated_at: it.finished_at ?? it.created_at,
      version: 1,
      steps,
    } as unknown as ReviewOut["job"];
    const params: Record<string, unknown> =
      it.job_type === "ESL_SOLVE" ? { frame_index: (it.summary?.frame_index as number) ?? 5, metric: "max_strain" }
      : it.job_type === "VALIDATE" ? { esl_run_id: "run-1" }
      : it.job_type === "EXPORT" ? { esl_run_id: "run-1", targets: ["radioss_inc", "fem", "csv"] }
      : it.job_type === "CASE_EXTRACT" ? { part_title: "chassis_rear" }
      : {};
    const res: ReviewResult = {
      ref: it.result_ref,
      availability: extra.availability ?? "none",
      state: it.result_state,
      stale_reasons: extra.reasons ?? [],
      files_note: extra.files_note ?? (extra.availability === "summary" ? "파일 보존 안 됨 — 기록된 값만 표시" : null),
      past: extra.past ?? {},
      diff: extra.diff ?? [],
      links: extra.links ?? {},
    };
    return {
      job,
      timing: {
        queued_at: it.queued_at,
        started_at: it.started_at,
        finished_at: it.finished_at,
        wait_s: it.wait_s,
        duration_s: it.duration_s,
        steps: steps.map((s) => ({ step_no: s.step_no, step_key: s.step_key, started_at: s.started_at, finished_at: s.finished_at, duration_s: it.duration_s === null ? null : Math.round(it.duration_s / steps.length) })),
      },
      input: {
        params,
        settings_summary: { criteria: { disp_rms_rel_max: 1e-6, hotspot_strain_rel_err_max: 0.2, reaction_rel_max: 1e-5 }, tstar_metric: "max_strain", material_override: {} },
        input_fingerprint: it.job_type === "CASE_EXTRACT" ? [{ kind: "h3d", path: "h3d/chassis_rear.h3d", size: 812_331_902, mtime: Date.UTC(2026, 9, 12, 5, 40) / 1000 }, { kind: "result", path: null, size: null, mtime: null }] : null,
      },
      error: {
        failure_code: it.failure_code,
        failure_message: it.failure_message,
        failed_step: it.state === "FAILED" ? { step_no: 1, step_key: steps[0].step_key, exit_code: 2, failure_code: it.failure_code, failure_message: it.failure_message } : null,
        warnings: extra.warnings ?? [],
      },
      logs: steps.map((s) => ({ step_no: s.step_no, step_key: s.step_key, state: s.state, has_log: it.state !== "QUEUED", size: 1840 })),
      result: res,
    };
  }

  handle(method: string, path: string, query: URLSearchParams): MockResponse | null {
    const ph = this.pastHandle(method, path, query);
    if (ph) return ph;
    if (method === "GET" && path === "/history") {
      const pid = query.get("project_id");
      if (!pid) return err(422, "VALIDATION_ERROR", "project_id 가 필요합니다.");
      if (pid !== PROJECT) return { status: 200, body: { items: [], next_cursor: null, has_more: false } };
      const limit = Number(query.get("limit") ?? 50);
      if (!Number.isInteger(limit) || limit < 1 || limit > 200) return err(422, "VALIDATION_ERROR", "limit 은 1~200 입니다.");
      let start = 0;
      const cur = query.get("cursor");
      if (cur) {
        const n = Number(atob(cur.replace(/-/g, "+").replace(/_/g, "/")).replace(/^o:/, ""));
        if (!Number.isInteger(n) || n < 0) return err(422, "INVALID_CURSOR", "커서가 올바르지 않습니다.");
        start = n;
      }
      const all = this.seeds.filter((s) => this.matches(s.item, query));
      const page = all.slice(start, start + limit);
      const nxt = start + limit;
      const has = nxt < all.length;
      return {
        status: 200,
        body: { items: page.map((s) => s.item), next_cursor: has ? btoa(`o:${nxt}`).replace(/\+/g, "-").replace(/\//g, "_") : null, has_more: has },
      };
    }
    let r: RegExpMatchArray | null;
    if ((r = path.match(/^\/jobs\/(h-[^/]+)(\/review|\/log|\/retry)$/))) {
      const seed = this.seeds.find((s) => s.item.id === r![1]);
      if (!seed) return err(404, "JOB_NOT_FOUND", "작업을 찾을 수 없습니다.");
      if (method === "GET" && r[2] === "/review") return { status: 200, body: this.review(seed) };
      if (method === "GET" && r[2] === "/log") {
        const step = Number(query.get("step") ?? 1) || 1;
        const key = STEPS[seed.item.job_type][step - 1] ?? "STEP";
        const lines = [`[${key}] 시작`, `[${key}] 입력 확인 완료`, `[${key}] 진행 50%`, seed.item.state === "FAILED" ? `[${key}] 오류: ${seed.item.failure_message}` : `[${key}] 완료`];
        // 실제 서버처럼 한 번에 일부만(여기서는 2줄) 주고 next_cursor·eof 로 잇는다
        const from = Math.max(0, Number(query.get("cursor") ?? 0) || 0);
        const part = lines.slice(from, from + 2);
        return { status: 200, body: { step, lines: part, next_cursor: from + part.length, eof: from + part.length >= lines.length } };
      }
      if (method === "POST" && r[2] === "/retry") {
        if (!this.ctx.canRun(PROJECT)) return err(403, "FORBIDDEN", "권한이 없습니다.");
        return { status: 201, body: { id: "j-retry-1", state: "QUEUED", job_type: seed.item.job_type } };
      }
    }
    if (method === "GET" && (r = path.match(/^\/jobs\/(h-[^/]+)\/files$/))) {
      const seed = this.seeds.find((s) => s.item.id === r![1]);
      const files = seed?.extra.past?.files;
      return Array.isArray(files) ? { status: 200, body: files } : err(404, "HISTORY_FILES_GONE", "보관된 파일이 없습니다.");
    }
    if (method === "GET" && /^\/jobs\/h-[^/]+\/report$/.test(path)) return { status: 200, body: "<!doctype html><title>보고서</title><h1>Case 보고서(보관본)</h1>" };
    return null;
  }
}
