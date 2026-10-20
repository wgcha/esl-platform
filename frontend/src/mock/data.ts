// 목 데이터: 합성 판 메시(사각판) + 요소별 max-hold 곡선. 결정적(난수 없음).
// t* 규칙(esl_core §7.1·§7.4)을 그대로 따른다:
//   - 요소 e 의 max-hold v_e(f), first_reach(e) = v_e 가 최종값에 처음 도달한 프레임.
//   - history m(f) = max_e v_e(f). 후보 = 최종값 내림차순으로 first-reach 프레임(중복 제외) top_n.
//   - rank 1 = 최종값 1위 요소의 first-reach = m(f) 가 최종 최대값에 처음 도달한 프레임 = 자동 t*.
//   - hotspot = t* 에서 상승 중(v[t*] > v[t*−1])인 요소, rank 1 = 최종값 1위(정의상 상승 중).
import type {
  ArtifactOut, CaseOut, EslRunOut, ExtractSummary, ForceRow, Hotspot, Me, Metric, Preview, Project, StageState,
  SupportSetOut, TstarCandidate, TstarMetricBlock, ValidationOut,
} from "../api/types";

export type MockUserKey = "admin" | "power" | "general";

export const USERS: Record<MockUserKey, Me> = {
  admin: { user_id: "u-admin", username: "admin", display_name: "관리자", is_global_admin: true, roles: {} },
  power: { user_id: "u-power", username: "kim", display_name: "김해석", is_global_admin: false, roles: { "p-body": "power", "p-door": "power" } },
  general: { user_id: "u-gen", username: "lee", display_name: "이조회", is_global_admin: false, roles: { "p-body": "general", "p-door": "general" } },
};

export const PROJECTS: Project[] = [
  { id: "p-body", name: "차체 후방 충돌", product_name: "SUV-A" },
  { id: "p-door", name: "도어 측면 충돌", product_name: "SEDAN-B" },
];

const NX = 120;
const NY = 60;
const LX = 1200;
const LY = 600;

/** 판 위 노드 id = 1 + j*NX + i */
export function nodeId(i: number, j: number) {
  return 1 + j * NX + i;
}
export function nodeAB(id: number): [number, number] {
  const k = id - 1;
  const i = k % NX;
  const j = Math.floor(k / NX);
  return [(i / (NX - 1)) * LX - LX / 2, (j / (NY - 1)) * LY - LY / 2];
}
export const N_NODES = NX * NY;
export const CORNER_IDS = [nodeId(0, 0), nodeId(NX - 1, 0), nodeId(NX - 1, NY - 1), nodeId(0, NY - 1)];

export const PLANE = { origin: [1520.4, 0, 410.2], e1: [0.998, 0.0, -0.06], e2: [0.0, 1.0, 0.0], n: [0.06, 0.0, 0.998] };

export function makePreview(frameIndex: number | null = null, supports: { node_id: number; dof: string }[] = []): Preview {
  const points: Preview["points"] = [];
  for (let j = 0; j < NY; j++)
    for (let i = 0; i < NX; i++) {
      const [a, b] = nodeAB(nodeId(i, j));
      const r2 = ((a - 280) / 260) ** 2 + ((b + 80) / 180) ** 2;
      const v = 0.4 + 11.5 * Math.exp(-r2) + 0.003 * (a + LX / 2);
      points.push([nodeId(i, j), +a.toFixed(2), +b.toFixed(2), +v.toFixed(3)]);
    }
  return { frame_index: frameIndex, plane: PLANE, points, decimated: false, n_nodes: N_NODES, value: "|u|", supports };
}

// ---------------------------------------------------------------- max-hold 이력
export const N_FRAMES = 126;
const TIME = Array.from({ length: N_FRAMES }, (_, f) => +(f * 0.001).toFixed(3));
const RTOL = 1e-6;

interface Elem {
  elem_id: number;
  /** 최종값(= 정점 값) */
  peak: number;
  /** 순간값이 정점에 이르는 프레임(이후 감소 → hold 는 이 프레임에서 최종값에 처음 도달) */
  at: number;
  centroid: [number, number, number];
}

