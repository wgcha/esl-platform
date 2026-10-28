// v0.7.0 비드 최적화 목 API(계약 esl_opt_run.md §5). MockServer.handle 이 /opt/* 를 여기로 넘긴다.
// 결과(하중 선정·OptResult)는 실행 입력에서 결정적으로 만든다 — 작업 단계(OPT_LOAD·완료)에 따라 채워 응답.
import type {
  DeformMode, EntryOut, JobOut, KeepoutAuto, KeepoutRect, KeepoutSetOut, LoadSelection, LoadSelectionRow, LoadStrategy, Me, MeshCheckOut, ObjectiveNorm,
  OptFileOut, OptMethodSources, OptResult, OptRunIn, OptRunOut, OptSettingsOut, PlanViewOut, S1CheckBase, S1CheckOut, TemplateOut, XY,
} from "../api/types";

interface MockResponse {
  status: number;
  body?: unknown;
}
const err = (status: number, code: string, message: string, extra: Record<string, unknown> = {}): MockResponse => ({ status, body: { detail: { code, message, ...extra } } });
const ok = (body: unknown, status = 200): MockResponse => ({ status, body });

export interface OptCtx {
  entries: () => EntryOut[];
  me: () => Me;
  canRun: (projectId: string) => boolean;
  /** OPT_RUN 작업 생성(대기열) */
  newJob: (projectId: string, params: Record<string, unknown>) => JobOut;
  jobs: () => JobOut[];
  now: () => string;
  /** 업로드 상태: null = 없음, files = 받은 파일(rel), ready = 다 받음 */
  upload: (id: string) => { project_id: string; ready: boolean; files: string[]; state: string } | null;
  markUploadCompleted: (id: string) => void;
}

// ---------------------------------------------------------------- 설정·방법 출처(§9.1 초기 내용)
export const METHOD_SOURCES: OptMethodSources = {
  version: "1",
  summary_ko: [
    "각 ESL(t* 한 시점)을 하중 케이스 1개로 씁니다.",
    "초기 형상에서 계산한 컴플라이언스로 하중을 고르고, 가장 큰 컴플라이언스를 최소화(min-max)합니다.",
    "형상 유사도 |MAC| 는 부호와 무관해 반대 방향 하중을 같은 하중으로 봅니다.",
  ],
  strategies: {
    A: "KIT 식: 선택 ESL 전부, 형상이 거의 같은 하중(|MAC| ≥ 0.95)만 병합, 20개 초과 시 군집 대표",
    B: "모드 대표: 덴팅·뒤틀림·굽힘별 최악 1개(최대 3개)",
    C: "군집 대표: 형상 유사도로 k개 묶음, 묶음별 최악 1개",
  },
  objective_norms: {
    abs: "절대 기준(추천): 가장 큰 컴플라이언스를 줄임, 공통 상수로만 나눠 큰 하중의 비중 유지",
    rel: "상대 기준: 각 하중을 자기 초기값 대비 같은 비율로 개선",
  },
  sources: [
    { title: "Altair OptiStruct — Equivalent Static Load Method (ESLM)", url: "https://help.altair.com/2024/hwsolvers/os/topics/solvers/os/opt_composite_equiv_static_load_method_c.htm" },
    { title: "Structural optimization using equivalent static loads at all time intervals", authors: "Park, G.J., Kang, B.S. 외", note: "서지만" },
    { title: "KIT 비드/토포그래피 최적화 문헌", url: "https://publikationen.bibliothek.kit.edu/1000137417/126578473" },
  ],
};

export function makeOptSettings(): OptSettingsOut {
  return {
    enabled: true,
    solver_ready: true,
    solver_reason: null,
    size: { tol_rel: 0.02, plate_tol_rel: 0.05, require_inch: true },
    bead_defaults: { angle: 45, min_width: 60, height: 10 },
    keepout_auto: { hole_radius_mm: 15, edge_band_mm: 10 },
    loads: { default_objective_norm: "abs", default_strategy: "A", mac_merge: 0.95, max_cases: 20, default_k: 5 },
    method_sources: METHOD_SOURCES,
    max_rects: 20,
    max_entries: 200,
    template_max_elems: 500000,
    template_ext: [".rad", ".inc", ".fem"],
  };
}

// ---------------------------------------------------------------- 라이브러리 항목 보강(size·topo·deform_mode)
const DIMS: Record<number, [number, number]> = { 75: [1662, 948], 65: [1452, 826], 85: [1880, 1072] };
/** 항목 순서별 자동 모드(분류 불가 = null) + 사용자 수정 */
const AUTO_MODES: (DeformMode | null)[] = ["bend", "twist", "bend", "dent", "twist", "bend", "dent", "bend", "bend", "twist", "dent"];

