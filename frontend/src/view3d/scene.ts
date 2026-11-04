// three 장면(계약 §6·§8). 이 파일만 three 를 import 한다 → 동적 import 로 별도 청크. 시험에서는 mock.
// 좌표 mm·Z-up. onDemand 렌더: 카메라·상태 변경 때만 requestAnimationFrame 1회. 언마운트 시 geometry·material·texture·renderer dispose.
// v0.12.5: 회전은 TrackballControls(화면 공간, 극점 제한 없음 — 상하·좌우 무한 연속 회전). up 이 회전을 따라 바뀌므로 맞춤 보기에서 +Z 로 복원.
import {
  AmbientLight, BufferAttribute, BufferGeometry, CanvasTexture, Color, ConeGeometry, DirectionalLight, DoubleSide, HemisphereLight, InstancedMesh,
  Matrix4, Mesh, MeshBasicMaterial, Points, PointsMaterial, MeshLambertMaterial, OrthographicCamera, PerspectiveCamera, Quaternion, Raycaster, Scene, ShaderMaterial, SphereGeometry, Sprite, SpriteMaterial,
  SRGBColorSpace, Vector2, Vector3, Vector4, WebGLRenderTarget, WebGLRenderer,
} from "three";
import { TrackballControls } from "three/examples/jsm/controls/TrackballControls.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { LineSegments2 } from "three/examples/jsm/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/examples/jsm/lines/LineSegmentsGeometry.js";
import { ARROW_COLOR, ARROW_PICK_PX, ARROW_SELECTED, CONE_ASPECT, CONE_CLUSTER_SCALE, CONE_LEN_SCALE, CONE_PX, LINE_PX, SUPPORT_LINE_PX, type ArrowSpec } from "./arrows";
import { applyDeform } from "./deform";
import { LUT_DIV_LINEAR, LUT_LINEAR, fillVertexColors, srgbToLinear } from "./colors";
import { idToRgb, type IdPatch, type Rect } from "./select/lasso";
import { ndcToPx, pickSegmentScreen, type ScreenSeg, type V3 } from "./pick";
import { DEFAULT_PROJECTION, PERSP_FOV as FOV, orthoClip, orthoHalfHeightFromPersp, perspPositionFromOrtho, pxWorld, type Projection } from "./projection";
import type { CreateScene, GeoData, PickEvent, SceneApi, SceneOptions } from "./sceneApi";
import { fitView, validBbox, viewBasis, type Bbox, type FitResult } from "./viewFit";
import { SUPPORT_COLOR, SYMBOL_GLYPH, type SupportSpec } from "./supports";
import { PAN_SPEED, STATIC_MOVING, WHEEL_ZOOM_SPEED, trackballRotateSpeed } from "../lib/viewerControls";

const LOD_RESTORE_MS = 250;
/** Trackball 키(A/S/D 누른 채 끌기 = 회전/줌/팬 전환)는 쓰지 않는다 — 다른 입력란 타이핑과 섞이지 않게 */
const NO_KEY = "esl-no-key";

/** TrackballControls 내부 상태(타입 선언 없음) */
interface TrackballInternals {
  _eye: Vector3;
  _panStart: Vector2;
  _panEnd: Vector2;
}
const _right = new Vector3();
const _upP = new Vector3();
const _pan = new Vector3();

/**
 * 자유 회전 컨트롤: TrackballControls + 화면 공간 팬(커서를 그대로 따라감).
 * 원래 Trackball 팬은 화면 비율 × 카메라 거리라 원근은 가로·세로 배율이 다르고 직교는 카메라 거리에 좌우된다 —
 * 이전 OrbitControls(screenSpacePanning)처럼 타깃 깊이의 보이는 폭·높이로 환산한다.
 */
export class FreeRotateControls extends TrackballControls {
  _panCamera() {
    const s = this as unknown as TrackballInternals;
    const dx = s._panEnd.x - s._panStart.x;
    const dy = s._panEnd.y - s._panStart.y;
    if (!dx && !dy) return;
    const cam = this.object as PerspectiveCamera | OrthographicCamera;
    const sw = Math.max(1, this.screen.width);
    const sh = Math.max(1, this.screen.height);
    let visW: number;
    let visH: number;
    if ((cam as OrthographicCamera).isOrthographicCamera) {
      const o = cam as OrthographicCamera;
      visW = (o.right - o.left) / Math.max(o.zoom, 1e-12);
      visH = (o.top - o.bottom) / Math.max(o.zoom, 1e-12);
    } else {
      const p = cam as PerspectiveCamera;
      visH = 2 * s._eye.length() * Math.tan((p.fov * Math.PI) / 360);
      visW = (visH * sw) / sh;
    }
    // 오른쪽 = up × 눈(타깃→카메라), 화면 위 = 눈 × 오른쪽. 커서가 오른쪽·아래로 가면 모델도 오른쪽·아래로(카메라는 반대)
    _right.crossVectors(cam.up, s._eye).normalize();
    _upP.crossVectors(s._eye, _right).normalize();
    _pan.copy(_right).multiplyScalar(-dx * visW * this.panSpeed).addScaledVector(_upP, dy * visH * this.panSpeed);
    cam.position.add(_pan);
    this.target.add(_pan);
    if (this.staticMoving) s._panStart.copy(s._panEnd);
    else s._panStart.add(new Vector2(dx, dy).multiplyScalar(this.dynamicDampingFactor));
  }
}

interface Layer {
  geo: GeoData;
  mesh: Mesh;
  geometry: BufferGeometry;
  position: BufferAttribute;
  color: BufferAttribute;
  base: Float32Array;
  dirty: boolean;
}

