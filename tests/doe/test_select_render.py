"""V-BS-10(렌더)·V-BS-8(썸네일 결정성) + select 코어 단계 흐름(bd_input → bd_loads → bd_matrix → bd_select_grid → bd_eval →
bd_post, 계약 esl_bead_select.md §7.2·§8 — 워커 작업 시험 V-BS-14 는 S3).

썸네일 크기·결정적 바이트, 색 부호(깊어짐 = 파랑 채널 우세), 모든 칸 같은 V(manifest)·같은 시점(공칭 bbox), 공칭 칸 회색,
셀 상태(SELECT_* → SKIPPED_FIXED/FAILED_MESH), 산출물 rad 사본 = /NODE 좌표 칸 외 바이트 동일, 입력 폴더 불변."""
import os

import numpy as np
import pytest

import synth_bead as sb
import synth_doe as sd
from esl import view3d as v3
from esl.doe import bead_select as bs
from esl.doe import paicad_io as pio
from esl.doe import scenario as sc
from esl.doe import select_render as sr
from esl.doe import settings
from esl.doe import stages as stg
from esl.library import _util as U
from esl.opt.png import decode_png_size

CFG = settings({"bead_doe": {"enabled": True}})
TC = CFG["select"]["thumb"]


@pytest.fixture(scope="module")
def G():
    g = sb.generate()
    D = bs.derive_obj(g["mesh"], bs.normalize_input(sb.selection(g), CFG), CFG, fixed_node_ids=g["fixed_ids"])
    B = bs.basis(g["mesh"], D, CFG)
    return g, D, B


def _thumb(g, D, B, values, v_max=5.0):
    X0 = g["mesh"]["x0"]
    direction, has = bs.node_direction(B)
    view = sr.view(X0, has, np.mean([b.n_hat for b in D.beads], axis=0), None, TC)
    x = bs.morph(X0, B, values)
    tris = v3.triangulate(g["mesh"]["conn"], g["mesh"]["elem_type"])
    cv = sr.color_values(X0, x, direction, has)
    return sr.render(x, tris, cv, has, view, v_max, TC, loops=[lp["nodes"] for b in D.beads for lp in b.loops]), view


def test_thumb_size_determinism_sign(G):
    g, D, B = G
    a, va = _thumb(g, D, B, {"B1_D1": 27.0})
    b, vb = _thumb(g, D, B, {"B1_D1": 27.0})
    assert a == b and decode_png_size(a) == (TC["w"], TC["h"])
    _, vc = _thumb(g, D, B, {"B1_D1": 17.0, "B1_W": 50.0})
    for k in ("f", "r", "u", "center"):                                   # 같은 시점·축척(공칭 bbox)
        assert np.array_equal(va[k], vc[k])
    assert va["scale"] == vc["scale"]
    deep = sr.png_rgb(a).astype(int)
    shallow = sr.png_rgb(_thumb(g, D, B, {"B1_D1": 17.0})[0]).astype(int)
    blue = (deep[..., 2] - deep[..., 0] > 40).sum()
    red = (shallow[..., 0] - shallow[..., 2] > 40).sum()
    assert blue > 200 and red > 200                                        # 깊어짐 = 파랑, 얕아짐 = 빨강
    assert (deep[..., 0] - deep[..., 2] > 40).sum() < blue / 20
    # 공칭(색 None) = 회색 음영
    X0 = g["mesh"]["x0"]
    tris = v3.triangulate(g["mesh"]["conn"], g["mesh"]["elem_type"])
    nom = sr.png_rgb(sr.render(X0, tris, None, None, va, 5.0, TC))
    assert np.all(nom[..., 0] == nom[..., 1]) and np.all(nom[..., 1] == nom[..., 2])
    assert (nom < 250).any()
    t = sr.diverging(np.array([1.0, 0.0, -1.0]))
    assert t[0, 2] > t[0, 0] and t[2, 0] > t[2, 2] and np.allclose(t[1], sr.WHITE)


def test_raster_depth_nearest_wins():
    P = np.array([[0, 0], [10, 0], [0, 10], [0, 0], [10, 0], [0, 10]], float)
    z = np.array([5, 5, 5, 1, 1, 1], float)
    tris = np.array([[0, 1, 2], [3, 4, 5]])
    buf, _ = sr.raster_depth(P, z, tris, 12, 12)
    assert set(np.unique(buf[buf >= 0]).tolist()) == {1}                   # 가까운 삼각형
    z2 = np.ones(6)
    buf2, _ = sr.raster_depth(P, z2, tris, 12, 12)
    assert set(np.unique(buf2[buf2 >= 0]).tolist()) == {0}                 # 동률 = 작은 번호