export function enrichEntries(entries: EntryOut[]) {
  entries.forEach((e, k) => {
    const inch = e.model.inch ?? null;
    const d = inch != null ? DIMS[inch] : undefined;
    const jitter = 1 + ((k % 3) - 1) * 0.0015;
    e.size = { inch, L_xi: d ? +(d[0] * jitter).toFixed(1) : null, L_eta: d ? +(d[1] * jitter).toFixed(1) : null };
    e.topo_sha256 = e.model.name ? `topo-${e.model.name}-${e.model.version ?? "?"}`.padEnd(64, "0") : null;
    const auto = AUTO_MODES[k % AUTO_MODES.length];
    const user: DeformMode | null = k === 2 ? "twist" : null;
    e.deform_mode = { auto, user, effective: user ?? auto, metrics: { bend: 0.6, twist: 0.25, resid: 0.15, kappa: 0.3 } };
  });
}

// ---------------------------------------------------------------- 평면도(PlanViewOut)
const circle = (cx: number, cy: number, r: number, n = 20): XY[] => Array.from({ length: n }, (_, i) => [+(cx + r * Math.cos((2 * Math.PI * i) / n)).toFixed(1), +(cy + r * Math.sin((2 * Math.PI * i) / n)).toFixed(1)] as XY);

export function makePlanView(L: number, H: number, holeR = 15, edge = 10): PlanViewOut {
  const outline: XY[] = [
    [0, 0],
    [L, 0],
    [L, H],
    [0, H],
  ];
  const cx = L / 2;
  const cy = H / 2;
  const centers: XY[] = [
    [cx - 200, cy - 150],
    [cx + 200, cy - 150],
    [cx - 200, cy + 150],
    [cx + 200, cy + 150],
    [L * 0.15, H * 0.82],
    [L * 0.85, H * 0.82],
  ];
  const holes = centers.map(([x, y]) => circle(x, y, 4));
  const points: [number, number, number][] = [];
  const step = Math.max(L, H) / 48;
  for (let a = step / 2; a < L; a += step) for (let b = step / 2; b < H; b += step) points.push([+a.toFixed(1), +b.toFixed(1), Math.abs(a - cx) < 260 && Math.abs(b - cy) < 200 ? 2 : 1]);
  const polygons: XY[][] = [
    outline,
    [
      [edge, edge],
      [L - edge, edge],
      [L - edge, H - edge],
      [edge, H - edge],
    ],
    ...centers.map(([x, y]) => circle(x, y, 4 + holeR)),
  ];
  return {
    frame: { a_range: [0, L], b_range: [0, H] },
    outline,
    holes,
    elems: { n_total: 223415, decimated: true, points },
    auto_keepout: { hole_radius_mm: holeR, edge_band_mm: edge, polygons, kinds: ["edge", "edge", ...centers.map(() => "hole" as const)] },
  };
}

// ---------------------------------------------------------------- 하중 선정(§7.4 흉내 — 결정적)
const DROP_C: Record<string, number> = { Corner: 1.23e4, Edge: 8.7e3, Face: 5.1e3 };

export function sceneOf(e: EntryOut) {
  const s = e.scene;
  return `${e.model.name ?? "?"} ${e.model.version ?? ""} · ${s.seq ?? "?"} ${s.drop_type ?? "?"} ${s.orient ?? ""}`.replace(/\s+/g, " ").trim();
}
const c0Of = (e: EntryOut) => +(((DROP_C[e.scene.drop_type ?? "Face"] ?? 6e3) * (1 + 0.07 * ((e.scene.seq ?? 0) % 5)) * (e.model.version === "v073" ? 0.93 : 1)).toPrecision(4));
const modeOf = (e: EntryOut) => e.deform_mode?.effective ?? null;
/** 목 |MAC|: 같은 모드면 0.96(같은 씬 유형이면 0.98) → 병합, 다르면 0.3 */
function mac(a: EntryOut, b: EntryOut) {
  if (modeOf(a) && modeOf(a) === modeOf(b)) return a.scene.drop_type === b.scene.drop_type ? 0.98 : 0.96;
  return 0.3;
}
const signOf = (a: EntryOut, b: EntryOut): 1 | -1 => (((a.scene.orient ?? "").length + (b.scene.orient ?? "").length) % 2 ? -1 : 1);