function textSprite(text: string, glyph: string | null, opts: { color: string; bg?: string; px: number }): Sprite {
  const dpr = 2;
  const font = `600 ${22 * dpr}px "Malgun Gothic","Noto Sans KR",system-ui,sans-serif`;
  const meas = document.createElement("canvas").getContext("2d");
  let tw = text.length * 13 * dpr;
  if (meas) {
    meas.font = font;
    tw = meas.measureText(text).width;
  }
  const gw = glyph ? 34 * dpr : 0;
  const pad = 6 * dpr;
  const w = Math.ceil(gw + tw + pad * 2);
  const h = 34 * dpr;
  const cv = document.createElement("canvas");
  cv.width = w;
  cv.height = h;
  const g = cv.getContext("2d");
  if (g) {
    if (opts.bg) {
      g.fillStyle = opts.bg;
      g.fillRect(0, 0, w, h);
    }
    g.fillStyle = opts.color;
    g.textBaseline = "middle";
    g.font = font;
    if (glyph) {
      g.font = `700 ${30 * dpr}px system-ui,sans-serif`;
      g.fillText(glyph, pad, h / 2 + 1 * dpr);
      g.font = font;
    }
    g.fillText(text, pad + gw, h / 2);
  }
  const tex = new CanvasTexture(cv);
  tex.colorSpace = SRGBColorSpace;
  const mat = new SpriteMaterial({ map: tex, depthTest: false, transparent: true, sizeAttenuation: false });
  const sp = new Sprite(mat);
  sp.userData.aspect = w / h;
  sp.userData.px = opts.px;
  sp.renderOrder = 10;
  return sp;
}