# ---------------------------------------------------------------- select 코어 단계 흐름
def _case(tmp_path, g):
    cd = tmp_path / "case" / "input"
    cd.mkdir(parents=True)
    m = g["mesh"]
    rad = sd.write_mesh_rad(str(cd / "model.rad"), m)
    (cd / "other.inc").write_text("/BEGIN\n# 대상 노드 없음\n")
    return str(cd), rad


def test_select_stage_flow(tmp_path, G):
    g, _, _ = G
    m = g["mesh"]
    cd, rad = _case(tmp_path, g)
    lib = tmp_path / "lib"
    dirs = [sd.save_entry(str(lib), f"E{k}", m, kind, 1.0 + k, seed=k)[0] for k, kind in enumerate(("bend", "twist"))]
    stamp_case, stamp_lib = sc.tree_stamp(cd), sc.tree_stamp(str(lib))
    sel_in = sb.selection(g)
    norm = bs.normalize_input(sel_in, CFG)
    sha = bs.selection_sha256(norm)
    full = {"bead_doe": {"enabled": True}, "opt_run": {"solver": {"backend": "superlu"}}}
    doe = {"id": "S9", "scenario": "select", "title": "t", "cfg": full,
           "entries": [{"id": f"E{k}", "dir": d} for k, d in enumerate(dirs)],
           "base": {"entry_id": "E0", "rad_path": rad, "part_title": sd.PART_TITLE, "case_dir": cd},
           "selection": {"rev": 1, "sha256": sha, "input": sel_in}}
    out = tmp_path / "_doe" / "S9"

    def run(stage, **kw):
        return stg.run_stage({"stage": stage, "out": str(out), "doe": {**doe, **kw}}, lambda s: None)

    r = run("bd_input")
    assert r["part_id"] == sd.PART_ID and U.read_json(str(out / "prep" / "input.json"))["step"] is None
    r = run("bd_loads")
    assert "FIXED_INFO_MISSING" in r["warnings"]                          # paicad fixed-scan 없음 → 경고(준비 성공)
    man = U.read_json(str(out / "prep" / "select" / "select_manifest.json"))
    assert man["schema"] == "esl/bead_select_view/1" and man["n_elems"] == m["conn"].shape[0]
    blob = (out / "prep" / "select" / "select.bin").read_bytes()
    lay = {x["name"]: x for x in man["bin"]["layout"]}
    t2e = np.frombuffer(blob, "<u4", count=lay["tri2elem"]["count"], offset=lay["tri2elem"]["offset"])
    assert t2e.size == man["n_tris"] and t2e[-1] == m["conn"].shape[0] - 1
    v3.read_glb(str(out / "prep" / "select" / "part.glb"))
    # 고정 노드: fixed-scan 사본 흉내(prep/fixed) → 다음 단계부터 사용
    pos = {int(v): i for i, v in enumerate(m["node_id"].tolist())}
    sd.write_fixed(str(out / "prep" / "fixed"), m, [[pos[int(v)] for v in gr] for gr in g["fixed_groups"]])
    tab = None
    spec = {"method": "lhs", "n": 4, "seed": 3, "params": [{"name": "B1_D1", "lo": 18.0, "hi": 26.0},
                                                          {"name": "B1_W", "lo": 52.0, "hi": 66.0}]}
    r = run("bd_matrix", rev=1, spec=spec)
    assert r["selection_sha256"] == sha and len(r["basis_sha256"]) == 64
    tab = stg.params_table(stg.Ctx({"stage": "x", "out": str(out), "doe": {**doe, "rev": 1}}))
    assert [p["name"] for p in tab] == ["B1_D1", "B1_D2", "B1_W", "B2_D1", "B2_W"]
    sdir = out / "select" / sha[:12]
    b1 = (sdir / "basis.npz").read_bytes()
    r2 = run("bd_matrix", rev=2, spec=spec)                                # 같은 sha → 재사용(바이트 동일)
    assert r2["basis_sha256"] == r["basis_sha256"] and (sdir / "basis.npz").read_bytes() == b1
    # 선택 sha 불일치 → PREVIEW_STALE
    from esl.errors import EslError
    with pytest.raises(EslError) as ei:
        run("bd_matrix", rev=3, spec=spec, selection={"rev": 1, "sha256": "0" * 64, "input": sel_in})
    assert ei.value.code == "PREVIEW_STALE"
    # 미리보기 격자
    r = run("bd_select_grid", rev=1)
    gd = out / "doe" / "1" / "grid"
    gm = U.read_json(str(gd / pio.GRID_MANIFEST))
    assert gm["kind"] == "select" and gm["nominal"]["thumb"] == "cells/nominal/thumb.png" and gm["rules"] == 2
    assert gm["color"]["unit"] == "mm" and gm["color"]["v_max"] > 0
    assert (gd / "cells" / "nominal" / "thumb.png").is_file()
    nomp = sr.png_rgb((gd / "cells" / "nominal" / "thumb.png").read_bytes())
    assert np.all(nomp[..., 0] == nomp[..., 1])
    mtx = U.read_json(str(out / "doe" / "1" / "matrix.json"))
    ids = [d["id"] for d in mtx["designs"] if d["id"] != "d000"]
    assert sorted(c["id"] for c in gm["cells"]) == ids
    for cell in gm["cells"]:
        assert decode_png_size((gd / cell["thumb"]).read_bytes()) == (TC["w"], TC["h"])
        # v0.16.1 SR-D-3: 고정 침범이 있는 모든 칸(상태 무관)에 fixed_viol{n, max_mm, bead_vars, node_idx}
        assert ("fixed_viol" in cell) == (cell["fixed_max_mm"] > CFG["select"]["fixed_tol_mm"]), cell
        assert cell["code"] != "SELECT_FIXED_VIOLATION"                      # warn 정책(기본) — 스킵 없음
        if cell["status"] == "OK" and "fixed_viol" in cell:
            assert any(w["code"] == "SELECT_FIXED_MOVED" for w in cell["warnings"])
        if "fixed_viol" in cell:
            assert cell["fixed_viol"]["n"] > 0 and cell["fixed_viol"]["bead_vars"], cell["fixed_viol"]
    g1 = pio.read_grid(str(gd), ids)
    st = {x["id"]: x["state"] for x in g1["cells"]}
    first = (gd / gm["cells"][0]["thumb"]).read_bytes()
    run("bd_select_grid", rev=1)                                          # 결정적(같은 바이트)
    assert (gd / gm["cells"][0]["thumb"]).read_bytes() == first
    # 셀 상태 매핑
    assert pio.cell_state({"id": "x", "status": "FAIL", "code": "SELECT_FIXED_VIOLATION"})["state"] == "SKIPPED_FIXED"
    assert pio.cell_state({"id": "x", "status": "FAIL", "code": "SELECT_QUALITY_FAIL"})["state"] == "FAILED_MESH"
    assert pio.cell_state({"id": "x", "status": "FAIL", "code": "SELECT_MORPH_INVERTED"})["state"] == "FAILED_MESH"
    assert pio.cell_state({"id": "x", "status": "FAIL", "code": "GEOM_FEATURE_COLLISION"})["state"] != "FAILED_MESH"
    # 실행: 베이스라인 + 안
    assert run("bd_eval", rev=1, design="d000")["status"] == "OK"
    for did in ids:
        res = run("bd_eval", rev=1, design=did)
        want = "OK" if st[did] == "READY" else st[did]
        assert res["status"] == want, (did, res, st[did])
    ok_ids = [i for i in ids if st[i] == "READY"]
    assert ok_ids, st
    assert run("bd_eval", rev=1, design=ok_ids[0])["reused"]
    z = U.load_npz(str(out / "run" / "designs" / ok_ids[0] / "design.npz"))
    L = bs.load_basis(str(sdir / "basis.npz"))
    vals = next(d["values"] for d in mtx["designs"] if d["id"] == ok_ids[0])
    assert np.array_equal(z["x"], bs.morph(m["x0"], L, vals))
    res = U.read_json(str(out / "run" / "designs" / ok_ids[0] / "result.json"))
    assert res["mesh"]["quality"]["n_affected"] > 0
    r = run("bd_post", rev=1)
    best = r["result"]["best"]
    assert best is not None
    bd = out / "best" / best["id"]
    assert {"values.json", "selection.json", "include/model.rad", "ch_r.rad", "ch_r.fem"} <= set(best["files"])
    assert "include/other.inc" not in best["files"]
    # rad 사본 = 원본에서 /NODE 좌표 칸만 다름(ID·줄 수·다른 줄 바이트 동일)
    a = (out / ".." / ".." / "case" / "input" / "model.rad").resolve().read_bytes().splitlines(keepends=True)
    b = (bd / "include" / "model.rad").read_bytes().splitlines(keepends=True)
    assert len(a) == len(b)
    zb = U.load_npz(str(out / "run" / "designs" / best["id"] / "design.npz"))
    moved = set(m["node_id"][np.any(zb["x"] != m["x0"], axis=1)].tolist())
    in_node, n_diff = False, 0
    for la, lb in zip(a, b):
        if la[:1] == b"/":
            in_node = la[1:5].upper() == b"NODE"
        if la != lb:
            assert in_node and la[:10] == lb[:10] and la[70:] == lb[70:] and int(la[:10]) in moved
            n_diff += 1
    assert n_diff == len(moved) > 0
    from esl.doe import nodes as nd
    got = nd.read_nodes(str(bd / "include" / "model.rad"))
    pos = {int(v): i for i, v in enumerate(m["node_id"].tolist())}
    for k in list(moved)[:50]:
        assert np.allclose(got[k], zb["x"][pos[k]], rtol=0, atol=1e-9)
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "비드 선택·모핑 규칙" in html and "Wendland" in html and "STEP" in html
    assert sc.tree_stamp(cd) == stamp_case and sc.tree_stamp(str(lib)) == stamp_lib
    assert os.path.isfile(str(out / "post" / "result.json"))