export function makeSelection(es: EntryOut[], strategy: LoadStrategy, k: number | null, norm: ObjectiveNorm, macMerge = 0.95, maxCases = 20): LoadSelection {
  const sorted = [...es].sort((a, b) => c0Of(b) - c0Of(a) || a.id.localeCompare(b.id));
  const rows: LoadSelectionRow[] = sorted.map((e) => ({
    entry_id: e.id,
    scene: sceneOf(e),
    mode: modeOf(e),
    C0: c0Of(e),
    pos: null,
    umax: +(Math.sqrt(c0Of(e)) / 27).toFixed(2),
    status: "not_selected",
    merged_into: null,
    mac_to_target: null,
    sign: null,
    cluster: null,
    label: null,
  }));
  const byId = new Map(es.map((e) => [e.id, e]));
  const clusters: LoadSelection["clusters"] = [];
  let excluded: DeformMode[] = [];
  if (strategy === "A") {
    const kept: LoadSelectionRow[] = [];
    for (const r of rows) {
      const e = byId.get(r.entry_id)!;
      let best: LoadSelectionRow | null = null;
      let bm = 0;
      for (const t of kept) {
        const m = mac(e, byId.get(t.entry_id)!);
        if (m >= macMerge && m > bm) {
          best = t;
          bm = m;
        }
      }
      if (best) Object.assign(r, { status: "merged", merged_into: best.entry_id, mac_to_target: bm, sign: signOf(e, byId.get(best.entry_id)!) });
      else {
        r.status = "included";
        kept.push(r);
      }
    }
    if (kept.length > maxCases) kept.slice(maxCases).forEach((r) => (r.status = "clustered"));
  } else if (strategy === "B") {
    const modes: DeformMode[] = ["dent", "twist", "bend"];
    for (const m of modes) {
      const rep = rows.find((r) => r.mode === m);
      if (rep) rep.status = "mode_rep";
    }
    excluded = modes.filter((m) => !rows.some((r) => r.mode === m));
  } else {
    // C: 키(모드|씬 유형) 묶음을 k 개로 맞춤(작은 묶음 병합·큰 묶음 분할)
    const kk = Math.min(k ?? 5, rows.length);
    const groups = new Map<string, LoadSelectionRow[]>();
    for (const r of rows) {
      const key = `${r.mode}|${byId.get(r.entry_id)!.scene.drop_type}`;
      groups.set(key, [...(groups.get(key) ?? []), r]);
    }
    const gs = [...groups.values()];
    while (gs.length > kk) {
      gs.sort((a, b) => b.length - a.length);
      const last = gs.pop()!;
      gs[gs.length - 1].push(...last);
    }
    while (gs.length < kk) {
      gs.sort((a, b) => b.length - a.length);
      gs.push([gs[0].pop()!]);
    }
    gs.sort((a, b) => Math.max(...b.map((r) => r.C0)) - Math.max(...a.map((r) => r.C0)));
    gs.forEach((g, i) => {
      g.sort((a, b) => b.C0 - a.C0);
      g.forEach((r, j) => {
        r.cluster = i + 1;
        r.status = j === 0 ? "cluster_rep" : "clustered";
      });
      clusters.push({ id: i + 1, rep_entry_id: g[0].entry_id, members: g.map((r) => r.entry_id), min_mac: g.length > 1 ? 0.8 : 1 });
    });
  }
  const sel = rows.filter((r) => r.status === "included" || r.status === "cluster_rep" || r.status === "mode_rep");
  const cref = sel.length ? Math.max(...sel.map((r) => r.C0)) : null;
  sel.forEach((r, i) => {
    r.label = `L${String(i + 1).padStart(2, "0")}`;
    r.pos = norm === "abs" ? cref : r.C0;
  });
  return {
    strategy,
    objective_norm: norm,
    C_ref: norm === "abs" ? cref : null,
    k: strategy === "C" ? k : null,
    mac_merge: strategy === "A" ? macMerge : null,
    max_cases: maxCases,
    n_selected_esl: es.length,
    n_cases: sel.length,
    rows,
    clusters,
    excluded_modes: excluded,
    sources_ref: `opt_method_sources/${METHOD_SOURCES.version}`,
  };
}

export function makeOptResult(sel: LoadSelection, bead: { height: number }, keepoutRects: number, scenario: "S1" | "S2"): OptResult {
  const sub = sel.rows.filter((r) => r.label);
  const n = 18;
  const fin = 0.71;
  const history = Array.from({ length: n + 1 }, (_, i) => +(fin + (1 - fin) * Math.exp(-i / 4)).toFixed(4));
  return {
    load_selection: sel,
    objective_norm: sel.objective_norm,
    C_ref: sel.C_ref,
    converged: true,
    iterations: n,
    desmax: 30,
    objective: { initial: history[0], final: history[n], history },
    subcases: sub.map((r, i) => {
      const ratio = +(0.64 + 0.03 * i).toFixed(3);
      return { label: r.label!, entry_id: r.entry_id, C0_self: r.C0, C0_os: +(r.C0 * 1.018).toPrecision(4), C_final: +(r.C0 * 1.018 * ratio).toPrecision(4), ratio };
    }),
    keepout: { n_elems_auto_hole: 1844, n_elems_auto_edge: 6120, n_elems_rects: 2400 * keepoutRects, n_design_elems: 205000 - 2400 * keepoutRects },
    bead: { height_max: bead.height, area_frac: 0.34 },
    normals_opposite: scenario === "S1" ? 12 : null,
    normals_flipped: scenario === "S2" ? 0 : null,
    solve: { seconds: 5412, license_waits: 0, reused: false },
    warnings: scenario === "S1" ? ["반대 법선 요소 12개 — 원 연결 유지(비드 방향은 요소 법선 쪽)"] : [],
  };
}

// ---------------------------------------------------------------- 목 서버
interface Run {
  id: string;
  project_id: string;
  scenario: "S1" | "S2";
  title: string | null;
  entry_ids: string[];
  analysis_id: string | null;
  template_id: string | null;
  base: S1CheckBase | null;
  design: OptRunIn["design"];
  load_strategy: LoadStrategy;
  k: number | null;
  objective_norm: ObjectiveNorm;
  created_by_name: string;
  created_at: string;
  /** 시연용: 이 실행의 작업을 처음부터 이 상태로 */
  seededJob?: JobOut;
}

