// v0.12.5 자유 회전: 실제 scene.ts(createScene) + 실제 TrackballControls, WebGLRenderer 만 가짜.
// 컨트롤 생성·설정, 극점 넘어 연속 회전, 투영 전환 시 컨트롤 대상 갱신, 맞춤 보기에서 up 복원, 팬 방향·크기, 휠 줌 방향, dispose.
import { Vector3, type OrthographicCamera, type PerspectiveCamera } from "three";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TrackballControls } from "three/examples/jsm/controls/TrackballControls.js";
import { ROTATE_TURNS_PER_HEIGHT, STATIC_MOVING, WHEEL_ZOOM_SPEED, trackballRotateSpeed } from "../lib/viewerControls";
import type { SceneApi } from "../view3d/sceneApi";

const h = vi.hoisted(() => ({ ctl: [] as unknown[], renders: 0 }));

vi.mock("three", async (orig) => {
  const m = await orig<typeof import("three")>();
  class FakeRenderer {
    setPixelRatio() {}
    setSize() {}
    render() {
      h.renders++;
    }
    dispose() {}
    forceContextLoss() {}
  }
  return { ...m, WebGLRenderer: FakeRenderer };
});
vi.mock("three/examples/jsm/controls/TrackballControls.js", async (orig) => {
  const m = await orig<typeof import("three/examples/jsm/controls/TrackballControls.js")>();
  class Recorded extends m.TrackballControls {
    constructor(...a: ConstructorParameters<typeof m.TrackballControls>) {
      super(...a);
      h.ctl.push(this);
    }
  }
  return { ...m, TrackballControls: Recorded };
});

const W = 800;
const H = 600;
const BBOX = { min: [0, 0, 0], max: [100, 60, 20] };
const CENTER = new Vector3(50, 30, 10);
const DIAG = Math.hypot(100, 60, 20);

type Cam = PerspectiveCamera | OrthographicCamera;
let canvas: HTMLCanvasElement;
let api: SceneApi | null = null;
const ctl = () => h.ctl[h.ctl.length - 1] as TrackballControls & { object: Cam; target: Vector3 };
const frame = () => new Promise<void>((r) => requestAnimationFrame(() => r()));

function ptr(type: string, x: number, y: number, button = 0, target: EventTarget = canvas) {
  const e = new MouseEvent(type, { clientX: x, clientY: y, button, bubbles: true, cancelable: true });
  Object.defineProperty(e, "pointerId", { value: 1 });
  Object.defineProperty(e, "pointerType", { value: "mouse" });
  target.dispatchEvent(e);
}
/** 왼쪽(0)/오른쪽(2) 버튼 끌기: 컨트롤이 쌓은 입력을 update 1회로 반영 */
function drag(x0: number, y0: number, x1: number, y1: number, button = 0) {
  ptr("pointerdown", x0, y0, button);
  ptr("pointermove", x1, y1, button, document);
  ctl().update();
  ptr("pointerup", x1, y1, button, document);
}
const eye = () => ctl().object.position.clone().sub(ctl().target);
/** 모델 중심이 보이는 화면 위치(px) */
function screenOf(p: Vector3): [number, number] {
  const c = ctl().object;
  c.updateMatrixWorld();
  const q = p.clone().project(c);
  return [((q.x + 1) / 2) * W, ((1 - q.y) / 2) * H];
}

async function make(projection: "persp" | "ortho" = "ortho") {
  const { createScene } = await import("../view3d/scene");
  api = createScene(canvas, { background: "#ffffff", diag: DIAG, bbox: BBOX, projection });
  return api;
}

beforeEach(() => {
  h.ctl.length = 0;
  canvas = document.createElement("canvas");
  Object.defineProperty(canvas, "clientWidth", { value: W });
  Object.defineProperty(canvas, "clientHeight", { value: H });
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: W, height: H, right: W, bottom: H, x: 0, y: 0, toJSON: () => ({}) });
  (canvas as unknown as { setPointerCapture: () => void }).setPointerCapture = () => {};
  (canvas as unknown as { releasePointerCapture: () => void }).releasePointerCapture = () => {};
  document.body.appendChild(canvas);
});
afterEach(() => {
  api?.dispose();
  api = null;
  canvas.remove();
});