def test_fixed_violation_detail_v0151():
    """고정 침범 원인: 침범 노드·변수별 이동(큰 순)·노드 번호 상한, 공칭·영향 없는 변수 제외."""
    from esl.doe import bead_select as bsel

    x0 = np.zeros((6, 3))
    vars_ = [
        {"name": "B1_W", "type": "W", "bead": "b1", "nominal": 50.0, "idx": np.array([0, 1, 2], dtype=np.int32),
         "vec": np.array([[0.5, 0, 0], [0.1, 0, 0], [0.01, 0, 0]])},
        {"name": "B1_D1", "type": "D", "bead": "b1", "nominal": 20.0, "idx": np.array([1, 4], dtype=np.int32),
         "vec": np.array([[0, 0, 1.0], [0, 0, 1.0]])},
        {"name": "B2_D1", "type": "D", "bead": "b2", "nominal": 6.0, "idx": np.array([5], dtype=np.int32),
         "vec": np.array([[0, 0, 1.0]])},
    ]
    B = bsel.Basis(vars_, 6, "s")
    vals = {"B1_W": 52.0, "B1_D1": 20.5, "B2_D1": 6.0}
    x = bsel.morph(x0, B, vals)
    fixed = np.array([True, True, True, False, False, True])
    r = bsel.fixed_violation_detail(x0, x, fixed, B, vals, tol=0.05)
    assert r["n"] == 2 and r["node_idx"] == [0, 1]
    assert [v["name"] for v in r["bead_vars"]] == ["B1_W", "B1_D1"]
    assert r["bead_vars"][0] == {"name": "B1_W", "bead": "b1", "n": 2, "max_mm": 1.0}
    assert r["bead_vars"][1]["n"] == 1 and r["bead_vars"][1]["max_mm"] == 0.5
    assert bsel.fixed_violation_detail(x0, x, fixed, B, vals, tol=0.05, cap=1)["node_idx"] == [0]
    none = bsel.fixed_violation_detail(x0, x0, fixed, B, vals, tol=0.05)
    assert none == {"n": 0, "max_mm": 0.0, "bead_vars": [], "node_idx": []}


