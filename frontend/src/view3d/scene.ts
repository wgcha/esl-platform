// three 장면(계약 §6·§8). 이 파일만 three 를 import 한다 → 동적 import 로 별도 청크. 시험에서는 mock.
// 좌표 mm·Z-up. onDemand 렌더: 카메라·상태 변경 때만 requestAnimationFrame 1회. 언마운트 시 geometry·material·texture·renderer dispose.
import {
  AmbientLight, BufferAttribute, BufferGeometry, CanvasTexture, Color, ConeGeometry, CylinderGeometry, DirectionalLight, DoubleSide, HemisphereLight, InstancedMesh,
  LineBasicMaterial, LineSegments, Matrix4, Mesh, MeshBasicMaterial, MeshLambertMaterial, PerspectiveCamera, Quaternion, Raycaster, Scene, SphereGeometry, Sprite, SpriteMaterial,
  SRGBColorSpace, Vector2, Vector3, WebGLRenderer,
} from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { ARROW_COLOR, ARROW_SELECTED, type ArrowSpec } from "./arrows";
import { applyDeform } from "./deform";
import { fillVertexColors } from "./colors";
import { pickSegment, type V3 } from "./pick";
import type { CreateScene, GeoData, PickEvent, SceneApi, SceneOptions } from "./sceneApi";
import { SUPPORT_COLOR, SYMBOL_GLYPH, type SupportSpec } from "./supports";