describe("v0.12.5 자유 회전 컨트롤(TrackballControls)", () => {
  it("생성: Trackball 1개, 대상 = 활성 카메라(기본 직교), 타깃 = bbox 중심, 감쇠 없음·감도 상수", async () => {
    await make();
    expect(h.ctl).toHaveLength(1);
    const c = ctl();
    expect(c.constructor.name).toBe("FreeRotateControls");
    expect((c.object as OrthographicCamera).isOrthographicCamera).toBe(true);
    expect(c.target.distanceTo(CENTER)).toBeLessThan(1e-9);
    expect(c.staticMoving).toBe(STATIC_MOVING);
    expect(c.zoomSpeed).toBe(WHEEL_ZOOM_SPEED);
    expect(c.rotateSpeed).toBeCloseTo(trackballRotateSpeed(W, H), 12);
    expect(c.keys.every((k) => !/^Key/.test(k))).toBe(true); // A/S/D 키 전환 꺼짐
    expect(c.mouseButtons).toEqual({ LEFT: 0, MIDDLE: 1, RIGHT: 2 }); // 회전·줌·팬(Orbit 과 같음)
  });

  it("감도 상수: 화면 높이만큼 위아래로 끌면 ROTATE_TURNS_PER_HEIGHT 바퀴(=Orbit 기본 체감)", () => {
    // Trackball 1 px 각도 = speed·2/w, 목표 = 2π·turns/h
    const s = trackballRotateSpeed(W, H);
    expect((s * 2) / W).toBeCloseTo((2 * Math.PI * ROTATE_TURNS_PER_HEIGHT) / H, 12);
  });

  it("극점 제한 없음: 한 방향으로 계속 위로 끌면 꼭대기를 넘어 뒤집혀 계속 돈다, 한 바퀴면 제자리", async () => {
    await make("persp");
    const e0 = eye();
    const zs: number[] = [];
    // 화면 높이/8 씩 8번 = 1 바퀴(45°씩)
    for (let i = 0; i < 8; i++) {
      drag(400, 300, 400, 300 + H / 8);
      zs.push(eye().normalize().z);
    }
    // Orbit 이라면 z 가 극점(1) 근처에서 멈춘다 — 여기서는 +, - 를 모두 지나 되돌아온다
    expect(Math.max(...zs)).toBeGreaterThan(0.98);
    expect(Math.min(...zs)).toBeLessThan(-0.98);
    expect(eye().distanceTo(e0)).toBeLessThan(1e-6 * e0.length());
    // 좌우도 같은 방식(롤 없음 확인은 아님 — 끊김 없이 1 바퀴)
    for (let i = 0; i < 8; i++) drag(400, 300, 400 + H / 8, 300);
    expect(eye().distanceTo(e0)).toBeLessThan(1e-6 * e0.length());
  });

  it("투영 전환: 컨트롤 대상이 새 활성 카메라로 바뀌고 타깃·up·방향 유지, 전환 후에도 회전", async () => {
    const s = await make("ortho");
    drag(400, 300, 400, 300 + H / 3); // up 이 +Z 에서 벗어난 상태로 전환
    const up0 = ctl().object.up.clone();
    const dir0 = eye().normalize();
    s.setProjection("persp");
    expect((ctl().object as PerspectiveCamera).isPerspectiveCamera).toBe(true);
    expect(ctl().object.up.distanceTo(up0)).toBeLessThan(1e-9);
    expect(eye().normalize().distanceTo(dir0)).toBeLessThan(1e-9);
    expect(ctl().target.distanceTo(CENTER)).toBeLessThan(1e-9);
    const before = ctl().object.position.clone();
    drag(400, 300, 480, 300);
    expect(ctl().object.position.distanceTo(before)).toBeGreaterThan(1);
    s.setProjection("ortho");
    expect((ctl().object as OrthographicCamera).isOrthographicCamera).toBe(true);
    expect(s.projection()).toBe("ortho");
  });

  it("맞춤 보기(초기화): 회전으로 바뀐 up 을 +Z 로, 등각 +X+Y+Z 시점·타깃 = 중심으로 복원(두 투영 모두)", async () => {
    for (const p of ["ortho", "persp"] as const) {
      const s = await make(p);
      drag(400, 300, 400, 300 + H / 2); // 180° — 뒤집힘
      drag(400, 300, 400 + 150, 300);
      drag(100, 100, 300, 200, 2); // 팬으로 타깃도 옮김
      expect(ctl().object.up.z).toBeLessThan(0.9);
      s.fit();
      expect(ctl().object.up.distanceTo(new Vector3(0, 0, 1))).toBeLessThan(1e-9);
      expect(ctl().target.distanceTo(CENTER)).toBeLessThan(1e-9);
      expect(eye().normalize().distanceTo(new Vector3(1, 1, 1).normalize())).toBeLessThan(1e-9);
      // fit 직후 update 해도 잔여 회전 없음(감쇠 없음)
      const pos = ctl().object.position.clone();
      ctl().update();
      expect(ctl().object.position.distanceTo(pos)).toBeLessThan(1e-9);
      s.dispose();
      api = null;
    }
  });

  it("팬(오른쪽 버튼): 모델 중심이 커서를 그대로 따라감 — 원근·직교 모두, 방향 같음", async () => {
    for (const p of ["ortho", "persp"] as const) {
      const s = await make(p);
      const [x0, y0] = screenOf(CENTER);
      drag(200, 200, 280, 230, 2); // 오른쪽 80, 아래 30
      const [x1, y1] = screenOf(CENTER);
      expect(x1 - x0).toBeCloseTo(80, 3);
      expect(y1 - y0).toBeCloseTo(30, 3);
      s.dispose();
      api = null;
    }
  });

  it("휠: 아래로 굴리면 멀어짐(직교 zoom↓, 원근 거리↑), 위로 굴리면 가까워짐 — 렌더 루프가 남은 줌을 반영", async () => {
    const s = await make("ortho");
    const z0 = (ctl().object as OrthographicCamera).zoom;
    canvas.dispatchEvent(new WheelEvent("wheel", { deltaY: 100, cancelable: true }));
    await frame();
    await frame();
    const z1 = (ctl().object as OrthographicCamera).zoom;
    expect(z1).toBeLessThan(z0);
    expect(z0 / z1).toBeCloseTo(1 + 0.025 * WHEEL_ZOOM_SPEED, 6);
    s.setProjection("persp");
    const d0 = eye().length();
    canvas.dispatchEvent(new WheelEvent("wheel", { deltaY: -100, cancelable: true }));
    await frame();
    await frame();
    expect(eye().length()).toBeLessThan(d0);
  });

  it("렌더 루프: 끌기 중 프레임마다 update·렌더, 놓은 뒤 움직임 없으면 멈춤(onDemand)", async () => {
    const s = await make("ortho");
    await frame();
    const r0 = s.stats().renders;
    ptr("pointerdown", 400, 300);
    ptr("pointermove", 420, 330, 0, document);
    await frame();
    await frame();
    expect(s.stats().renders).toBeGreaterThan(r0);
    ptr("pointerup", 420, 330, 0, document);
    await frame();
    await frame();
    await frame();
    const r1 = s.stats().renders;
    await frame();
    await frame();
    expect(s.stats().renders).toBe(r1);
  });

  it("dispose: 컨트롤 이벤트 해제 — 이후 휠·끌기가 카메라를 바꾸지 않음", async () => {
    const s = await make("persp");
    const c = ctl();
    const pos = c.object.position.clone();
    const spy = vi.spyOn(c, "dispose");
    s.dispose();
    api = null;
    expect(spy).toHaveBeenCalledTimes(1);
    expect(canvas.style.touchAction).toBe("");
    canvas.dispatchEvent(new WheelEvent("wheel", { deltaY: 100, cancelable: true }));
    ptr("pointerdown", 400, 300);
    ptr("pointermove", 450, 350, 0, document);
    await frame();
    await frame();
    expect(c.object.position.distanceTo(pos)).toBe(0);
  });
});