const PIDS_S1 = [
  { pid: 1, title: "rear_cover_t0.8", n_elems: 212000, thickness: 0.8, E: 210000, nu: 0.3 },
  { pid: 2, title: "boss_t1.6", n_elems: 11415, thickness: 1.6, E: 210000, nu: 0.3 },
];
const SUPPORTS = [
  { node_id: 100231, dof: "123" },
  { node_id: 100877, dof: "23" },
  { node_id: 104410, dof: "3" },
];

export class OptMock {
  settings = makeOptSettings();
  templates: (TemplateOut & { created_by: string })[] = [];
  keepouts = new Map<string, KeepoutSetOut>();
  runs: Run[] = [];
  seq = 0;

  constructor(private ctx: OptCtx) {}

  private id(p: string) {
    this.seq += 1;
    return `${p}-${this.seq}`;
  }

  seed() {
    const t = (id: string, title: string, inch: number | null, L: number, H: number, format: "rad" | "fem", by: string, byName: string, status: "ACTIVE" | "ARCHIVED", n_runs: number): TemplateOut & { created_by: string } => ({
      id,
      title,
      inch,
      description: status === "ARCHIVED" ? "이전 판(보관)" : "평판 템플릿 — 구멍 6개",
      format,
      file_name: `${title.replace(/\s+/g, "_")}.${format}`,
      part_title: format === "rad" ? "plate" : null,
      sha256: `${id}`.padEnd(64, "a"),
      n_nodes: 48210,
      n_elems: 47600,
      L_xi: L,
      L_eta: H,
      z_range: 0.4,
      pids: [{ pid: 1, title: "plate_t0.8", n_elems: 47600, thickness: 0.8, E: 210000, nu: 0.3 }],
      quality_warnings: format === "fem" ? ["셀당 노드 중앙값 58 < 64 (매핑 해상도)"] : [],
      status,
      n_runs,
      created_by_name: byName,
      created_at: "2026-10-27T05:00:00Z",
      can_delete: false,
      created_by: by,
    });
    this.templates = [
      t("tpl-1", "75형 평판 v1", 75, 1660, 950, "fem", "u-power", "김해석", "ACTIVE", 3),
      t("tpl-2", "65형 평판 v2", 65, 1450, 828, "rad", "u-admin", "관리자", "ACTIVE", 0),
      t("tpl-3", "75형 평판 v0", 75, 1655, 945, "fem", "u-power", "김해석", "ARCHIVED", 1),
    ];
    // 75QN80H v072 모델(topo)에 저장된 금지 영역 세트
    const e1 = this.ctx.entries().find((e) => e.id === "le-1");
    if (e1?.topo_sha256)
      this.keepouts.set(`topo:${e1.topo_sha256}`, {
        id: "ko-1",
        key: { topo_sha256: e1.topo_sha256 },
        version: 3,
        rects: [{ name: "PCB", corner: "a0b0", x_mm: 120, y_mm: 80, w_mm: 300, h_mm: 200 }],
        auto: { hole: true, edge: true },
        frame: { a_range: [0, e1.size?.L_xi ?? 1662], b_range: [0, e1.size?.L_eta ?? 948] },
        updated_by_name: "차완기",
        updated_at: "2026-10-28T02:10:00Z",
      });
    // 완료된 S1 실행 1개
    const r = this.makeRun({
      project_id: "p-body",
      scenario: "S1",
      title: "75형 강건 비드 1차",
      entry_ids: ["le-1", "le-2", "le-3"],
      design: { bead: { angle: 45, min_width: 60, height: 10 }, keepout: { rects: [{ name: "PCB", corner: "a0b0", x_mm: 120, y_mm: 80, w_mm: 300, h_mm: 200 }], auto: { hole: true, edge: true } } },
      options: { load_strategy: "A", objective_norm: "abs" },
    });
    r.id = "opt-1";
    r.created_at = "2026-10-28T03:00:00Z";
    this.seq = 10; // 새 id(tpl-11, opt-12 …)가 시드 id 와 겹치지 않게
    // 완료 작업은 서버 작업 목록(대기열·시험 순서)에 섞지 않고 여기만 둔다
    r.seededJob = doneJob("j-opt-seed", r.project_id, r.id);
    this.runs.push(r);
  }

  private s1Base(e: EntryOut): S1CheckBase {
    return {
      entry_id: e.id,
      case_id: e.case_id,
      case_title: e.case_title ?? null,
      part_title: (e.model.part_title as string | null | undefined) ?? "rear_cover",
      rad_file_name: `${e.model.name ?? "model"}_${e.model.version ?? ""}_0000.rad`,
      n_nodes: 224120,
      n_elems: 223415,
      topo_sha256: e.topo_sha256 ?? "",
      pids: PIDS_S1,
      supports: SUPPORTS,
    };
  }