const FOV = 40;
const LOD_RESTORE_MS = 250;
const SELECT_THICK = 1.6;

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
  const camera = new PerspectiveCamera(FOV, 1, opts.diag / 1000, opts.diag * 100);
  camera.up.set(0, 0, 1);
  const center = new Vector3((opts.bbox.min[0] + opts.bbox.max[0]) / 2, (opts.bbox.min[1] + opts.bbox.max[1]) / 2, (opts.bbox.min[2] + opts.bbox.max[2]) / 2);

  scene.add(new HemisphereLight(0xffffff, 0x8a8f99, 1.1));
  scene.add(new AmbientLight(0xffffff, 0.35));
  const headlight = new DirectionalLight(0xffffff, 1.4);
  camera.add(headlight);
  scene.add(camera);

  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = false;
  controls.screenSpacePanning = true;

  let renders = 0;
  let raf = 0;
  let disposed = false;
  const invalidate = () => {
    if (raf || disposed) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      if (disposed) return;
      renders++;
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

  const paintLayer = (l: Layer) => {
    if (!colorArgs) return;
    fillVertexColors(colorArgs.values, colorArgs.min, colorArgs.max, l.color.array as Float32Array, srcOf(l));
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

  // ---- 화살표
  const shaftGeo = new CylinderGeometry(1, 1, 1, 12);
  shaftGeo.translate(0, 0.5, 0);
  const headGeo = new ConeGeometry(1, 1, 16);
  headGeo.translate(0, 0.5, 0);
  const arrowMat = new MeshLambertMaterial({ color: 0xffffff });
  let arrowShaft: InstancedMesh | null = null;
  let arrowHead: InstancedMesh | null = null;
  let arrows: ArrowSpec[] = [];
  let selArrow: number | null = null;
  const arrowLabels: Sprite[] = [];
  const Y = new Vector3(0, 1, 0);
  const tmpM = new Matrix4();
  const tmpQ = new Quaternion();
  const tmpP = new Vector3();
  const tmpS = new Vector3();
  const tmpC = new Color();

  const clearArrows = () => {
    for (const m of [arrowShaft, arrowHead]) {
      if (!m) continue;
      scene.remove(m);
      m.dispose();
    }
    arrowShaft = arrowHead = null;
    for (const s of arrowLabels) {
      scene.remove(s);
      s.material.map?.dispose();
      s.material.dispose();
    }
    arrowLabels.length = 0;
  };
  const writeArrows = () => {
    if (!arrowShaft || !arrowHead) return;
    arrows.forEach((a, i) => {
      const sel = i === selArrow;
      const th = sel ? SELECT_THICK : 1;
      tmpQ.setFromUnitVectors(Y, tmpP.set(a.dir[0], a.dir[1], a.dir[2]));
      tmpP.set(a.tail[0], a.tail[1], a.tail[2]);
      tmpM.compose(tmpP, tmpQ, tmpS.set(a.shaftRadius * th, a.shaftLen, a.shaftRadius * th));
      arrowShaft!.setMatrixAt(i, tmpM);
      tmpP.set(a.tail[0] + a.dir[0] * a.shaftLen, a.tail[1] + a.dir[1] * a.shaftLen, a.tail[2] + a.dir[2] * a.shaftLen);
      tmpM.compose(tmpP, tmpQ, tmpS.set(a.headRadius * th, a.headLen, a.headRadius * th));
      arrowHead!.setMatrixAt(i, tmpM);
      tmpC.set(sel ? ARROW_SELECTED : a.color || ARROW_COLOR);
      arrowShaft!.setColorAt(i, tmpC);
      arrowHead!.setColorAt(i, tmpC);
    });
    for (const m of [arrowShaft, arrowHead]) {
      m.instanceMatrix.needsUpdate = true;
      if (m.instanceColor) m.instanceColor.needsUpdate = true;
    }
  };

  // ---- 선택 표식·군집 꼬리 구
  const sphereGeo = new SphereGeometry(1, 16, 12);
  const selMarker = new Mesh(sphereGeo, new MeshBasicMaterial({ color: ARROW_SELECTED, depthTest: false }));
  selMarker.visible = false;
  selMarker.renderOrder = 9;
  selMarker.scale.setScalar(opts.diag * 0.011);
  scene.add(selMarker);
  const tailMat = new MeshBasicMaterial({ color: 0xa50f15 });
  let tails: InstancedMesh | null = null;

  // ---- 3-2-1 지지 기호
  const supMat = new LineBasicMaterial({ color: SUPPORT_COLOR, depthTest: false, transparent: true });
  let supLines: LineSegments | null = null;
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
    const t = 2 * Math.tan((FOV * Math.PI) / 360);
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
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
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
    controls.update();
    invalidate();
  };

  controls.addEventListener("change", invalidate);
  controls.addEventListener("start", () => {
    if (lodTimer) clearTimeout(lodTimer);
    showLod(true);
    invalidate();
  });
  controls.addEventListener("end", scheduleFull);

  // ---- 선택(클릭)
  let pickCb: ((e: PickEvent) => void) | null = null;
  const raycaster = new Raycaster();
  let down: { x: number; y: number; t: number } | null = null;
  const ndc = (ev: MouseEvent) => {
    const r = canvas.getBoundingClientRect();
    return new Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  };
  const doPick = (ev: MouseEvent): PickEvent => {
    const p = ndc(ev);
    raycaster.setFromCamera(p, camera);
    const o: V3 = [raycaster.ray.origin.x, raycaster.ray.origin.y, raycaster.ray.origin.z];
    const d: V3 = [raycaster.ray.direction.x, raycaster.ray.direction.y, raycaster.ray.direction.z];
    const pxWorld = (t: number) => (2 * t * Math.tan((FOV * Math.PI) / 360)) / Math.max(1, canvas.clientHeight); // 거리 t 에서 1 px 의 월드 길이
    // 1) 지지 기호 2) 화살표 3) 표면 — 화살표는 선분 + 머리 포함, 허용 6 px
    const supIdx = supports.findIndex((s) => {
      const v = new Vector3(s.position[0], s.position[1], s.position[2]).sub(raycaster.ray.origin);
      const t = v.dot(raycaster.ray.direction);
      if (t <= 0) return false;
      const off = v.addScaledVector(raycaster.ray.direction, -t).length();
      return off <= pxWorld(t) * 14;
    });
    const segs = arrows.map((a) => ({ a: a.tail, b: [a.tail[0] + a.dir[0] * a.length, a.tail[1] + a.dir[1] * a.length, a.tail[2] + a.dir[2] * a.length] as V3 }));
    const ai = pickSegment(o, d, segs, (t) => Math.max(pxWorld(t) * 6, 0));
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
      if (tails) {
        scene.remove(tails);
        tails.dispose();
        tails = null;
      }
      if (list.length) {
        arrowShaft = new InstancedMesh(shaftGeo, arrowMat, list.length);
        arrowHead = new InstancedMesh(headGeo, arrowMat, list.length);
        arrowShaft.frustumCulled = arrowHead.frustumCulled = false;
        scene.add(arrowShaft, arrowHead);
        writeArrows();
        const cl = list.filter((a) => a.kind === "cluster");
        if (cl.length) {
          tails = new InstancedMesh(sphereGeo, tailMat, cl.length);
          tails.frustumCulled = false;
          cl.forEach((a, i) => {
            tmpM.compose(tmpP.set(a.tail[0], a.tail[1], a.tail[2]), tmpQ.identity(), tmpS.setScalar(opts.diag * 0.009));
            tails!.setMatrixAt(i, tmpM);
          });
          tails.instanceMatrix.needsUpdate = true;
          scene.add(tails);
        }
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
        const g = new BufferGeometry();
        g.setAttribute("position", new BufferAttribute(new Float32Array(pts), 3));
        supLines = new LineSegments(g, supMat);
        supLines.frustumCulled = false;
        supLines.renderOrder = 8;
        scene.add(supLines);
      }
      sizeSprites();
      invalidate();
    },
    select(arrowIndex, vertex) {
      selArrow = arrowIndex;
      writeArrows();
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
    fit,
    onPick(cb) {
      pickCb = cb;
    },
    stats: () => ({ renders }),
    dispose() {
      disposed = true;
      if (raf) cancelAnimationFrame(raf);
      if (lodTimer) clearTimeout(lodTimer);
      ro?.disconnect();
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointerup", onUp);
      controls.dispose();
      clearArrows();
      clearSupports();
      if (tails) tails.dispose();
      disposeLayer(layers.full);
      disposeLayer(layers.lod);
      for (const g of [shaftGeo, headGeo, sphereGeo]) g.dispose();
      for (const m of [surfMat, arrowMat, tailMat, supMat, selMarker.material as MeshBasicMaterial]) m.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };
  resize();
  fit();
  return api;
};