/** 순간값: at 까지 단조 증가(시작 4 ms 지연), 이후 감소. */
function raw(e: Elem, f: number) {
  const t0 = 4;
  if (f <= t0) return 0;
  if (f <= e.at) return e.peak * Math.pow((f - t0) / (e.at - t0), 1.6);
  return e.peak * Math.max(0.2, 1 - 0.012 * (f - e.at));
}

function holdCurve(e: Elem): number[] {
  const out: number[] = [];
  let h = 0;
  for (let f = 0; f < N_FRAMES; f++) {
    h = Math.max(h, raw(e, f));
    out.push(h);
  }
  return out;
}

function firstReach(v: number[]) {
  const fin = v[v.length - 1];
  const f = v.findIndex((x) => x >= fin * (1 - RTOL));
  return f < 0 ? v.length - 1 : f;
}

const ELEMS: Record<Metric, Elem[]> = {
  max_strain: [
    { elem_id: 101245, peak: 0.1418, at: 78, centroid: [1802.1, -84.3, 402.5] },
    { elem_id: 101588, peak: 0.129, at: 92, centroid: [1755.6, -120.0, 404.1] },
    { elem_id: 99871, peak: 0.1176, at: 64, centroid: [1690.2, 40.8, 407.9] },
    { elem_id: 104012, peak: 0.1032, at: 110, centroid: [1883.4, 210.2, 399.0] },
    { elem_id: 97733, peak: 0.0951, at: 55, centroid: [1311.7, -255.5, 431.2] },
    { elem_id: 101250, peak: 0.0912, at: 78, centroid: [1806.0, -80.1, 402.4] },
    { elem_id: 96010, peak: 0.0705, at: 40, centroid: [1205.5, 280.4, 436.0] },
  ],
  plastic_strain: [
    { elem_id: 101302, peak: 0.0881, at: 84, centroid: [1798.7, -92.0, 402.9] },
    { elem_id: 101245, peak: 0.0812, at: 97, centroid: [1802.1, -84.3, 402.5] },
    { elem_id: 99902, peak: 0.0644, at: 71, centroid: [1688.4, 52.6, 408.0] },
    { elem_id: 104077, peak: 0.0571, at: 118, centroid: [1890.2, 205.3, 398.7] },
    { elem_id: 96010, peak: 0.0302, at: 46, centroid: [1205.5, 280.4, 436.0] },
  ],
};

export const TOP_N = 5;

function block(elems: Elem[]): TstarMetricBlock {
  const curves = elems.map(holdCurve);
  const value = TIME.map((_, f) => +Math.max(...curves.map((c) => c[f])).toFixed(6));
  const order = elems.map((_, k) => k).sort((a, b) => curves[b][N_FRAMES - 1] - curves[a][N_FRAMES - 1] || a - b);
  const candidates: TstarCandidate[] = [];
  const seen = new Set<number>();
  for (const k of order) {
    if (candidates.length >= TOP_N) break;
    const f = firstReach(curves[k]);
    if (seen.has(f)) continue;
    seen.add(f);
    candidates.push({
      rank: candidates.length + 1,
      frame_index: f,
      time: TIME[f],
      elem_id: elems[k].elem_id,
      value: +curves[k][f].toFixed(6),
      in_D: true,
    });
  }
  const c0 = candidates[0];
  const ts = c0.frame_index;
  // hotspot: t* 에서 상승 중인 요소(값 내림차순), rank 1 = 최종값 1위
  const rising = (k: number) => (ts > 0 ? curves[k][ts] > curves[k][ts - 1] * (1 + RTOL) : curves[k][ts] > 0);
  const hotIdx = [order[0], ...elems.map((_, k) => k).filter((k) => k !== order[0] && rising(k)).sort((a, b) => curves[b][ts] - curves[a][ts])];
  const hotspots: Hotspot[] = hotIdx.map((k, r) => ({
    rank: r + 1,
    elem_id: elems[k].elem_id,
    value: +curves[k][ts].toFixed(6),
    centroid: elems[k].centroid,
    rising: rising(k),
  }));
  return {
    tstar: { frame_index: c0.frame_index, time: c0.time, elem_id: c0.elem_id, value: c0.value },
    candidates,
    history: { time: TIME, value },
    hotspots,
  };
}