  private makeRun(b: OptRunIn): Run {
    const es = this.ctx.entries();
    const first = es.find((e) => e.id === b.entry_ids[0]);
    const strategy = b.options.load_strategy ?? this.settings.loads.default_strategy;
    return {
      id: this.id("opt"),
      project_id: b.project_id,
      scenario: b.scenario,
      title: b.title?.trim() || null,
      entry_ids: [...b.entry_ids],
      analysis_id: b.analysis_id ?? null,
      template_id: b.scenario === "S2" ? b.template_id ?? null : null,
      base: b.scenario === "S1" && first ? this.s1Base(first) : null,
      design: { nondesign_pids: b.design.nondesign_pids ?? [], bead: b.design.bead ?? this.settings.bead_defaults, keepout: b.design.keepout },
      load_strategy: strategy,
      k: strategy === "C" ? b.options.k ?? this.settings.loads.default_k : null,
      objective_norm: b.options.objective_norm ?? this.settings.loads.default_objective_norm,
      created_by_name: this.ctx.me().display_name,
      created_at: this.ctx.now(),
    };
  }

  private jobOf(r: Run): JobOut | null {
    const js = this.ctx.jobs().filter((j) => j.params.opt_run_id === r.id);
    return js[js.length - 1] ?? r.seededJob ?? null;
  }

  private selection(r: Run) {
    const es = this.ctx.entries().filter((e) => r.entry_ids.includes(e.id));
    return makeSelection(es, r.load_strategy, r.k, r.objective_norm, this.settings.loads.mac_merge, this.settings.loads.max_cases);
  }

  runOut(r: Run): OptRunOut {
    const j = this.jobOf(r);
    const state = j?.state ?? "QUEUED";
    const loadDone = !!j?.steps?.find((s) => s.step_key === "OPT_LOAD" && s.state === "SUCCEEDED");
    const sel = loadDone ? this.selection(r) : null;
    const done = state === "SUCCEEDED";
    const tpl = r.template_id ? this.templates.find((t) => t.id === r.template_id) : undefined;
    const first = this.ctx.entries().find((e) => e.id === r.entry_ids[0]);
    return {
      id: r.id,
      project_id: r.project_id,
      scenario: r.scenario,
      title: r.title,
      entry_ids: r.entry_ids,
      analysis_id: r.analysis_id,
      base: r.base,
      template: tpl ? { id: tpl.id, title: tpl.title, inch: tpl.inch, L_xi: tpl.L_xi, L_eta: tpl.L_eta, status: tpl.status } : null,
      size: first?.size ? { inch: first.size.inch, L_xi: first.size.L_xi, L_eta: first.size.L_eta } : null,
      design: r.design,
      load_strategy: r.load_strategy,
      k: r.k,
      objective_norm: r.objective_norm,
      job: j,
      state,
      created_by_name: r.created_by_name,
      created_at: r.created_at,
      result: sel ? (done ? makeOptResult(sel, r.design.bead ?? { height: 10 }, r.design.keepout.rects.length, r.scenario) : ({ load_selection: sel } as OptResult)) : null,
      report_ready: done,
    };
  }

  private templateOut(t: TemplateOut & { created_by: string }): TemplateOut {
    const me = this.ctx.me();
    const { created_by, ...rest } = t;
    return { ...rest, can_delete: me.is_global_admin || created_by === me.user_id };
  }

  private anyPower() {
    const me = this.ctx.me();
    return me.is_global_admin || Object.values(me.roles).some((r) => r === "power" || r === "admin");
  }