describe("v0.15.1 시점 버튼: setView(축, 방향)·fit(bbox) — Trackball target·up 함께, 직교·원근", () => {
  /** bbox 8 꼭짓점의 NDC 최대 |x|·|y| */
  const ndcExtent = (b: { min: number[]; max: number[] }) => {
    const c = ctl().object;
    c.updateMatrixWorld();
    let ax = 0;
    let ay = 0;
    for (let i = 0; i < 8; i++) {
      const q = new Vector3(i & 1 ? b.max[0] : b.min[0], i & 2 ? b.max[1] : b.min[1], i & 4 ? b.max[2] : b.min[2]).project(c);
      ax = Math.max(ax, Math.abs(q.x));
      ay = Math.max(ay, Math.abs(q.y));
    }
    return { ax, ay };
  };
  const cases: ["x" | "y" | "z", 1 | -1, [number, number, number], [number, number, number]][] = [
    ["x", 1, [1, 0, 0], [0, 0, 1]],
    ["x", -1, [-1, 0, 0], [0, 0, 1]],
    ["y", 1, [0, 1, 0], [0, 0, 1]],
    ["y", -1, [0, -1, 0], [0, 0, 1]],
    ["z", 1, [0, 0, 1], [0, 1, 0]],
    ["z", -1, [0, 0, -1], [0, 1, 0]],
  ];
  it("정면 ±X·±Y·±Z: 카메라 = 그 쪽, up(X·Y = +Z, Z = +Y), 타깃 = 중심, 꽉 참(화면 안·직교는 여백 1.08), 잔여 회전 없음", async () => {
    for (const p of ["ortho", "persp"] as const) {
      const s = await make(p);
      drag(400, 300, 520, 380); // 아무 회전 후
      drag(100, 100, 300, 200, 2);
      for (const [axis, sign, eyeDir, up] of cases) {
        s.setView(axis, sign);
        expect(ctl().target.distanceTo(CENTER)).toBeLessThan(1e-9);
        expect(eye().normalize().distanceTo(new Vector3(...eyeDir))).toBeLessThan(1e-9);
        expect(ctl().object.up.distanceTo(new Vector3(...up))).toBeLessThan(1e-9);
        const { ax, ay } = ndcExtent(BBOX);
        expect(Math.max(ax, ay)).toBeLessThanOrEqual(1 + 1e-9);
        if (p === "ortho") expect(Math.max(ax, ay)).toBeCloseTo(1 / 1.08, 6);
        else expect(Math.max(ax, ay)).toBeGreaterThan(0.6);
        const pos = ctl().object.position.clone();
        ctl().update();
        expect(ctl().object.position.distanceTo(pos)).toBeLessThan(1e-9);
        expect(ctl().object.up.distanceTo(new Vector3(...up))).toBeLessThan(1e-9);
      }
      s.setView("iso", 1);
      expect(eye().normalize().distanceTo(new Vector3(1, 1, 1).normalize())).toBeLessThan(1e-9);
      s.setView("iso", -1);
      expect(eye().normalize().distanceTo(new Vector3(-1, -1, 1).normalize())).toBeLessThan(1e-9);
      s.dispose();
      api = null;
    }
  });

  it("fit(bbox): 지금 시선 그대로 그 bbox 꽉 차게(화면비 반영) — 작은 선택 영역도, 투영 전환 뒤에도", async () => {
    for (const p of ["ortho", "persp"] as const) {
      const s = await make(p);
      s.setView("z", 1);
      const sel = { min: [10, 10, 0], max: [30, 20, 5] };
      s.fit(sel);
      expect(ctl().target.distanceTo(new Vector3(20, 15, 2.5))).toBeLessThan(1e-9);
      expect(eye().normalize().distanceTo(new Vector3(0, 0, 1))).toBeLessThan(1e-9);
      const e1 = ndcExtent(sel);
      expect(Math.max(e1.ax, e1.ay)).toBeLessThanOrEqual(1 + 1e-9);
      // 가로 20 > 세로 10 × 화면비 4:3 → 가로가 맞춤 기준
      if (p === "ortho") expect(e1.ax).toBeCloseTo(1 / 1.08, 6);
      else expect(e1.ax).toBeGreaterThan(0.6);
      s.fit(BBOX); // 모델 전체
      const e2 = ndcExtent(BBOX);
      expect(Math.max(e2.ax, e2.ay)).toBeLessThanOrEqual(1 + 1e-9);
      s.setProjection(p === "ortho" ? "persp" : "ortho");
      s.fit(BBOX);
      const e3 = ndcExtent(BBOX);
      expect(Math.max(e3.ax, e3.ay)).toBeLessThanOrEqual(1 + 1e-9);
      expect(Math.max(e3.ax, e3.ay)).toBeGreaterThan(0.6);
      s.dispose();
      api = null;
    }
  });
});

describe("v0.15.1 강조 점 setMarkers", () => {
  it("점 추가·교체·지우기(렌더 요청), dispose 안전", async () => {
    const s = await make("ortho");
    expect(s.setMarkers).toBeTypeOf("function");
    s.setMarkers!(Float32Array.from([0, 0, 0, 10, 10, 10]));
    s.setMarkers!(Float32Array.from([1, 2, 3]));
    s.setMarkers!(null);
    s.setMarkers!(Float32Array.from([1, 2, 3]));
    await frame();
    expect(s.stats().renders).toBeGreaterThan(0);
  });
});