export const createScene: CreateScene = (canvas: HTMLCanvasElement, opts: SceneOptions): SceneApi => {
  const renderer = new WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new Scene();
  scene.background = new Color(opts.background);
  // 투영 2종(원근/직교) — 활성 카메라 하나만 장면에 두고 헤드라이트·회전 컨트롤을 옮겨 단다
  const persp = new PerspectiveCamera(FOV, 1, opts.diag / 1000, opts.diag * 100);
  const ortho = new OrthographicCamera(-1, 1, 1, -1, -opts.diag, opts.diag);
  persp.up.set(0, 0, 1);
  ortho.up.set(0, 0, 1);
  let proj: Projection = opts.projection ?? DEFAULT_PROJECTION;
  let camera: PerspectiveCamera | OrthographicCamera = proj === "ortho" ? ortho : persp;
  let aspect = 1;
  let orthoHalfH = 1;
  const center = new Vector3((opts.bbox.min[0] + opts.bbox.max[0]) / 2, (opts.bbox.min[1] + opts.bbox.max[1]) / 2, (opts.bbox.min[2] + opts.bbox.max[2]) / 2);
  const v3 = (v: Vector3): V3 => [v.x, v.y, v.z];
  const tmpDir = new Vector3();
  /** 직교 보이는 높이(월드) = 2·halfH / zoom */
  const orthoVisibleH = () => (2 * orthoHalfH) / Math.max(ortho.zoom, 1e-12);
  /** 직교 frustum: 반높이·화면비 반영 + 근/원은 시선 방향 모델 중심 ± k·대각선(클리핑 없음) */
  const applyOrtho = () => {
    ortho.top = orthoHalfH;
    ortho.bottom = -orthoHalfH;
    ortho.left = -orthoHalfH * aspect;
    ortho.right = orthoHalfH * aspect;
    ortho.updateMatrixWorld();
    const c = orthoClip(v3(ortho.position), v3(ortho.getWorldDirection(tmpDir)), v3(center), opts.diag);
    ortho.near = c.near;
    ortho.far = c.far;
    ortho.updateProjectionMatrix();
  };

  scene.add(new HemisphereLight(0xffffff, 0x8a8f99, 1.1));
  scene.add(new AmbientLight(0xffffff, 0.35));
  const headlight = new DirectionalLight(0xffffff, 1.4);
  camera.add(headlight);
  scene.add(camera);

  const controls = new FreeRotateControls(camera, canvas);
  const activate = () => {
    const other = camera === persp ? ortho : persp;
    scene.remove(other);
    scene.add(camera);
    camera.add(headlight);
    controls.object = camera;
    controls.update();
  };
  // 버튼: 왼쪽 회전·가운데 줌·오른쪽 팬(Orbit 과 같음), 휠 줌(아래로 = 멀어짐)
  controls.staticMoving = STATIC_MOVING;
  controls.zoomSpeed = WHEEL_ZOOM_SPEED;
  controls.panSpeed = PAN_SPEED;
  controls.keys = [NO_KEY, NO_KEY, NO_KEY];

  let renders = 0;
  let raf = 0;
  let disposed = false;
  const invalidate = () => {
    if (raf || disposed) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      if (disposed) return;
      renders++;
      if (proj === "ortho") applyOrtho(); // 회전 후 근/원 재계산
      sizeSprites(); // 직교 줌은 화면 크기를 바꾼다
      updateLineArrows();
      renderer.render(scene, camera);
    });
  };

  // ---- 표면
  const surfMat = new MeshLambertMaterial({ vertexColors: true, side: DoubleSide });
  const layers: { full: Layer | null; lod: Layer | null } = { full: null, lod: null };
  let u: Float32Array | null = null;
  let kscale = 0;
  let colorArgs: { values: Float32Array; min: number; max: number } | null = null;
  let lodTimer: ReturnType<typeof setTimeout> | null = null;

  const makeLayer = (geo: GeoData, compute: boolean): Layer => {
    const geometry = new BufferGeometry();
    const position = new BufferAttribute(new Float32Array(geo.positions), 3);
    const color = new BufferAttribute(new Float32Array(geo.positions.length).fill(0.75), 3);
    geometry.setAttribute("position", position);
    geometry.setAttribute("color", color);
    geometry.setIndex(new BufferAttribute(geo.indices, 1));
    if (compute) geometry.computeVertexNormals(); // 로드 직후 1회 — 변형 중 재계산 없음
    else geometry.computeVertexNormals();
    geometry.computeBoundingSphere();
    const mesh = new Mesh(geometry, surfMat);
    mesh.frustumCulled = false;
    scene.add(mesh);
    return { geo, mesh, geometry, position, color, base: geo.positions, dirty: false };
  };
  const disposeLayer = (l: Layer | null) => {
    if (!l) return;
    scene.remove(l.mesh);
    l.geometry.dispose();
  };
  const srcOf = (l: Layer) => l.geo.src;

  let lut: Float32Array = LUT_LINEAR;
  const paintLayer = (l: Layer) => {
    if (!colorArgs) return;
    fillVertexColors(colorArgs.values, colorArgs.min, colorArgs.max, l.color.array as Float32Array, srcOf(l), lut);
    l.color.needsUpdate = true;
  };
  const deformLayer = (l: Layer) => {
    const out = l.position.array as Float32Array;
    const src = srcOf(l);
    if (!src) applyDeform(l.base, u, kscale, out);
    else {
      for (let i = 0; i < src.length; i++) {
        const s = src[i] * 3;
        for (let c = 0; c < 3; c++) out[i * 3 + c] = l.base[i * 3 + c] + (u ? kscale * u[s + c] : 0);
      }
    }
    l.position.needsUpdate = true;
    l.geometry.computeBoundingSphere();
  };
  const showLod = (on: boolean) => {
    if (elemLayer) return; // v0.15.0 요소 모드: 노드 층은 숨긴 채
    if (!layers.lod || !layers.full) return;
    layers.lod.mesh.visible = on;
    layers.full.mesh.visible = !on;
    if (!on && layers.full.dirty) {
      deformLayer(layers.full);
      paintLayer(layers.full);
      layers.full.dirty = false;
    }
  };
  const scheduleFull = () => {
    if (!layers.lod) return;
    showLod(true);
    if (lodTimer) clearTimeout(lodTimer);
    lodTimer = setTimeout(() => {
      lodTimer = null;
      showLod(false);
      invalidate();
    }, LOD_RESTORE_MS);
  };
  const currentLayer = (): Layer | null => {
    if (layers.lod?.mesh.visible) return layers.lod;
    return layers.full;
  };
  /** 현재 (변형된) 정점 위치 — 원 정점 번호 기준 */
  const vertexPos = (vertex: number): V3 | null => {
    const l = layers.full;
    if (!l) return null;
    const a = l.base;
    const i = vertex * 3;
    if (i + 2 >= a.length) return null;
    return u && kscale ? [a[i] + kscale * u[i], a[i + 1] + kscale * u[i + 1], a[i + 2] + kscale * u[i + 2]] : [a[i], a[i + 1], a[i + 2]];
  };

  // ---- 화살표(계약 §6.2, L3-C2): 픽셀 고정 두께 선(LineSegments2) + 화면 크기 제한이 있는 가는 원뿔 머리
  const headGeo = new ConeGeometry(1, 1, 16);
  headGeo.translate(0, 0.5, 0);
  const arrowMat = new MeshLambertMaterial({ color: 0xffffff });
  let arrowHead: InstancedMesh | null = null;
  let arrows: ArrowSpec[] = [];
  /** 원뿔 머리 반지름(화면 px) — 화살표 클릭 허용 계산용(writeHeads 가 갱신) */
  const headRpx: number[] = [];
  let selArrow: number | null = null;
  const arrowLabels: Sprite[] = [];
  const Y = new Vector3(0, 1, 0);
  const tmpM = new Matrix4();
  const tmpQ = new Quaternion();
  const tmpP = new Vector3();
  const tmpS = new Vector3();
  const tmpC = new Color();
  interface LineGroup {
    obj: LineSegments2;
    idx: number[];
  }
  const lineGroups: LineGroup[] = [];
  /** 1 px 의 월드 길이(점까지 거리 t) */
  const pxWorldAt = (t: number) => pxWorld(proj, t, canvas.clientHeight, orthoVisibleH());

  const fillLineGroup = (g: LineGroup) => {
    const pos: number[] = [];
    const col: number[] = [];
    for (const i of g.idx) {
      const a = arrows[i];
      const c = tmpC.set(i === selArrow ? ARROW_SELECTED : a.color || ARROW_COLOR);
      // 선은 끝점까지(원뿔이 덮음)
      pos.push(a.tail[0], a.tail[1], a.tail[2], a.tail[0] + a.dir[0] * a.length, a.tail[1] + a.dir[1] * a.length, a.tail[2] + a.dir[2] * a.length);
      col.push(c.r, c.g, c.b, c.r, c.g, c.b);
    }
    g.obj.geometry.setPositions(pos);
    g.obj.geometry.setColors(col);
  };
  /** 원뿔 머리: 높이 = 기준 머리 길이 × CONE_LEN_SCALE 을 화면 CONE_PX 범위로 제한, 반지름 = 높이 × CONE_ASPECT */
  const writeHeads = () => {
    if (!arrowHead) return;
    arrows.forEach((a, i) => {
      const dist = camera.position.distanceTo(tmpP.set(a.tail[0], a.tail[1], a.tail[2]));
      const w = pxWorldAt(dist);
      const kk = a.kind === "cluster" ? CONE_CLUSTER_SCALE : 1;
      const hl = Math.max(CONE_PX.min * kk * w, Math.min(CONE_PX.max * kk * w, a.headLen * CONE_LEN_SCALE * kk));
      const hr = hl * CONE_ASPECT;
      headRpx[i] = hr / Math.max(w, 1e-12);
      tmpQ.setFromUnitVectors(Y, tmpP.set(a.dir[0], a.dir[1], a.dir[2]));
      tmpP.set(a.tail[0] + a.dir[0] * (a.length - hl), a.tail[1] + a.dir[1] * (a.length - hl), a.tail[2] + a.dir[2] * (a.length - hl));
      tmpM.compose(tmpP, tmpQ, tmpS.set(hr, hl, hr));
      arrowHead!.setMatrixAt(i, tmpM);
      arrowHead!.setColorAt(i, tmpC.set(i === selArrow ? ARROW_SELECTED : a.color || ARROW_COLOR));
    });
    arrowHead.instanceMatrix.needsUpdate = true;
    if (arrowHead.instanceColor) arrowHead.instanceColor.needsUpdate = true;
  };
  /** 렌더 직전: 선 해상도(px 두께 기준) 갱신, 머리 크기는 카메라 거리에 맞춰 재계산 */
  const updateLineArrows = () => {
    const w = Math.max(1, canvas.clientWidth);
    const h = Math.max(1, canvas.clientHeight);
    supMat.resolution.set(w, h);
    overlayMat.resolution.set(w, h);
    for (const g of lineGroups) g.obj.material.resolution.set(w, h);
    writeHeads();
  };
  const buildArrows = () => {
    for (const kind of ["node", "cluster"] as const) {
      const idx = arrows.map((a, i) => (a.kind === kind ? i : -1)).filter((i) => i >= 0);
      if (!idx.length) continue;
      const mat = new LineMaterial({ linewidth: LINE_PX[kind], vertexColors: true, worldUnits: false });
      const obj = new LineSegments2(new LineSegmentsGeometry(), mat);
      obj.frustumCulled = false;
      obj.renderOrder = 5;
      const g: LineGroup = { obj, idx };
      fillLineGroup(g);
      scene.add(obj);
      lineGroups.push(g);
    }
    arrowHead = new InstancedMesh(headGeo, arrowMat, arrows.length);
    arrowHead.frustumCulled = false;
    scene.add(arrowHead);
    updateLineArrows();
  };
  const clearArrows = () => {
    if (arrowHead) {
      scene.remove(arrowHead);
      arrowHead.dispose();
      arrowHead = null;
    }
    for (const g of lineGroups) {
      scene.remove(g.obj);
      g.obj.geometry.dispose();
      g.obj.material.dispose();
    }
    lineGroups.length = 0;
    for (const s of arrowLabels) {
      scene.remove(s);
      s.material.map?.dispose();
      s.material.dispose();
    }
    arrowLabels.length = 0;
  };

  // ---- 선택 표식·군집 꼬리 구
  const sphereGeo = new SphereGeometry(1, 16, 12);
  const selMarker = new Mesh(sphereGeo, new MeshBasicMaterial({ color: ARROW_SELECTED, depthTest: false }));
  selMarker.visible = false;
  selMarker.renderOrder = 9;
  selMarker.scale.setScalar(opts.diag * 0.011);
  scene.add(selMarker);
  // v0.15.1 강조 점(고정 침범 노드 등) — 화면 크기 고정·가려져도 보임
  const markMat = new PointsMaterial({ color: 0xd61f1f, size: 9, sizeAttenuation: false, depthTest: false });
  let marks: Points | null = null;

  // ---- v0.15.0 요소 모드(비드 직접 선택): 비색인 삼각형 표면(요소별 평면 음영) + ID 버퍼 + 경계선
  interface ElemLayer {
    mesh: Mesh;
    idMesh: Mesh;
    geometry: BufferGeometry;
    color: BufferAttribute;
    tri2elem: Uint32Array;
    nElems: number;
  }
  let elemLayer: ElemLayer | null = null;
  const elemMat = new MeshLambertMaterial({ vertexColors: true, side: DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
  const idMat = new ShaderMaterial({
    vertexShader: "attribute vec3 idc; varying vec3 vIdc; void main() { vIdc = idc; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: "varying vec3 vIdc; void main() { gl_FragColor = vec4(vIdc, 1.0); }",
    side: DoubleSide,
  });
  const idScene = new Scene();
  let idTarget: WebGLRenderTarget | null = null;
  let idKey = "";
  const overlayMat = new LineMaterial({ color: 0x111111, linewidth: 2, worldUnits: false });
  let overlay: LineSegments2 | null = null;
  const disposeElemLayer = () => {
    if (!elemLayer) return;
    scene.remove(elemLayer.mesh);
    idScene.remove(elemLayer.idMesh);
    elemLayer.geometry.dispose();
    elemLayer = null;
  };
  const tmpV4 = new Vector4();
  const viewProj = new Matrix4();

  // ---- 3-2-1 지지 기호
  const supMat = new LineMaterial({ color: SUPPORT_COLOR, linewidth: SUPPORT_LINE_PX, depthTest: false, transparent: true, worldUnits: false });
  let supLines: LineSegments2 | null = null;
  const supSprites: Sprite[] = [];
  let supports: SupportSpec[] = [];
  const clearSupports = () => {
    if (supLines) {
      scene.remove(supLines);
      supLines.geometry.dispose();
      supLines = null;
    }
    for (const s of supSprites) {
      scene.remove(s);
      s.material.map?.dispose();
      s.material.dispose();
    }
    supSprites.length = 0;
  };

  // 화면 크기 고정 스프라이트: 높이 px → scale
  const sizeSprites = () => {
    const h = Math.max(1, canvas.clientHeight);
    // sizeAttenuation=false: 원근은 깊이로 나눠져 2·tan(FOV/2), 직교는 보이는 높이(월드) 그대로
    const t = proj === "ortho" ? orthoVisibleH() : 2 * Math.tan((FOV * Math.PI) / 360);
    for (const s of [...supSprites, ...arrowLabels]) {
      const frac = (s.userData.px as number) / h;
      s.scale.set(frac * t * (s.userData.aspect as number), frac * t, 1);
    }
  };

  // ---- 크기
  const resize = () => {
    const w = Math.max(1, canvas.clientWidth);
    const h = Math.max(1, canvas.clientHeight);
    renderer.setSize(w, h, false);
    aspect = w / h;
    controls.handleResize();
    controls.rotateSpeed = trackballRotateSpeed(w, h);
    persp.aspect = aspect;
    persp.updateProjectionMatrix();
    applyOrtho();
    sizeSprites();
    invalidate();
  };
  const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => resize()) : null;
  ro?.observe(canvas);

  const fit = () => {
    const r = opts.diag / 2;
    const dist = (r / Math.sin((FOV * Math.PI) / 360)) * 0.8;
    const dir = new Vector3(1, 1, 1).normalize();
    camera.position.copy(center).addScaledVector(dir, dist);
    camera.up.set(0, 0, 1);
    controls.target.copy(center);
    camera.lookAt(center);
    if (camera === ortho) {
      // 원근 맞춤과 같은 크기: 반높이 = dist·tan(FOV/2), 줌 1
      orthoHalfH = orthoHalfHeightFromPersp(v3(camera.position), v3(center));
      ortho.zoom = 1;
      applyOrtho();
    }
    controls.update();
    invalidate();
  };

  // v0.15.1 시점·꽉 차게: 카메라 위치·up·Trackball target 을 함께 바꾸고(잔여 회전 없음), 직교는 반높이·zoom 1 로
  const modelBbox: Bbox = opts.bbox;
  const applyFit = (r: FitResult) => {
    camera.position.set(r.position[0], r.position[1], r.position[2]);
    camera.up.set(r.up[0], r.up[1], r.up[2]);
    controls.target.set(r.target[0], r.target[1], r.target[2]);
    camera.lookAt(controls.target);
    if (camera === ortho) {
      orthoHalfH = r.halfH;
      ortho.zoom = 1;
      applyOrtho();
    } else persp.updateProjectionMatrix();
    controls.update();
    sizeSprites();
    invalidate();
  };
  const fitBox = (b: Bbox) => {
    const eye = v3(tmpDir.copy(camera.position).sub(controls.target));
    if (!(Math.hypot(eye[0], eye[1], eye[2]) > 0)) eye.splice(0, 3, 1, 1, 1);
    applyFit(fitView(b, eye, v3(camera.up), aspect, proj));
  };

  // Trackball 은 입력을 쌓아 두고 update() 에서 반영한다 → 조작 중(start~end)과 그 뒤 움직임이 남은 동안만 매 프레임 update
  let ctlRaf = 0;
  let interacting = false;
  let moved = false;
  const pump = () => {
    if (ctlRaf || disposed) return;
    ctlRaf = requestAnimationFrame(() => {
      ctlRaf = 0;
      if (disposed) return;
      moved = false;
      controls.update();
      if (interacting || moved) pump();
    });
  };
  controls.addEventListener("change", () => {
    moved = true;
    invalidate();
  });
  controls.addEventListener("start", () => {
    interacting = true;
    if (lodTimer) clearTimeout(lodTimer);
    showLod(true);
    pump();
    invalidate();
  });
  controls.addEventListener("end", () => {
    interacting = false;
    pump(); // 휠은 start·end 가 한꺼번에 온다 — 남은 줌을 다음 프레임에 반영
    scheduleFull();
  });

  // ---- 선택(클릭)
  let pickCb: ((e: PickEvent) => void) | null = null;
  const raycaster = new Raycaster();
  const tmpPick = new Vector3();
  let down: { x: number; y: number; t: number } | null = null;
  const ndc = (ev: MouseEvent) => {
    const r = canvas.getBoundingClientRect();
    return new Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  };
  const doPick = (ev: MouseEvent): PickEvent => {
    const p = ndc(ev);
    raycaster.setFromCamera(p, camera);
    // 직교: setFromCamera 의 원점은 카메라 평면(z_view = 0). near 가 음수면(카메라가 모델 안쪽) 그만큼 뒤로 물려 앞쪽 모델도 맞힌다
    if (camera === ortho && ortho.near < 0) raycaster.ray.origin.addScaledVector(raycaster.ray.direction, ortho.near);
    const pxW = pxWorldAt; // 거리 t 에서 1 px 의 월드 길이(직교는 거리 무관)
    // 1) 지지 기호 2) 화살표 3) 표면 — 화살표는 화면 공간(투영 선분까지 px 거리, 머리 포함) 허용 ARROW_PICK_PX
    const supIdx = supports.findIndex((s) => {
      const v = new Vector3(s.position[0], s.position[1], s.position[2]).sub(raycaster.ray.origin);
      const t = v.dot(raycaster.ray.direction);
      if (t <= 0) return false;
      const off = v.addScaledVector(raycaster.ray.direction, -t).length();
      return off <= pxW(t) * 14;
    });
    // v0.8.0: 예전 광선-선분 월드 거리 허용(6 px)은 2 px 선에 너무 좁아, 직교 기본(v0.7.1)에서 짧게 보이는 화살표를
    // 거의 못 눌렀다(원근은 가까운 화살표가 커 보여 가려졌음). 화면 공간 거리로 원근·직교·줌 모두 같은 px 허용.
    const r = canvas.getBoundingClientRect();
    const W = Math.max(1, r.width);
    const H = Math.max(1, r.height);
    const toPx = (q: V3) => {
      tmpPick.set(q[0], q[1], q[2]).project(camera);
      return { p: ndcToPx(tmpPick.x, tmpPick.y, W, H), z: tmpPick.z };
    };
    const ssegs = arrows.map((a, i): ScreenSeg | null => {
      const A = toPx(a.tail);
      const B = toPx([a.tail[0] + a.dir[0] * a.length, a.tail[1] + a.dir[1] * a.length, a.tail[2] + a.dir[2] * a.length]);
      if (Math.abs(A.z) > 1 || Math.abs(B.z) > 1) return null; // 근/원 평면 밖(원근 카메라 뒤 포함)
      return { a: A.p, b: B.p, depth: Math.min(A.z, B.z), tol: Math.max(ARROW_PICK_PX, (headRpx[i] ?? 0) + 2) };
    });
    const ai = pickSegmentScreen([ev.clientX - r.left, ev.clientY - r.top], ssegs);
    if (ai >= 0) return { type: "arrow", index: ai };
    if (supIdx >= 0) return { type: "support", index: supIdx };
    const l = currentLayer();
    if (l) {
      const hit = raycaster.intersectObject(l.mesh, false)[0];
      if (hit?.face) {
        const ids = [hit.face.a, hit.face.b, hit.face.c];
        let best = ids[0];
        let bd = Infinity;
        for (const id of ids) {
          const dx = l.position.getX(id) - hit.point.x;
          const dy = l.position.getY(id) - hit.point.y;
          const dz = l.position.getZ(id) - hit.point.z;
          const dd = dx * dx + dy * dy + dz * dz;
          if (dd < bd) (bd = dd), (best = id);
        }
        const src = srcOf(l);
        return { type: "vertex", vertex: src ? src[best] : best };
      }
    }
    return { type: "none" };
  };
  const onDown = (e: PointerEvent) => {
    down = { x: e.clientX, y: e.clientY, t: performance.now() };
  };
  const onUp = (e: PointerEvent) => {
    if (!down) return;
    const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
    down = null;
    if (moved > 4 || e.button !== 0) return;
    pickCb?.(doPick(e));
  };
  canvas.addEventListener("pointerdown", onDown);
  canvas.addEventListener("pointerup", onUp);

  const api: SceneApi = {
    setGeometry(full, lod) {
      disposeLayer(layers.full);
      disposeLayer(layers.lod);
      layers.full = makeLayer(full, true);
      layers.lod = lod ? makeLayer(lod, false) : null;
      if (layers.lod) {
        layers.full.mesh.visible = false;
        layers.full.dirty = true; // 첫 표시는 LOD, 250 ms 뒤 전체 해상도
        scheduleFull();
      }
      if (colorArgs) {
        paintLayer(layers.full);
        if (layers.lod) paintLayer(layers.lod);
      }
      invalidate();
    },
    setColors(values, min, max) {
      colorArgs = { values, min, max };
      if (layers.lod) {
        paintLayer(layers.lod);
        layers.full!.dirty = true;
        if (!layers.lod.mesh.visible) paintLayer(layers.full!), (layers.full!.dirty = false);
        else scheduleFull();
      } else if (layers.full) paintLayer(layers.full);
      invalidate();
    },
    setDeform(uu, k) {
      u = uu;
      kscale = uu ? k : 0;
      if (layers.lod) {
        deformLayer(layers.lod);
        layers.full!.dirty = true;
        scheduleFull();
      } else if (layers.full) deformLayer(layers.full);
      invalidate();
    },
    setArrows(list, selected) {
      clearArrows();
      arrows = list;
      selArrow = selected;
      if (list.length) {
        buildArrows();
        list.forEach((a) => {
          if (!a.label) return;
          const sp = textSprite(a.label, null, { color: "#7f0b16", bg: "rgba(255,255,255,0.82)", px: 20 });
          sp.position.set(a.tail[0] + a.dir[0] * a.length, a.tail[1] + a.dir[1] * a.length, a.tail[2] + a.dir[2] * a.length);
          sp.center.set(0, 0.5);
          scene.add(sp);
          arrowLabels.push(sp);
        });
        sizeSprites();
      }
      invalidate();
    },
    setSupports(list) {
      clearSupports();
      supports = list;
      const pts: number[] = [];
      for (const s of list) {
        for (const [a, b] of s.segments) pts.push(...a, ...b);
        const sp = textSprite(s.symbol.label, SYMBOL_GLYPH[s.symbol.kind], { color: SUPPORT_COLOR, bg: "rgba(255,255,255,0.78)", px: 22 });
        sp.position.set(s.position[0], s.position[1], s.position[2]);
        sp.center.set(0.1, 1.0); // 기호 꼭짓점이 노드에 닿도록
        scene.add(sp);
        supSprites.push(sp);
      }
      if (pts.length) {
        const g = new LineSegmentsGeometry();
        g.setPositions(pts);
        supLines = new LineSegments2(g, supMat);
        supLines.frustumCulled = false;
        supLines.renderOrder = 8;
        scene.add(supLines);
      }
      sizeSprites();
      invalidate();
    },
    select(arrowIndex, vertex) {
      selArrow = arrowIndex;
      for (const g of lineGroups) fillLineGroup(g);
      writeHeads();
      const p = vertex === null ? null : vertexPos(vertex);
      if (p) selMarker.position.set(p[0], p[1], p[2]);
      selMarker.visible = !!p;
      invalidate();
    },
    focus(point) {
      const delta = new Vector3(point[0], point[1], point[2]).sub(controls.target);
      controls.target.add(delta);
      camera.position.add(delta);
      controls.update();
      invalidate();
    },
    fit(bbox) {
      // 인자 없음 = 기존 동작(등각 +X+Y+Z·up +Z·모델 중심), bbox = 지금 시선 그대로 그 bbox 를 꽉 차게(화면비 반영)
      if (bbox === undefined) fit();
      else fitBox(validBbox(bbox) ? bbox : modelBbox);
    },
    setView(axis, sign = 1, bbox) {
      const b = validBbox(bbox) ? bbox : modelBbox;
      const v = viewBasis(axis, sign);
      applyFit(fitView(b, v.eye, v.up, aspect, proj));
    },
    setProjection(p) {
      if (p === proj) return;
      const t = controls.target;
      if (p === "ortho") {
        // 위치·방향 그대로, 보이는 높이 = 2·d·tan(FOV/2)
        ortho.position.copy(persp.position);
        ortho.quaternion.copy(persp.quaternion);
        ortho.up.copy(persp.up);
        orthoHalfH = orthoHalfHeightFromPersp(v3(persp.position), v3(t));
        ortho.zoom = 1;
        camera = ortho;
        applyOrtho();
      } else {
        // 타깃·방향 그대로, 보이는 높이가 같도록 타깃 거리만 조정(줌 1 이었으면 위치도 그대로)
        const np = perspPositionFromOrtho(v3(ortho.position), v3(t), orthoHalfH, ortho.zoom);
        persp.position.set(np[0], np[1], np[2]);
        persp.quaternion.copy(ortho.quaternion);
        persp.up.copy(ortho.up);
        persp.updateProjectionMatrix();
        camera = persp;
      }
      proj = p;
      activate();
      sizeSprites();
      invalidate();
    },
    projection: () => proj,
    onPick(cb) {
      pickCb = cb;
    },
    setMarkers(points) {
      if (marks) {
        scene.remove(marks);
        marks.geometry.dispose();
        marks = null;
      }
      if (points && points.length >= 3) {
        const g = new BufferGeometry();
        g.setAttribute("position", new BufferAttribute(new Float32Array(points), 3));
        marks = new Points(g, markMat);
        marks.renderOrder = 10;
        scene.add(marks);
      }
      invalidate();
    },
    setColorMap(map) {
      lut = map === "diverging" ? LUT_DIV_LINEAR : LUT_LINEAR;
      if (layers.full) paintLayer(layers.full);
      if (layers.lod) paintLayer(layers.lod);
      invalidate();
    },
    setElements(tri2elem, nElems) {
      disposeElemLayer();
      const g = layers.full?.geo;
      if (!g) return;
      const nT = tri2elem.length;
      const pos = new Float32Array(nT * 9);
      const idc = new Uint8Array(nT * 9);
      for (let t = 0; t < nT; t++) {
        const rgb = idToRgb(tri2elem[t]);
        for (let j = 0; j < 3; j++) {
          const v = g.indices[t * 3 + j] * 3;
          const o = (t * 3 + j) * 3;
          pos[o] = g.positions[v];
          pos[o + 1] = g.positions[v + 1];
          pos[o + 2] = g.positions[v + 2];
          idc[o] = rgb[0];
          idc[o + 1] = rgb[1];
          idc[o + 2] = rgb[2];
        }
      }
      const geometry = new BufferGeometry();
      geometry.setAttribute("position", new BufferAttribute(pos, 3));
      const color = new BufferAttribute(new Float32Array(nT * 9).fill(0.6), 3);
      geometry.setAttribute("color", color);
      geometry.setAttribute("idc", new BufferAttribute(idc, 3, true));
      geometry.computeVertexNormals();
      geometry.computeBoundingSphere();
      const mesh = new Mesh(geometry, elemMat);
      mesh.frustumCulled = false;
      const idMesh = new Mesh(geometry, idMat);
      idMesh.frustumCulled = false;
      scene.add(mesh);
      idScene.add(idMesh);
      elemLayer = { mesh, idMesh, geometry, color, tri2elem, nElems };
      if (layers.full) layers.full.mesh.visible = false;
      if (layers.lod) layers.lod.mesh.visible = false;
      idKey = "";
      invalidate();
    },
    setElemColors(rgba) {
      if (!elemLayer) return;
      const out = elemLayer.color.array as Float32Array;
      const t2e = elemLayer.tri2elem;
      const lin = new Float32Array(256);
      for (let i = 0; i < 256; i++) lin[i] = srgbToLinear(i);
      for (let t = 0; t < t2e.length; t++) {
        const e = t2e[t] * 4;
        const r = lin[rgba[e]];
        const gg = lin[rgba[e + 1]];
        const b = lin[rgba[e + 2]];
        for (let j = 0; j < 3; j++) {
          const o = (t * 3 + j) * 3;
          out[o] = r;
          out[o + 1] = gg;
          out[o + 2] = b;
        }
      }
      elemLayer.color.needsUpdate = true;
      invalidate();
    },
    pickElem(clientX, clientY) {
      if (!elemLayer) return null;
      const r = canvas.getBoundingClientRect();
      const p = new Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
      raycaster.setFromCamera(p, camera);
      if (camera === ortho && ortho.near < 0) raycaster.ray.origin.addScaledVector(raycaster.ray.direction, ortho.near);
      const hit = raycaster.intersectObject(elemLayer.mesh, false)[0];
      if (!hit || hit.faceIndex == null) return null;
      return { elem: elemLayer.tri2elem[hit.faceIndex], point: [hit.point.x, hit.point.y, hit.point.z] };
    },
    idBuffer(rect: Rect): IdPatch {
      const cw = Math.max(1, canvas.clientWidth);
      const ch = Math.max(1, canvas.clientHeight);
      const x0 = Math.max(0, Math.floor(rect.x));
      const y0 = Math.max(0, Math.floor(rect.y));
      const x1 = Math.min(cw, Math.ceil(rect.x + rect.w));
      const y1 = Math.min(ch, Math.ceil(rect.y + rect.h));
      const w = Math.max(0, x1 - x0);
      const h = Math.max(0, y1 - y0);
      const out: IdPatch = { rect: { x: x0, y: y0, w, h }, ids: new Uint32Array(w * h) };
      if (!elemLayer || !w || !h) return out;
      const W = renderer.domElement.width;
      const H = renderer.domElement.height;
      if (!idTarget || idTarget.width !== W || idTarget.height !== H) {
        idTarget?.dispose();
        idTarget = new WebGLRenderTarget(W, H);
        idKey = "";
      }
      if (proj === "ortho") applyOrtho();
      camera.updateMatrixWorld();
      const key = `${W}x${H}|${camera.matrixWorld.elements.join(",")}|${camera.projectionMatrix.elements.join(",")}`;
      if (key !== idKey) {
        const prevBg = idScene.background;
        renderer.setRenderTarget(idTarget);
        renderer.setClearColor(0x000000, 1);
        renderer.clear();
        renderer.render(idScene, camera);
        renderer.setRenderTarget(null);
        idScene.background = prevBg;
        idKey = key;
      }
      const sx = W / cw;
      const sy = H / ch;
      const dx0 = Math.floor(x0 * sx);
      const dx1 = Math.min(W, Math.ceil(x1 * sx));
      const dy0 = Math.floor(y0 * sy);
      const dy1 = Math.min(H, Math.ceil(y1 * sy));
      const dw = Math.max(1, dx1 - dx0);
      const dh = Math.max(1, dy1 - dy0);
      const buf = new Uint8Array(dw * dh * 4);
      // GL 행 0 = 아래
      renderer.readRenderTargetPixels(idTarget, dx0, H - dy1, dw, dh, buf);
      for (let j = 0; j < h; j++)
        for (let i = 0; i < w; i++) {
          const px = Math.min(dw - 1, Math.floor((x0 + i + 0.5) * sx) - dx0);
          const pyTop = Math.min(dh - 1, Math.floor((y0 + j + 0.5) * sy) - dy0);
          const k = ((dh - 1 - pyTop) * dw + px) * 4;
          out.ids[j * w + i] = buf[k] | (buf[k + 1] << 8) | (buf[k + 2] << 16);
        }
      return out;
    },
    projectCentroids(c) {
      if (proj === "ortho") applyOrtho();
      camera.updateMatrixWorld();
      viewProj.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
      const cw = Math.max(1, canvas.clientWidth);
      const ch = Math.max(1, canvas.clientHeight);
      const n = c.length / 3;
      const out = new Float32Array(n * 2);
      for (let e = 0; e < n; e++) {
        tmpV4.set(c[e * 3], c[e * 3 + 1], c[e * 3 + 2], 1).applyMatrix4(viewProj);
        const w = tmpV4.w;
        const nz = tmpV4.z / w;
        if (!(w > 0) || nz < -1 || nz > 1) {
          out[e * 2] = NaN;
          out[e * 2 + 1] = NaN;
          continue;
        }
        out[e * 2] = ((tmpV4.x / w + 1) / 2) * cw;
        out[e * 2 + 1] = ((1 - tmpV4.y / w) / 2) * ch;
      }
      return out;
    },
    setOverlayLines(segs) {
      if (overlay) {
        scene.remove(overlay);
        overlay.geometry.dispose();
        overlay = null;
      }
      if (segs && segs.length) {
        const g = new LineSegmentsGeometry();
        g.setPositions(segs);
        overlay = new LineSegments2(g, overlayMat);
        overlay.frustumCulled = false;
        overlay.renderOrder = 4;
        scene.add(overlay);
      }
      invalidate();
    },
    stats: () => ({ renders }),
    dispose() {
      disposed = true;
      if (raf) cancelAnimationFrame(raf);
      if (ctlRaf) cancelAnimationFrame(ctlRaf);
      if (lodTimer) clearTimeout(lodTimer);
      ro?.disconnect();
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointerup", onUp);
      controls.dispose();
      clearArrows();
      clearSupports();
      disposeLayer(layers.full);
      disposeLayer(layers.lod);
      disposeElemLayer();
      overlay?.geometry.dispose();
      marks?.geometry.dispose();
      markMat.dispose();
      idTarget?.dispose();
      for (const g of [headGeo, sphereGeo]) g.dispose();
      for (const m of [surfMat, arrowMat, supMat, selMarker.material as MeshBasicMaterial, elemMat, idMat, overlayMat]) m.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };
  resize();
  fit();
  return api;
};