  handle(method: string, path: string, query: URLSearchParams, b: Record<string, unknown>): MockResponse | null {
    if (!path.startsWith("/opt/")) return null;
    let r: RegExpMatchArray | null;
    const es = this.ctx.entries();
    if (method === "GET" && path === "/opt/settings") return ok(this.settings);

    // ---- 템플릿
    if (method === "POST" && path === "/opt/templates/check") {
      if (!this.ctx.canRun(String(b.project_id ?? ""))) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
      const u = this.ctx.upload(String(b.upload_id ?? ""));
      if (!u) return err(404, "UPLOAD_NOT_FOUND", "업로드를 찾을 수 없습니다.");
      if (!u.ready) return err(409, "UPLOAD_NOT_READY", "업로드가 아직 끝나지 않았습니다.");
      const main = u.files.find((f) => /\.(fem|rad)$/i.test(f));
      if (!main) return err(422, "MESH_FORMAT_UNSUPPORTED", "`.rad` 또는 `.fem` 쉘 메시만 등록할 수 있습니다.");
      this.ctx.markUploadCompleted(String(b.upload_id));
      const format = /\.fem$/i.test(main) ? "fem" : "rad";
      const out: MeshCheckOut = {
        ok: true,
        sha256: `sha-${b.upload_id}`.padEnd(64, "b"),
        format,
        file_name: main.split("/").pop()!,
        parts: format === "rad" ? ["plate"] : [],
        part_title: format === "rad" ? "plate" : null,
        mesh: { n_nodes: 48210, n_elems: 47600, n_quad: 46900, n_tria: 700, unsupported: {} },
        pids: [{ pid: 1, title: "plate_t0.8", n_elems: 47600, thickness: 0.8, E: 210000, nu: 0.3 }],
        frame: { L_xi: 1660, L_eta: 950, z_range: 0.4, warnings: [] },
        quality: { errors: [], warnings: ["셀당 노드 중앙값 58 < 64 (매핑 해상도)"], metrics: {} },
        supports_auto: SUPPORTS,
      };
      return ok(out);
    }
    if (method === "POST" && path === "/opt/templates") {
      if (!this.ctx.canRun(String(b.project_id ?? ""))) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
      const title = String(b.title ?? "").trim();
      if (!title || title.length > 200) return err(422, "INVALID_PARAMS", "제목은 1~200자입니다.");
      const u = this.ctx.upload(String(b.upload_id ?? ""));
      if (!u) return err(404, "UPLOAD_NOT_FOUND", "업로드를 찾을 수 없습니다.");
      const main = u.files.find((f) => /\.(fem|rad)$/i.test(f)) ?? "plate.fem";
      const me = this.ctx.me();
      const inch = typeof b.inch === "number" ? b.inch : null;
      const t: TemplateOut & { created_by: string } = {
        id: this.id("tpl"),
        title,
        inch,
        description: typeof b.description === "string" ? b.description : null,
        format: /\.fem$/i.test(main) ? "fem" : "rad",
        file_name: main.split("/").pop()!,
        part_title: (b.part_title as string | null) ?? null,
        sha256: String(b.sha256 ?? ""),
        n_nodes: 48210,
        n_elems: 47600,
        L_xi: 1660,
        L_eta: 950,
        z_range: 0.4,
        pids: [{ pid: 1, title: "plate_t0.8", n_elems: 47600, thickness: 0.8, E: 210000, nu: 0.3 }],
        quality_warnings: ["셀당 노드 중앙값 58 < 64 (매핑 해상도)"],
        status: "ACTIVE",
        n_runs: 0,
        created_by_name: me.display_name,
        created_at: this.ctx.now(),
        can_delete: true,
        created_by: me.user_id,
      };
      this.templates.unshift(t);
      return ok(this.templateOut(t), 201);
    }
    if (method === "GET" && path === "/opt/templates") {
      const st = query.get("status");
      const q = (query.get("q") ?? "").toLowerCase();
      return ok(this.templates.filter((t) => (!st || t.status === st) && (!q || t.title.toLowerCase().includes(q))).map((t) => this.templateOut(t)));
    }
    if ((r = path.match(/^\/opt\/templates\/([^/]+)$/))) {
      const t = this.templates.find((x) => x.id === r![1]);
      if (!t) return err(404, "TEMPLATE_NOT_FOUND", "템플릿을 찾을 수 없습니다.");
      if (method === "GET") return ok(this.templateOut(t));
      if (method === "DELETE") {
        if (!this.templateOut(t).can_delete) return err(403, "NOT_TEMPLATE_OWNER", "등록자 또는 관리자만 삭제할 수 있습니다.");
        if (t.n_runs > 0 || this.runs.some((x) => x.template_id === t.id)) {
          t.status = "ARCHIVED";
          return ok({ deleted: false, archived: true });
        }
        this.templates = this.templates.filter((x) => x !== t);
        this.keepouts.delete(`tpl:${t.id}`);
        return ok({ deleted: true, archived: false });
      }
    }

    // ---- S1 동일성
    if (method === "POST" && path === "/opt/s1-check") {
      const ids = (b.entry_ids as string[]) ?? [];
      const hit = ids.map((id) => es.find((e) => e.id === id && e.project_id === b.project_id));
      if (!ids.length || hit.some((e) => !e)) return err(422, "ENTRY_NOT_FOUND", "라이브러리 항목을 찾을 수 없습니다.", { entry_ids: ids.filter((_, i) => !hit[i]) });
      const base = hit[0]!;
      const out: S1CheckOut = {
        base: this.s1Base(base),
        entries: hit.map((e) => {
          const same = !!base.topo_sha256 && e!.topo_sha256 === base.topo_sha256;
          return { entry_id: e!.id, same_model: same, reason: same ? null : !e!.topo_sha256 || !base.topo_sha256 ? "NO_TOPO" : e!.model.name === base.model.name ? "COORDS" : "NODE_IDS" };
        }),
      };
      return ok(out);
    }

    // ---- 평면도
    if (method === "GET" && path === "/opt/plan-view") {
      const tid = query.get("template_id");
      const eid = query.get("entry_id");
      const s = this.settings.keepout_auto;
      if (tid) {
        const t = this.templates.find((x) => x.id === tid);
        if (!t) return err(404, "TEMPLATE_NOT_FOUND", "템플릿을 찾을 수 없습니다.");
        return ok(makePlanView(t.L_xi, t.L_eta, s.hole_radius_mm, s.edge_band_mm));
      }
      const e = es.find((x) => x.id === eid);
      if (!e) return err(404, "ENTRY_NOT_FOUND", "라이브러리 항목을 찾을 수 없습니다.");
      return ok(makePlanView(e.size?.L_xi ?? 1662, e.size?.L_eta ?? 948, s.hole_radius_mm, s.edge_band_mm));
    }

    // ---- 금지 영역 세트
    if (path === "/opt/keepouts") {
      if (method === "GET") {
        const key = query.get("template_id") ? `tpl:${query.get("template_id")}` : `topo:${query.get("topo")}`;
        const k = this.keepouts.get(key);
        return k ? ok(k) : err(404, "KEEPOUT_NOT_FOUND", "저장된 금지 영역 세트가 없습니다.");
      }
      if (method === "PUT") {
        if (!this.anyPower()) return err(403, "FORBIDDEN", "권한이 없습니다.");
        const tid = (b.template_id as string | null) ?? null;
        const topo = (b.topo_sha256 as string | null) ?? null;
        if (!!tid === !!topo) return err(422, "KEEPOUT_INVALID", "template_id 또는 topo_sha256 중 하나만 지정하세요.");
        const rects = (b.rects as KeepoutRect[]) ?? [];
        const bad = rectsInvalid(rects, this.settings.max_rects);
        if (bad) return err(422, "KEEPOUT_INVALID", bad);
        const key = tid ? `tpl:${tid}` : `topo:${topo}`;
        const cur = this.keepouts.get(key);
        if (cur && b.version !== cur.version) return err(409, "VERSION_CONFLICT", "다른 사용자가 먼저 저장했습니다.", { current_version: cur.version });
        const t = tid ? this.templates.find((x) => x.id === tid) : undefined;
        const e = topo ? es.find((x) => x.topo_sha256 === topo) : undefined;
        const L = t?.L_xi ?? e?.size?.L_xi ?? 1662;
        const H = t?.L_eta ?? e?.size?.L_eta ?? 948;
        const out: KeepoutSetOut = {
          id: cur?.id ?? this.id("ko"),
          key: tid ? { template_id: tid } : { topo_sha256: topo },
          version: (cur?.version ?? 0) + 1,
          rects,
          auto: (b.auto as KeepoutAuto) ?? { hole: true, edge: true },
          frame: { a_range: [0, L], b_range: [0, H] },
          updated_by_name: this.ctx.me().display_name,
          updated_at: this.ctx.now(),
        };
        this.keepouts.set(key, out);
        return ok(out);
      }
    }

    // ---- 실행
    if (method === "POST" && path === "/opt/runs") {
      const body = b as unknown as OptRunIn;
      if (!this.ctx.canRun(body.project_id)) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
      if (!this.settings.solver_ready) return err(503, "SOLVER_NOT_CONFIGURED", "서버 OptiStruct 경로가 설정되지 않았습니다.");
      const ids = body.entry_ids ?? [];
      const hit = ids.map((id) => es.find((e) => e.id === id && e.project_id === body.project_id && e.status === "ACTIVE"));
      if (!ids.length || hit.some((e) => !e)) return err(422, "ENTRY_NOT_FOUND", "라이브러리 항목을 찾을 수 없습니다.");
      const o = body.options ?? {};
      if (o.load_strategy && !["A", "B", "C"].includes(o.load_strategy)) return err(422, "INVALID_PARAMS", "load_strategy 는 A|B|C 입니다.");
      if (o.objective_norm && !["abs", "rel"].includes(o.objective_norm)) return err(422, "INVALID_PARAMS", "objective_norm 은 abs|rel 입니다.");
      if (o.load_strategy === "C" && o.k != null && !(Number.isInteger(o.k) && o.k >= 1 && o.k <= this.settings.loads.max_cases))
        return err(422, "INVALID_PARAMS", `k 는 1..${this.settings.loads.max_cases} 정수입니다.`);
      if (o.load_strategy === "B" && !hit.some((e) => e!.deform_mode?.effective)) return err(422, "NO_MODE_CANDIDATES", "모드가 분류된 ESL 이 없습니다.");
      const bad = rectsInvalid(body.design?.keepout?.rects ?? [], this.settings.max_rects);
      if (bad) return err(422, "KEEPOUT_INVALID", bad);
      if (body.scenario === "S1") {
        const base = hit[0]!;
        const mis = hit.filter((e) => !base.topo_sha256 || e!.topo_sha256 !== base.topo_sha256).map((e) => e!.id);
        if (mis.length) return err(422, "MODEL_MISMATCH", "기준 ESL 과 다른 모델이 있습니다.", { entry_ids: mis });
      } else {
        const t = this.templates.find((x) => x.id === body.template_id);
        if (!t) return err(422, "TEMPLATE_NOT_FOUND", "템플릿을 찾을 수 없습니다.");
        if (t.status === "ARCHIVED") return err(422, "TEMPLATE_ARCHIVED", "보관된 템플릿은 새 실행에 쓸 수 없습니다.");
        t.n_runs += 1;
      }
      const run = this.makeRun(body);
      this.runs.push(run);
      this.ctx.newJob(run.project_id, { opt_run_id: run.id });
      return ok(this.runOut(run), 201);
    }
    if (method === "GET" && path === "/opt/runs") {
      const pid = query.get("project_id");
      const sc = query.get("scenario");
      return ok(this.runs.filter((x) => (!pid || x.project_id === pid) && (!sc || x.scenario === sc)).map((x) => this.runOut(x)).reverse());
    }
    if ((r = path.match(/^\/opt\/runs\/([^/]+)(\/files|\/download|\/bundle|\/report|\/bead-map\.png)?$/)) && method === "GET") {
      const run = this.runs.find((x) => x.id === r![1]);
      if (!run) return err(404, "OPT_RUN_NOT_FOUND", "최적화 실행을 찾을 수 없습니다.");
      const out = this.runOut(run);
      if (!r[2]) return ok(out);
      if (out.state !== "SUCCEEDED") return err(404, "NOT_READY", "결과가 아직 없습니다.");
      if (r[2] === "/files") return ok(optFiles(run.id, run.scenario));
      if (r[2] === "/report") return ok(`<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><title>비드 최적화 보고서</title></head><body><h1>비드 최적화 — ${run.title ?? run.id}</h1></body></html>`);
      if (r[2] === "/bead-map.png") return ok(beadMapSvg(out.result!));
      return ok("mock file\n");
    }
    return err(404, "NOT_FOUND", `목 서버에 없는 경로: ${method} ${path}`);
  }
}

