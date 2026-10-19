// 목 데이터: 합성 판 메시(사각판) + max-hold 곡선. 결정적(난수 없음).
import type {
  Case, EslRun, ForceRow, Hotspot, Me, Metric, Preview, Project, StageStatus, SupportSet, TstarMetricBlock, Validation,
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

export function makePreview(): Preview {
  const points: Preview["points"] = [];
  for (let j = 0; j < NY; j++)
    for (let i = 0; i < NX; i++) {
      const [a, b] = nodeAB(nodeId(i, j));
      const r2 = ((a - 280) / 260) ** 2 + ((b + 80) / 180) ** 2;
      const v = 0.4 + 11.5 * Math.exp(-r2) + 0.003 * (a + LX / 2);
      points.push([nodeId(i, j), +a.toFixed(2), +b.toFixed(2), +v.toFixed(3)]);
    }
  return {
    plane: { origin: [1520.4, 0, 410.2], e1: [0.998, 0.0, -0.06], e2: [0.0, 1.0, 0.0], n: [0.06, 0.0, 0.998] },
    points,
    decimated: false,
  };
}

const N_FRAMES = 126;
function maxHold(scale: number, rise: number, knee: number): TstarMetricBlock["history"] {
  const time: number[] = [];
  const value: number[] = [];
  let hold = 0;
  for (let f = 0; f < N_FRAMES; f++) {
    const t = f * 0.001;
    const raw = scale * (1 - Math.exp(-Math.max(0, t - 0.004) / rise)) * (1 + 0.08 * Math.sin(f / 4)) * (t > knee ? 1.06 : 1);
    hold = Math.max(hold, raw);
    time.push(+t.toFixed(3));
    value.push(+hold.toFixed(5));
  }
  return { time, value };
}

function block(scale: number, rise: number, knee: number, frames: number[], elem: number): TstarMetricBlock {
  const history = maxHold(scale, rise, knee);
  const candidates = frames.map((f, k) => ({
    rank: k + 1,
    frame_index: f,
    time: history.time[f],
    elem_id: elem + k * 7,
    value: history.value[f],
  }));
  const c0 = candidates[0];
  return { tstar: { frame_index: c0.frame_index, time: c0.time, elem_id: c0.elem_id, value: c0.value }, candidates, history };
}

export const CANDIDATE_FRAMES: Record<Metric, number[]> = { max_strain: [78, 92, 64, 110, 55], plastic_strain: [84, 97, 71, 118] };

export function makeTstarMetrics(): Record<Metric, TstarMetricBlock> {
  return {
    max_strain: block(0.142, 0.026, 0.07, CANDIDATE_FRAMES.max_strain, 101245),
    plastic_strain: block(0.088, 0.034, 0.08, CANDIDATE_FRAMES.plastic_strain, 101302),
  };
}

export const HOTSPOTS: Hotspot[] = [
  { rank: 1, elem_id: 101245, value: 0.1418, centroid: [1802.1, -84.3, 402.5], rising: false },
  { rank: 2, elem_id: 101588, value: 0.1290, centroid: [1755.6, -120.0, 404.1], rising: true },
  { rank: 3, elem_id: 99871, value: 0.1176, centroid: [1690.2, 40.8, 407.9], rising: false },
  { rank: 4, elem_id: 104012, value: 0.1032, centroid: [1883.4, 210.2, 399.0], rising: true },
  { rank: 5, elem_id: 97733, value: 0.0951, centroid: [1311.7, -255.5, 431.2], rising: false },
];

export const PLANE = makePreview().plane;

export function makeSupportSet(id: string, caseId: string): SupportSet {
  return {
    id,
    case_id: caseId,
    node_ids: [CORNER_IDS[0], CORNER_IDS[1], CORNER_IDS[3]],
    dofs: ["123", "23", "3"],
    source: "auto",
    plane: PLANE,
    created_by: "u-power",
    created_at: "2026-10-18T02:10:00Z",
  };
}

export function makeEslRun(id: string, caseId: string, supportSetId: string, frame: number, time: number): EslRun {
  return {
    id,
    case_id: caseId,
    job_id: "j-esl-1",
    frame_index: frame,
    time,
    support_set_id: supportSetId,
    kabsch: { rot_deg: 1.84, rms_def: 3.412, max_def: 11.86 },
    forces: {
      n_nodes_loaded: 7146,
      sum_f: [2.1e-6, -4.3e-7, 1.2e-6],
      sum_m: [3.1e-4, -1.7e-4, 2.2e-5],
      equilibrium_rel: 3.8e-10,
      max_f: { node_id: 3542, mag: 18420.5 },
      noise: { force_rel: 0.0042, hotspot_strain_rel: 0.0011 },
    },
    dir_rel: `04_esl/${id}`,
    status: "READY",
    created_at: "2026-10-18T03:00:00Z",
    stale: false,
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

export function makeValidation(id: string, runId: string): Validation {
  return {
    id,
    esl_run_id: runId,
    job_id: "j-val-1",
    disp_rms_rel: 2.1e-9,
    reaction_rel: 4.4e-8,
    hotspots: [
      { elem_id: 101245, eps_rad: 0.1418, eps_val: 0.1302, rel_err: 0.082 },
      { elem_id: 101588, eps_rad: 0.129, eps_val: 0.1215, rel_err: 0.058 },
      { elem_id: 99871, eps_rad: 0.1176, eps_val: 0.1201, rel_err: 0.021 },
      { elem_id: 104012, eps_rad: 0.1032, eps_val: 0.0866, rel_err: 0.161 },
    ],
    excluded: [{ elem_id: 97733, reason: "지지점 인접(경계 영향)" }],
    verdict: "FAIL",
    fail_reasons: ["hotspot 104012 ε_eq 오차 16.1% > 기준 15.0%"],
    criteria: { disp_rms_rel_max: 1e-6, hotspot_rel_err_max: 0.15 },
    dir_rel: `05_val/${id}`,
    created_at: "2026-10-18T03:20:00Z",
    stale: false,
  };
}

export function allDone(): Record<string, StageStatus> {
  return Object.fromEntries([1, 2, 3, 4, 5, 6].map((n) => [String(n), { state: "done" as const }]));
}

export function baseCase(id: string, projectId: string, title: string, folder: string): Case {
  return {
    id,
    project_id: projectId,
    folder_name: folder,
    title,
    status: "ACTIVE",
    rad_path: `D:\\ESL_INPUT\\${folder}\\chassis_rear_0000.rad`,
    results_dir: `D:\\ESL_INPUT\\${folder}\\h3d_csv`,
    h3d_path: `D:\\ESL_INPUT\\${folder}\\chassis_rear.h3d`,
    part_title: "chassis_rear",
    part_id: null,
    extract_summary: null,
    tstar: null,
    current_support_set_id: null,
    current_esl_run_id: null,
    created_by: "u-power",
    created_by_name: "김해석",
    created_at: "2026-10-18T01:00:00Z",
    updated_at: "2026-10-18T01:00:00Z",
    version: 1,
    stage_status: Object.fromEntries([1, 2, 3, 4, 5, 6].map((n) => [String(n), { state: "none" as const }])),
    folder_path: `E:\\ESL_ROOT\\${folder}`,
  };
}

export const EXTRACT_SUMMARY = {
  n_nodes: N_NODES,
  n_elems: 223415,
  elem_types: { QUAD4: 214880, TRIA3: 8535 },
  n_frames: N_FRAMES,
  t_end: 0.125,
  units_label: "mm·ton·s (N, MPa)",
  mat: [
    { id: 12, law: "LAW36", E: 210000, nu: 0.3, source: "rad" },
    { id: 15, law: "LAW2", E: 70000, nu: 0.33, source: "rad" },
  ],
};

/** 평면 좌표(a,b) → 전역 xyz */
export function toXYZ(id: number): number[] {
  const [a, b] = nodeAB(id);
  const { origin, e1, e2 } = PLANE;
  return [0, 1, 2].map((k) => +(origin[k] + a * e1[k] + b * e2[k]).toFixed(3));
}