export function makeTstarMetrics(): Record<Metric, TstarMetricBlock> {
  return { max_strain: block(ELEMS.max_strain), plastic_strain: block(ELEMS.plastic_strain) };
}

export const TSTAR_METRICS = makeTstarMetrics();
/** done.json candidate_frames = 지표별 후보 프레임 */
export const CANDIDATE_FRAMES: Record<Metric, number[]> = {
  max_strain: TSTAR_METRICS.max_strain.candidates.map((c) => c.frame_index),
  plastic_strain: TSTAR_METRICS.plastic_strain.candidates.map((c) => c.frame_index),
};
/** 변위가 추출된 프레임 D = 두 지표 후보의 합집합 */
export const FRAMES_D = [...new Set([...CANDIDATE_FRAMES.max_strain, ...CANDIDATE_FRAMES.plastic_strain])].sort((a, b) => a - b);

// ---------------------------------------------------------------- 지지점·ESL·검증
export function makeSupportSet(id: string, caseId: string): SupportSetOut {
  return {
    id,
    case_id: caseId,
    node_ids: [CORNER_IDS[0], CORNER_IDS[1], CORNER_IDS[3]],
    dofs: ["123", "23", "3"],
    source: "auto",
    plane: PLANE,
    created_by: "u-power",
    created_at: "2026-10-18T02:10:00Z",
    is_current: true,
  };
}

export function makeEslRun(id: string, caseId: string, supportSetId: string, frame: number, time: number, metric: Metric = "max_strain"): EslRunOut {
  return {
    id,
    case_id: caseId,
    job_id: "j-esl-1",
    frame_index: frame,
    time,
    metric,
    support_set_id: supportSetId,
    kabsch: { rot_deg: 1.84, rms_def: 3.412, max_def: 11.86 },
    forces: {
      n_nodes_loaded: 7146,
      sum_f: [2.1e-6, -4.3e-7, 1.2e-6],
      sum_m: [3.1e-4, -1.7e-4, 2.2e-5],
      sum_abs_f: 2.31e6,
      equilibrium_rel: 3.8e-10,
      moment_rel: 1.1e-10,
      max_f: { node_id: 3542, mag: 18420.5 },
      noise: { force_rel: 0.0042, hotspot_strain_rel: 0.0011, disp_precision: "float32" },
    },
    supports: [
      { node_id: CORNER_IDS[0], dof: "123" },
      { node_id: CORNER_IDS[1], dof: "23" },
      { node_id: CORNER_IDS[3], dof: "3" },
    ],
    warnings: [],
    dir_rel: "04_esl",
    status: "READY",
    created_at: "2026-10-18T03:00:00Z",
    stale: false,
    is_current: true,
    latest_validation_id: null,
  };
}

export function makeForces(): ForceRow[] {
  const rows: ForceRow[] = [];
  for (let k = 0; k < 50; k++) {
    const id = 3542 + k * 37;
    const [a, b] = nodeAB(id);
    const mag = 18420.5 * Math.exp(-k / 14);
    rows.push({
      node_id: id,
      x: +(1520 + a).toFixed(1),
      y: +b.toFixed(1),
      z: 410.2,
      fx: +(mag * 0.62).toFixed(1),
      fy: +(-mag * 0.31).toFixed(1),
      fz: +(mag * 0.72).toFixed(1),
      mag: +mag.toFixed(1),
      is_support: k === 7,
    });
  }
  return rows;
}

export const VALIDATION_CRITERIA = {
  disp_rms_rel_max: 0.01,
  hotspot_strain_rel_err_max: 0.1,
  reaction_rel_max: 1e-6,
  hotspot_eval_count: 3,
  noise_strain_rel_max: 0.05,
  noise_force_rel_warn: 0.1,
  disp_precision: "float32",
  layers: ["mid"],
  metric: "max_strain",
  full_solve: "auto",
  field_max_err_pct_max: 10,
  field_p90_err_max: 20,
  field_min_rel: 0.1,
};