const OPT_STEPS = ["OPT_PREP", "OPT_LOAD", "OPT_DECK", "OS_SOLVE", "OPT_POST", "OPT_REGISTER"];
function doneJob(id: string, projectId: string, runId: string): JobOut {
  const t0 = "2026-10-28T03:00:10Z";
  const t1 = "2026-10-28T04:31:00Z";
  return {
    id,
    case_id: null,
    opt_run_id: runId,
    project_id: projectId,
    job_type: "OPT_RUN",
    stage: 10,
    lane: "SLOT",
    state: "SUCCEEDED",
    params: { opt_run_id: runId },
    result: null,
    warnings: [],
    cancel_requested: false,
    current_step_no: null,
    progress_pct: 100,
    queue_position: null,
    queued_at: t0,
    started_at: t0,
    finished_at: t1,
    failure_code: null,
    failure_message: null,
    retry_of_job_id: null,
    resume_from_step: null,
    created_by: "u-power",
    created_by_name: "김해석",
    created_at: t0,
    updated_at: t1,
    version: 1,
    steps: OPT_STEPS.map((k, i) => ({ step_no: i + 1, step_key: k, kind: k === "OS_SOLVE" || k === "OPT_POST" ? "LOCAL" : "INTERNAL", core_stage: null, state: "SUCCEEDED", progress_pct: 100, exit_code: 0, failure_code: null, failure_message: null, started_at: t0, finished_at: t1 })),
  };
}

