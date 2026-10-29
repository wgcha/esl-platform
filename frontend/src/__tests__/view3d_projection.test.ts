// v0.7.1 투영 전환 수식(원근 ↔ 직교): 같은 시점·같은 화면 크기, 직교 근/원, px 월드 길이, 직교 피킹.
// three 카메라로 실제 투영해 화면 크기를 비교한다(시험 파일은 번들 규칙 대상 아님).
import { OrthographicCamera, PerspectiveCamera, Raycaster, Vector2, Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { pickSegment, type V3 } from "../view3d/pick";
import {
  DEFAULT_PROJECTION, PERSP_FOV, orthoClip, orthoHalfHeightFromPersp, perspPositionFromOrtho, perspVisibleHeight, pxWorld,
} from "../view3d/projection";

const ASPECT = 16 / 9;
const target = new Vector3(100, 50, 20);
const pos = new Vector3(900, 850, 820);
const v3 = (v: Vector3): V3 => [v.x, v.y, v.z];

function perspCam(p: Vector3) {
  const c = new PerspectiveCamera(PERSP_FOV, ASPECT, 1, 1e6);
  c.up.set(0, 0, 1);
  c.position.copy(p);
  c.lookAt(target);
  c.updateMatrixWorld();
  c.updateProjectionMatrix();
  return c;
}
function orthoCam(p: Vector3, halfH: number, zoom: number, diag = 500) {
  const c = new OrthographicCamera(-halfH * ASPECT, halfH * ASPECT, halfH, -halfH, -1, 1);
  c.up.set(0, 0, 1);
  c.position.copy(p);
  c.lookAt(target);
  c.zoom = zoom;
  c.updateMatrixWorld();
  const cl = orthoClip(v3(c.position), v3(c.getWorldDirection(new Vector3())), v3(target), diag);
  c.near = cl.near;
  c.far = cl.far;
  c.updateProjectionMatrix();
  return c;
}
/** 타깃에서 화면 위쪽으로 h 떨어진 점의 화면 높이(NDC) */
function ndcSize(cam: PerspectiveCamera | OrthographicCamera, h: number) {
  const up = new Vector3(0, 1, 0).applyQuaternion(cam.quaternion);
  const a = target.clone().project(cam);
  const b = target.clone().addScaledVector(up, h).project(cam);
  return b.y - a.y;
}

describe("v0.7.1 투영 전환", () => {
  it("기본값 = 직교", () => {
    expect(DEFAULT_PROJECTION).toBe("ortho");
  });

  it("원근 → 직교: 위치·방향 그대로, 타깃 거리 보이는 높이 2·d·tan(FOV/2) 일치 → 모델 크기 동일", () => {
    const p = perspCam(pos);
    const halfH = orthoHalfHeightFromPersp(v3(pos), v3(target));
    const d = pos.distanceTo(target);
    expect(2 * halfH).toBeCloseTo(2 * d * Math.tan((PERSP_FOV * Math.PI) / 360), 9);
    const o = orthoCam(pos, halfH, 1);
    expect(o.quaternion.angleTo(p.quaternion)).toBeLessThan(1e-9);
    for (const h of [10, 80, 200]) expect(ndcSize(o, h)).toBeCloseTo(ndcSize(p, h), 4);
  });

  it("직교(줌 1) → 원근: 위치 그대로 복귀(왕복 무손실)", () => {
    const halfH = orthoHalfHeightFromPersp(v3(pos), v3(target));
    const back = perspPositionFromOrtho(v3(pos), v3(target), halfH, 1);
    back.forEach((x, i) => expect(x).toBeCloseTo(v3(pos)[i], 6));
  });

  it("직교에서 줌 2.5 후 → 원근: 방향 그대로, 보이는 높이 같도록 거리만 조정 → 크기 동일", () => {
    const halfH = orthoHalfHeightFromPersp(v3(pos), v3(target));
    const o = orthoCam(pos, halfH, 2.5);
    const np = new Vector3(...perspPositionFromOrtho(v3(pos), v3(target), halfH, 2.5));
    const p = perspCam(np);
    expect(np.distanceTo(target)).toBeCloseTo(pos.distanceTo(target) / 2.5, 6);
    expect(o.quaternion.angleTo(p.quaternion)).toBeLessThan(1e-9);
    expect(ndcSize(p, 30)).toBeCloseTo(ndcSize(o, 30), 4);
  });

  it("직교 근/원: 모델 대각선 기준 — 모델 전체가 클리핑되지 않음(카메라가 모델 안쪽이어도)", () => {
    const diag = 500;
    for (const p of [pos, target.clone().add(new Vector3(30, 20, 10))]) {
      const o = orthoCam(p, 100, 1, diag);
      const dir = o.getWorldDirection(new Vector3());
      const along = target.clone().sub(p).dot(dir);
      expect(o.near).toBeLessThanOrEqual(along - diag / 2);
      expect(o.far).toBeGreaterThanOrEqual(along + diag / 2);
      // 모델 경계 근처 점의 NDC z ∈ [-1, 1]
      for (const s of [-1, 1]) {
        const z = target.clone().addScaledVector(dir, (s * diag) / 2).project(o).z;
        expect(Math.abs(z)).toBeLessThanOrEqual(1);
      }
    }
  });

  it("px 월드 길이: 원근은 거리 비례, 직교는 보이는 높이/화면 높이(거리 무관)", () => {
    expect(pxWorld("persp", 1000, 700, 0)).toBeCloseTo(perspVisibleHeight(1000) / 700, 9);
    expect(pxWorld("ortho", 10, 700, 350)).toBe(0.5);
    expect(pxWorld("ortho", 99999, 700, 350)).toBe(0.5);
  });

  it("직교 피킹: Raycaster 광선이 화면 중앙의 화살표 선분을 맞힘(픽셀 허용 6 px)", () => {
    const halfH = orthoHalfHeightFromPersp(v3(pos), v3(target));
    const o = orthoCam(pos, halfH, 1.7);
    const rc = new Raycaster();
    rc.setFromCamera(new Vector2(0, 0), o);
    if (o.near < 0) rc.ray.origin.addScaledVector(rc.ray.direction, o.near);
    const o3 = v3(rc.ray.origin);
    const d3 = v3(rc.ray.direction);
    const visH = (2 * halfH) / o.zoom;
    const tol = () => pxWorld("ortho", 0, 700, visH) * 6;
    const right = new Vector3(1, 0, 0).applyQuaternion(o.quaternion);
    const seg = (off: number) => ({ a: v3(target.clone().addScaledVector(right, off)), b: v3(target.clone().addScaledVector(right, off).add(new Vector3(0, 0, 50))) });
    expect(pickSegment(o3, d3, [seg(500), seg(0)], tol)).toBe(1);
    // 7 px 밖이면 안 맞음
    expect(pickSegment(o3, d3, [seg(pxWorld("ortho", 0, 700, visH) * 7)], tol)).toBe(-1);
  });
});