def test_select_warn_flow_v0161(tmp_path, G):
    """v0.16.1(SR-D-1·3·11·12·13d): 블렌딩이 고정 노드에 닿는 선택 — warn 정책이면 침범 안도 READY(셀 warnings·fixed_viol),
    실행·순위에 포함(행 warn), summary.best_clean, 경고 안 받기 rad 사본 첫 /NODE 앞 ASCII 주석·values.json warnings.
    v0.16.0 SKIPPED_FIXED done.json(같은 sha) → 재사용하지 않고 해석."""
    g, _, _ = G
    m = g["mesh"]
    cd, rad = _case(tmp_path, g)
    lib = tmp_path / "lib"
    dirs = [sd.save_entry(str(lib), f"E{k}", m, kind, 1.0 + k, seed=k)[0] for k, kind in enumerate(("bend",))]
    sel_in = sb.selection(g)
    sel_in["beads"][0]["blend_mm"] = 24.0
    sha = bs.selection_sha256(bs.normalize_input(sel_in, CFG))
    doe = {"id": "S8", "scenario": "select", "title": "t", "cfg": {"bead_doe": {"enabled": True},
                                                                   "opt_run": {"solver": {"backend": "superlu"}}},
           "entries": [{"id": "E0", "dir": dirs[0]}],
           "base": {"entry_id": "E0", "rad_path": rad, "part_title": sd.PART_TITLE, "case_dir": cd},
           "selection": {"rev": 1, "sha256": sha, "input": sel_in}}
    out = tmp_path / "_doe" / "S8"

    def run(stage, **kw):
        return stg.run_stage({"stage": stage, "out": str(out), "doe": {**doe, **kw}}, lambda s: None)

    run("bd_input")
    run("bd_loads")
    pos = {int(v): i for i, v in enumerate(m["node_id"].tolist())}
    sd.write_fixed(str(out / "prep" / "fixed"), m, [[pos[int(v)] for v in gr] for gr in g["fixed_groups"]])
    W = next(b for b in bs.derive_obj(m, bs.normalize_input(sel_in, CFG), CFG).beads if b.id == "b1").W_nom
    spec = {"method": "lhs", "n": 3, "seed": 2, "params": [{"name": "B1_W", "lo": W + 4.0, "hi": W + 8.0}]}
    run("bd_matrix", rev=1, spec=spec)
    bj = U.read_json(str(out / "select" / sha[:12] / "basis.json"))
    assert bj["algo"] == bs.ALGO
    run("bd_select_grid", rev=1)
    gm = U.read_json(str(out / "doe" / "1" / "grid" / pio.GRID_MANIFEST))
    assert gm["rules"] == 2
    warned = [c["id"] for c in gm["cells"] if c["status"] == "OK" and c.get("warnings")]
    assert warned and all("fixed_viol" in c for c in gm["cells"] if c["id"] in warned)
    st = {x["id"]: x for x in pio.read_grid(str(out / "doe" / "1" / "grid"), [c["id"] for c in gm["cells"]])["cells"]}
    assert all(st[i]["state"] == "READY" and st[i].get("warnings") for i in warned), [st[i] for i in warned]
    run("bd_eval", rev=1, design="d000")
    # v0.16.0 이 남긴 SKIPPED_FIXED done.json(같은 sha) → 지금 READY 라 재사용하지 않음
    c0 = stg.Ctx({"stage": "x", "out": str(out), "doe": {**doe, "rev": 1}})
    dd = stg.design_dir(c0, warned[0])
    os.makedirs(dd, exist_ok=True)
    from esl.doe import evaluate as ev
    ev.write_done(dd, stg.design_sha(c0, warned[0]), "SKIPPED_FIXED")
    U.write_json(os.path.join(dd, ev.RESULT_JSON), ev.result_doc(warned[0], "SKIPPED_FIXED", {}))
    for c in gm["cells"]:
        r = run("bd_eval", rev=1, design=c["id"])
        assert r["status"] == "OK" and not r["reused"], r
    res = U.read_json(os.path.join(dd, ev.RESULT_JSON))
    assert res["select_warnings"][0]["code"] == "SELECT_FIXED_MOVED" and res["select_fixed_viol"]["bead_vars"]
    assert any(w.startswith("SELECT_FIXED_MOVED") for w in res["warnings"])
    post = run("bd_post", rev=1)["result"]
    rows = {x["id"]: x for x in post["ranking"]}
    assert all("FIXED_MOVED" in (rows[i].get("warn") or []) for i in warned), [(i, rows.get(i)) for i in warned]
    clean = [x["id"] for x in post["ranking"] if not x.get("warn")]
    assert post["summary"]["best_clean"] == (clean[0] if clean else None)
    best = post["best"]["id"]
    bd = out / "best" / best
    if best in warned:
        b = (bd / "include" / "model.rad").read_bytes()
        k = b.index(b"/NODE")
        head = b[:k].splitlines()
        assert head[-1].startswith(b"#ESL WARNING FIXED_NODES") or head[-1].startswith(b"#ESL WARNING FIXED_MOVED")
        assert all(len(x) <= 100 for x in head if x.startswith(b"#ESL"))              # SR-D-43 주석 줄 ≤ 100자
        assert b"#ESL WARNING FIXED_MOVED" in (bd / "ch_r.rad").read_bytes()
        assert U.read_json(str(bd / "values.json"))["warnings"][0]["code"] == "SELECT_FIXED_MOVED"
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "체결 위치 어긋남" in html and "⚠" in html