export function makeValidation(id: string, runId: string, caseId: string): ValidationOut {
  const hs = TSTAR_METRICS.max_strain.hotspots;
  return {
    id,
    esl_run_id: runId,
    case_id: caseId,
    job_id: "j-val-1",
    disp_rms_rel: 2.1e-9,
    reaction_rel: 4.4e-8,
    hotspots: [
      { rank: 1, elem_id: hs[0].elem_id, eps_rad: 0.1418, eps_val: 0.1242, rel_err: 0.124 },
      { rank: 2, elem_id: hs[1].elem_id, eps_rad: 0.0981, eps_val: 0.0925, rel_err: 0.057 },
      { rank: 3, elem_id: hs[2].elem_id, eps_rad: 0.0712, eps_val: 0.0697, rel_err: 0.021 },
    ],
    excluded: [{ elem_id: 101250, reason: "t* 프레임에서 상승 중 아님(hold 값 ≠ 순간값)" }],
    verdict: "FAIL",
    fail_reasons: ["HOTSPOT_STRAIN", "REACTION", "FIELD_MAX_ERR"],
    criteria: VALIDATION_CRITERIA,
    dir_rel: "05_val",
    created_at: "2026-10-18T03:20:00Z",
    stale: false,
  };
}

export function noneStatus(): Record<string, StageState> {
  return Object.fromEntries([1, 2, 3, 4, 5, 6].map((n) => [String(n), { state: "none" as const, job_id: null }]));
}

export const ESL_ROOT = "E:\\ESL_ROOT";

export function baseCase(id: string, projectId: string, title: string, folder: string): CaseOut {
  const dir = `${ESL_ROOT}\\${folder}`;
  return {
    id,
    project_id: projectId,
    folder_name: folder,
    title,
    status: "ACTIVE",
    rad_path: `D:\\ESL_INPUT\\${folder}\\chassis_rear_0000.rad`,
    results_dir: `D:\\ESL_INPUT\\${folder}\\h3d_csv`,
    h3d_path: null,
    input_kind: "RESULTS",
    input_fingerprint: {},
    part_title: "chassis_rear",
    part_id: null,
    extract_summary: null,
    tstar: null,
    current_support_set_id: null,
    current_esl_run_id: null,
    case_dir: dir,
    folder_path: dir,
    created_by: "u-power",
    created_by_name: "김해석",
    created_at: "2026-10-18T01:00:00Z",
    updated_at: "2026-10-18T01:00:00Z",
    version: 1,
    stage_status: noneStatus(),
  };
}

export const EXTRACT_SUMMARY: ExtractSummary = {
  job_id: "j-ext-1",
  requested_part_title: "chassis_rear",
  part_id: 10,
  part_title: "chassis_rear",
  units_label: "mm-ton-s",
  n_nodes: N_NODES,
  n_elems: 223415,
  n_quad: 214880,
  n_tria: 8535,
  n_frames: N_FRAMES,
  mats: [
    { id: 12, law: "LAW36", E: 210000, nu: 0.3, source: "rad" },
    { id: 15, law: "LAW2", E: 70000, nu: 0.33, source: "rad" },
  ],
  disp_frames: FRAMES_D,
  metrics: ["max_strain", "plastic_strain"],
  warnings: [],
};

/** 평면 좌표(a,b) → 전역 xyz */
export function toXYZ(id: number): number[] {
  const [a, b] = nodeAB(id);
  const { origin, e1, e2 } = PLANE;
  return [0, 1, 2].map((k) => +(origin[k] + a * e1[k] + b * e2[k]).toFixed(3));
}

/** 다운로드 허용 크기(설정 ui.max_artifact_bytes 기본값) */
export const MAX_ARTIFACT_BYTES = 20 * 1024 * 1024;

export function makeArtifact(id: string, c: CaseOut, rel: string, size: number, kind: string, jobId: string | null): ArtifactOut {
  return {
    id,
    case_id: c.id,
    job_id: jobId,
    kind,
    rel,
    size,
    path: `${c.folder_path}\\${rel.replace(/\//g, "\\")}`,
    downloadable: size <= MAX_ARTIFACT_BYTES,
    created_at: "2026-10-18T03:30:00Z",
  };
}