export function rectsInvalid(rects: KeepoutRect[], max: number): string | null {
  if (rects.length > max) return `사각형은 최대 ${max}개입니다.`;
  for (const r of rects) {
    if (!r.name || r.name.length > 40) return "이름은 1~40자입니다.";
    if (!(r.x_mm >= 0 && r.y_mm >= 0)) return `${r.name}: X·Y 는 0 이상입니다.`;
    if (!(r.w_mm > 0 && r.h_mm > 0)) return `${r.name}: 가로·세로는 0보다 커야 합니다.`;
  }
  return null;
}

function optFiles(id: string, scenario: "S1" | "S2"): OptFileOut[] {
  const f = (rel: string, kind: string, size: number): OptFileOut => ({ rel, kind, size, downloadable: size < 200e6, path: `E:\\ESL_ROOT\\_opt\\${id}\\${rel.replace(/\//g, "\\")}` });
  return [
    f("report.html", "report", 412_331),
    f("post/bead_map.png", "post", 88_120),
    f("post/bead_mesh.rad", "post", scenario === "S1" ? 61_204_118 : 4_120_331),
    f("post/bead_mesh.fem", "post", scenario === "S1" ? 58_331_204 : 3_901_112),
    f("post/bead_nodes.csv", "post", 14_220_118),
    f("post/history.csv", "post", 2_118),
    f("load/selection.json", "load", 6_331),
    f("deck/esl_bead.fem", "deck", 71_204_331),
    f("solve/esl_bead_des.h3d", "solve", 412_331_204),
  ];
}

/** 목 비드 맵(SVG — 실제는 PNG). 셀 색 = 비드 높이 */
export function beadMapSvg(res: OptResult) {
  const W = 1600;
  const H = 900;
  const cells: string[] = [];
  for (let i = 0; i < 32; i++)
    for (let j = 0; j < 18; j++) {
      const s = (i / 31) * 2 - 1;
      const t = (j / 17) * 2 - 1;
      const v = Math.max(0, Math.sin(3 * s) * Math.cos(2.4 * t) + 0.35 * Math.cos(5 * s * t));
      const g = Math.round(255 - Math.min(1, v) * 180);
      cells.push(`<rect x="${i * 50}" y="${j * 50}" width="50" height="50" fill="rgb(${g},${Math.round(g * 0.9)},255)"/>`);
    }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><rect width="${W}" height="${H}" fill="#fff"/>${cells.join("")}<rect x="120" y="580" width="300" height="200" fill="none" stroke="#d9480f" stroke-width="4"/><text x="20" y="40" font-size="28" font-family="sans-serif">비드 높이 0 → ${res.bead.height_max} mm</text></svg>`;
}