def test_thumb_orientation_convex_concave_v0161():
    """SR-D-34: 볼록·오목(n̂ 부호 반대) 비드 썸네일 시점이 같다 — 화면 오른쪽 = η × n_p(+x), 위 ≈ +η(+y), 카메라는 판 법선 쪽 위.
    같은 판에서 비드 깊이만 거울(z → −z)로 만든 두 메시의 공칭 썸네일: 시점 벡터 동일, 비드(가장 어두운 음영 아닌 전경) 무게중심이
    같은 쪽(화면 좌표 차 ≤ 5 px), 비드 중심(x 큰 쪽 b2)이 화면 오른쪽. view_normal 은 볼록·오목이 섞여도 상쇄되지 않음."""
    g = sb.generate()
    m = g["mesh"]
    m2 = dict(m)
    x2 = np.array(m["x0"], dtype=np.float64)
    x2[:, 2] *= -1.0
    m2["x0"] = x2
    out = []
    for mesh in (m, m2):
        D = bs.derive_obj(mesh, bs.normalize_input(sb.selection(g), CFG), CFG, fixed_node_ids=g["fixed_ids"])
        B = bs.basis(mesh, D, CFG)
        _d, has = bs.node_direction(B)
        vw = sr.view(mesh["x0"], has, sr.view_normal(mesh["x0"], [b.n_hat for b in D.beads]), None, TC)
        tris = v3.triangulate(mesh["conn"], mesh["elem_type"])
        img = sr.png_rgb(sr.render(mesh["x0"], tris, None, None, vw, 5.0, TC)).astype(int)
        ys, xs = np.nonzero(img.sum(axis=2) < 3 * 250)
        out.append((sorted({b.sense for b in D.beads}), vw, (xs.mean(), ys.mean()), D))
    (s1, v1, c1, D1), (s2, v2, c2, _D2) = out
    assert s1 != s2                                                        # 한쪽 볼록, 다른 쪽 오목
    for k in ("f", "r", "u"):
        assert np.allclose(v1[k], v2[k], atol=1e-9), k
    assert v1["r"][0] > 0.99 and v1["u"][1] > 0.5 and v1["f"][2] < 0       # 오른쪽 +x, 위 +y, 위에서 내려다봄
    assert abs(c1[0] - c2[0]) <= 5 and abs(c1[1] - c2[1]) <= 5
    n = D1.beads[0].n_hat
    assert np.linalg.norm(sr.view_normal(m["x0"], [n, -n])) == pytest.approx(1.0)


def test_sel_warn_lines_max_100():
    """SR-D-43: 받기 rad #ESL WARNING 줄 ≤ 100자(긴 노드 ID·큰 n 에서 나눠 씀), 짧은 ID 는 줄당 10개(v0.16.1 첫 판 그대로)."""
    from esl.doe import stages as stg
    short = stg.sel_warn_lines({"n": 12, "max_mm": 1.25}, list(range(1, 13)))
    assert short[0] == "#ESL WARNING FIXED_MOVED n=12 max_mm=1.25 : fastener positions moved, check RBE2/TIE"
    assert short[1] == "#ESL WARNING FIXED_NODES " + " ".join(str(v) for v in range(1, 11)) and short[2].endswith("11 12")
    big = stg.sel_warn_lines({"n": 10 ** 15, "max_mm": 123456.7891}, [9_000_000_000 + k for k in range(50)])
    assert all(len(x) <= 100 for x in big) and big[1].startswith("#ESL WARNING FIXED_MOVED :")
    got = [int(v) for x in big if x.startswith("#ESL WARNING FIXED_NODES") for v in x.split()[3:]]
    assert got == [9_000_000_000 + k for k in range(50)]
