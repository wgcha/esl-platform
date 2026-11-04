"""v0.16.0 ④ 메시 옵션 시험용 합성 복잡 STEP(계약 esl_compare_mesh_options.md V-C2-1, gmsh OCC 로 시험 중 생성).

``complex_plate_step``: 400×300 판(z = 0, 쉘) + 폭 0.3 mm 띠 면 여러 개·가는 쐐기 면 여러 개(판을 fragment 로 나눈 면 —
CAD 면 단위 메싱이 가장 싫어하는 좁은 면) + 구 캡 비드(구면 딤플, 테두리 날카로움) + Ø2 관통 구멍(작은 구멍 메움 대상).
gmsh 가 쓴 STEP 이라 설정 mesh.occ_sew_faces 1 로 읽는다. ``synth_compare.py``(v0.15.1 mesh-sphere 소유)는 건드리지 않는다.
"""
from __future__ import annotations

import os

COMPLEX = {"plate": (400.0, 300.0),
           "strips": [(60.0, 20.0, 0.3, 120.0), (120.0, 40.0, 0.3, 200.0), (300.0, 30.0, 0.3, 150.0)],   # (x, y, 폭, 길이)
           "wedges": [((250.0, 200.0), (330.0, 204.0), (330.0, 200.5)), ((40.0, 250.0), (140.0, 251.0), (40.0, 252.0))],
           "cap": (200.0, 150.0, 30.0, 8.0),             # (x, y, 구 R, 깊이) — 테두리 경사 ≈ 43° > 특징각 30°
           "hole": (330.0, 80.0, 1.0)}                    # (x, y, r) — Ø2


def complex_plate_step(path, spec: dict | None = None) -> str:
    import gmsh
    sp = dict(COMPLEX)
    sp.update(spec or {})
    Lx, Ly = sp["plate"]
    x, y, R, d = sp["cap"]
    T = d + 4.0
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        slab = occ.addBox(0.0, 0.0, -T, Lx, Ly, T)
        tools = [(3, occ.addSphere(x, y, R - d, R))]
        hx, hy, hr = sp["hole"]
        tools.append((3, occ.addCylinder(hx, hy, -T - 1.0, 0.0, 0.0, T + 2.0, hr)))
        (v,), _ = occ.cut([(3, slab)], tools)
        occ.synchronize()
        faces = [t for _d, t in occ.getEntities(2)]
        occ.remove([v])
        drop = []
        for s in faces:
            b = occ.getBoundingBox(2, s)
            if abs(b[5] + T) < 1e-6 or abs(b[3]) < 1e-6 or abs(b[0] - Lx) < 1e-6 or abs(b[4]) < 1e-6 \
                    or abs(b[1] - Ly) < 1e-6 or gmsh.model.getType(2, s) == "Cylinder":    # 밑면·옆면·구멍 벽
                drop.append((2, s))
        occ.remove(drop, recursive=True)
        occ.synchronize()
        top = [(2, t) for _d, t in occ.getEntities(2) if gmsh.model.getType(2, t) == "Plane"]
        cuts = [(2, occ.addRectangle(sx, sy, 0.0, w, L)) for sx, sy, w, L in sp["strips"]]
        for a, b, c in sp["wedges"]:
            pts = [occ.addPoint(px, py, 0.0) for px, py in (a, b, c)]
            ls = [occ.addLine(pts[i], pts[(i + 1) % 3]) for i in range(3)]
            cuts.append((2, occ.addPlaneSurface([occ.addCurveLoop(ls)])))
        occ.fragment(top, cuts)
        occ.synchronize()
        occ.fragment(list(occ.getEntities(2)), [])
        occ.synchronize()
        os.makedirs(os.path.dirname(os.path.abspath(str(path))), exist_ok=True)
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return str(path)
