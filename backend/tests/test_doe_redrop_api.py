"""재낙하 입력 묶음 API(계약 esl_redrop_bundle.md, v0.22.0 REDROP) — V-RD-8~11·13~15·18~20.

합성 스터디(① same·DONE) + Case 2개(픽스처 tests/fixtures/redrop 사본) + 엔트리 2개 + 안 폴더(run/designs/<did>/design.npz,
prep/base_mesh.npz)를 DB·폴더에 직접 심는다(계산 없음)."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import unquote

import numpy as np
import pytest
from doe_support import api, doe_settings_dict
from esl_test_support import API, H, REPO
from sqlalchemy import insert, text
from test_doe_api import _app

FIX = REPO / "tests" / "fixtures" / "redrop"
RELS = {"m_0000.rad", "inc/a.inc", "sub/b.inc", "m_0001.rad"}
NID = np.arange(1, 13, dtype=np.int64)
X0 = np.array([[float((i - 1) % 4) * 10, float((i - 1) // 4) * 10, 1.5] for i in range(1, 13)])
X1 = X0.copy()
X1[1] += [0.5, 0.25, -0.125]
X1[6] += [1.0, 0.0, 2.0]
X1[10] += [0.0, 3.0, 0.5]


@pytest.fixture()
def settings_dict(tmp_path):
    return doe_settings_dict(tmp_path)


def _sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _tree(*roots: Path) -> dict[str, tuple]:
    out = {}
    for r in roots:
        for root, _d, names in os.walk(r):
            for n in names:
                p = Path(root) / n
                out[str(p)] = (p.stat().st_mtime_ns, _sha(p))
    return out


def _case(engine, inputs_root: Path, name: str, *, cumulative=False, engine_rad=True, abs_include=False,
          status="ACTIVE", project_id="p-1") -> dict:
    from esl_platform.core.db.tables import cases

    d = inputs_root / name
    shutil.copytree(FIX, d)
    if not engine_rad:
        (d / "m_0001.rad").unlink()
    if abs_include:
        p = d / "m_0000.rad"
        p.write_bytes(p.read_bytes().replace(b"#include inc/a.inc", b"#include /abs/inc/a.inc"))
    for junk in ("m_0000_0001.h3d", "m_0000A001", "m_0000_0000.out", "m_0000.sta"):    # 결과 파일 — zip 에 들어가면 안 됨
        (d / junk).write_bytes(b"result")
    cid = str(uuid.uuid4())
    with engine.begin() as c:
        c.execute(insert(cases).values(
            id=cid, project_id=project_id, folder_name=f"rd_{name}", title=f"Case {name}", rad_path=str(d / "m_0000.rad"),
            results_dir=str(d), input_fingerprint={"includes": []}, part_title="Chassis rear", status=status,
            extract_summary={"requested_part_title": "Chassis rear", **({"cumulative": {"n": 1}} if cumulative else {})},
            created_by="u-power", created_by_name="파워"))
    return {"id": cid, "dir": d}


def _entry(engine, case_id: str, scene_no: int = 1, name: str = "55QX10A", project_id: str = "p-1") -> str:
    from p2_support import seed_entry, seed_run

    return seed_entry(engine, case_id, seed_run(engine, case_id)["run_id"], scene_no=scene_no, name=name,
                      project_id=project_id)


def _design(base: Path, did: str, x, *, status="OK", npz=True, values=None, shuffle=True) -> None:
    d = base / "run" / "designs" / did
    d.mkdir(parents=True, exist_ok=True)
    (d / "result.json").write_text(json.dumps({"id": did, "status": status, "values": values or {"CHR_BEAD_D_1": 4.5}}),
                                   encoding="utf-8")
    if npz:
        nid, xx = (NID[::-1].copy(), x[::-1].copy()) if shuffle else (NID, x)
        np.savez(d / "design.npz", node_id=nid, x=xx)


def _study(engine, esl_root: Path, entries: list[str], *, scenario="same", inputs=None, base_entry="first",
           project_id="p-1") -> tuple[str, Path]:
    from esl_platform.core.repositories import doe as doe_repo

    sid = str(uuid.uuid4())
    base = esl_root / "_doe" / sid
    (base / "prep").mkdir(parents=True)
    np.savez(base / "prep" / "base_mesh.npz", node_id=NID, x0=X0)
    (base / "post").mkdir()
    rows = [{"id": "d001", "rank": 1, "score": 0.8, "values": {}}, {"id": "d020", "rank": 7, "score": 0.5, "values": {}}]
    (base / "post" / "result.json").write_text(json.dumps({"ranking": rows, "best": {"id": "d001", "files": []}}),
                                               encoding="utf-8")
    (base / "best" / "d001" / "include").mkdir(parents=True)
    _design(base, "d000", X0)
    _design(base, "d001", X1)
    _design(base, "d020", X1 + 0.25)
    _design(base, "d003", X1, status="FAILED_MESH", npz=False)
    with engine.begin() as c:
        doe_repo.insert_study(c, id=sid, project_id=project_id, scenario=scenario, title="스터디", entry_ids=entries,
                              base={"entry_id": entries[0], "case_id": "x"} if base_entry == "first" else None,
                              inputs=inputs or {}, phase="DONE", dir_rel=f"_doe/{sid}", created_by="u-power",
                              created_by_name="파워", result={"ranking": rows})
    return sid, base


@pytest.fixture()
def world(engine, esl_root, inputs_root):
    c1 = _case(engine, inputs_root, "c1")
    c2 = _case(engine, inputs_root, "c2")
    e1 = _entry(engine, c1["id"], 1)
    e2 = _entry(engine, c2["id"], 2)
    sid, base = _study(engine, esl_root, [e1, e2])
    return {"c1": c1, "c2": c2, "e1": e1, "e2": e2, "sid": sid, "base": base}


def _get(client, sid, did="d001", entry=None, token="tok-power"):
    q = f"?entry_id={entry}" if entry else ""
    return api(client, "GET", f"/doe/studies/{sid}/designs/{did}/redrop{q}", token=token)


def _zip(r) -> zipfile.ZipFile:
    assert r.status_code == 200, r.text
    return zipfile.ZipFile(io.BytesIO(r.content))


def _redrop_left(esl_root: Path) -> list[str]:
    d = esl_root / "_redrop"
    return sorted(os.listdir(d)) if d.is_dir() else []


def _code(r) -> str:
    return r.json()["detail"]["code"]


# ================================================================ V-RD-9·10·18 정상
def test_rd9_10_18_zip_structure_and_rank_outside_best(client, world, esl_root):
    sid, did = world["sid"], "d020"                 # 순위 7 — best/d020 없음(순위 밖)
    assert not (world["base"] / "best" / did).exists()
    r = _get(client, sid, did)                      # entry_id 생략 → 기준 엔트리
    z = _zip(r)
    slug = "55QX10A_Corner_1"
    top = f"redrop_{did}_{slug}_{sid[:8]}"
    names = z.namelist()
    assert {n.split("/")[0] for n in names} == {top}
    assert set(names) == {f"{top}/REDROP_README.txt", f"{top}/redrop_manifest.json", *(f"{top}/input/{x}" for x in RELS)}
    assert not any(re.search(r"\.h3d|A001|\.out|\.sta", n) for n in names)           # 결과 파일 제외
    cd = r.headers["content-disposition"]
    assert f'filename="{top}.zip"' in cd and f"filename*=UTF-8''{top}.zip" in cd
    assert r.headers["x-bundle-files"] == str(len(names))
    m = json.loads(z.read(f"{top}/redrop_manifest.json"))
    assert list(m) and set(m) == {"schema", "platform_version", "created_at", "study", "design", "entry", "case", "files",
                                  "changed", "nodes", "checks"}
    assert m["schema"] == "esl/redrop/1" and m["study"]["plan"] == "case_once" and m["study"]["select_base"] is None
    assert m["design"] == {"id": did, "rank": 7, "status": "OK", "values": {"CHR_BEAD_D_1": 4.5}}
    assert m["entry"] == {"id": world["e1"], "label": "55QX10A Corner 1", "is_base": True}
    assert m["case"]["id"] == world["c1"]["id"] and m["case"]["rad_file_name"] == "m_0000.rad"
    assert "/" not in m["case"]["rad_file_name"] and str(world["c1"]["dir"]) not in json.dumps(m)
    x = X1 + 0.25
    disp = np.linalg.norm(x - X0, axis=1)
    assert m["nodes"]["n_target"] == 12 and m["nodes"]["n_moved"] == 12
    assert m["nodes"]["max_disp"] == pytest.approx(float(disp.max())) and m["nodes"]["max_disp_node_id"] == int(NID[disp.argmax()])
    assert sorted(m["changed"]) == sorted(["m_0000.rad", "inc/a.inc", "sub/b.inc"])
    assert {f["rel"] for f in m["files"]} == RELS
    for f in m["files"]:                            # sha256 = zip 안 파일
        assert hashlib.sha256(z.read(f"{top}/input/{f['rel']}")).hexdigest() == f["sha256"]
        assert (f["source"] == "orig") == (f["rel"] == "m_0001.rad") and f["size"] == len(z.read(f"{top}/input/{f['rel']}"))
    # 원본 파일(엔진 rad)은 바이트 동일, 패치본은 원본과 다름
    assert z.read(f"{top}/input/m_0001.rad") == (world["c1"]["dir"] / "m_0001.rad").read_bytes()
    assert z.read(f"{top}/input/sub/b.inc") != (world["c1"]["dir"] / "sub" / "b.inc").read_bytes()
    assert "input/" in z.read(f"{top}/REDROP_README.txt").decode("utf-8")
    assert not (world["base"] / "best" / did).exists() and _redrop_left(esl_root) == []


def test_rd2_base_design_zip_identical(client, world):
    z = _zip(_get(client, world["sid"], "d000"))
    top = z.namelist()[0].split("/")[0]
    m = json.loads(z.read(f"{top}/redrop_manifest.json"))
    assert m["changed"] == [] and m["nodes"]["n_moved"] == 0
    for rel in RELS:
        assert z.read(f"{top}/input/{rel}") == (world["c1"]["dir"] / rel).read_bytes()


def test_rd18_entry_selection(client, world):
    sid = world["sid"]
    z = _zip(_get(client, sid, "d001", world["e2"]))
    top = f"redrop_d001_55QX10A_Corner_2_{sid[:8]}"
    m = json.loads(z.read(f"{top}/redrop_manifest.json"))
    assert m["entry"] == {"id": world["e2"], "label": "55QX10A Corner 2", "is_base": False}
    assert m["case"]["id"] == world["c2"]["id"]
    for rel in RELS:                                 # 그 엔트리 Case 의 폐포(엔진 rad 는 원본 그대로)
        assert f"{top}/input/{rel}" in z.namelist()
    assert z.read(f"{top}/input/m_0001.rad") == (world["c2"]["dir"] / "m_0001.rad").read_bytes()


# ================================================================ V-RD-8 모드 거부
@pytest.mark.parametrize("scenario, inputs", [("mesh", {}), ("step", {}), ("compare", {}), ("select", {"select_base": "mesh"}),
                                              ("select", {"select_base": "step"})])
def test_rd8_unsupported_plans(client, engine, esl_root, world, scenario, inputs):
    sid, _b = _study(engine, esl_root, [world["e1"]], scenario=scenario, inputs=inputs, base_entry=None)
    r = _get(client, sid)
    assert r.status_code == 422 and _code(r) == "REDROP_UNSUPPORTED" and r.json()["detail"]["plan"]
    s = api(client, "GET", f"/doe/studies/{sid}").json()
    assert s["redrop_ok"] is False and "원 Case 노드 번호" in s["redrop_blocked"]
    assert [e["ok"] for e in s["redrop_entries"]] == [False]
    assert s["redrop_entries"][0]["blocked"] == s["redrop_blocked"]


def test_rd8_select_case_is_supported(client, engine, esl_root, world):
    sid, _b = _study(engine, esl_root, [world["e1"]], scenario="select", inputs={}, base_entry="first")
    assert api(client, "GET", f"/doe/studies/{sid}").json()["redrop_ok"] is True
    assert _get(client, sid).status_code == 200


def test_rd8_no_scenario_name_branching():
    src = (REPO / "backend" / "esl_platform" / "api" / "services" / "redrop.py").read_text(encoding="utf-8")
    assert not re.search(r"""(==|!=|\bin\b)\s*[(\[]?\s*["'](same|select|mesh|step|compare)["']""", src)
    assert not re.search(r"""["'](same|select|mesh|step|compare)["']\s*(==|!=|\bin\b)""", src)


# ================================================================ V-RD-11 무쓰기
def test_rd11_no_writes_to_inputs(client, world, inputs_root, esl_root, settings_dict):
    up = Path(settings_dict["storage"]["upload_root"])
    watched = (inputs_root, up, world["base"])
    before = _tree(*watched)
    assert before
    assert _get(client, world["sid"]).status_code == 200
    assert _get(client, world["sid"], "d020", world["e2"]).status_code == 200
    assert _tree(*watched) == before
    assert _redrop_left(esl_root) == []


# ================================================================ V-RD-13 정리
def test_rd13_cleanup_error_close_and_ttl(client, world, esl_root, inputs_root, app_ctx, tmp_path):
    from esl_platform.api.routers.doe import _with_cleanup
    from esl_platform.api.services import bundle as bundle_svc
    from esl_platform.api.services import redrop as rd_svc
    from esl_platform.core.auth import Principal

    sid = world["sid"]
    assert _get(client, sid).status_code == 200 and _redrop_left(esl_root) == []           # 정상 완료
    # 노드 누락 → 4xx, 폴더 즉시 정리
    a = world["c1"]["dir"] / "inc" / "a.inc"
    a.write_bytes(b"\n".join(ln for ln in a.read_bytes().split(b"\n") if not ln.startswith(b"         6")))
    r = _get(client, sid)
    assert r.status_code == 422 and _code(r) == "VD_NODES_MISSING" and _redrop_left(esl_root) == []
    # 스트림 도중 제너레이터 close
    pr = Principal(user_id="u-power", username="power", display_name="파워", is_global_admin=False, roles={"p-1": "power"})
    b = rd_svc.bundle(app_ctx, pr, sid, "d001", world["e2"])
    assert len(_redrop_left(esl_root)) == 1
    gen = _with_cleanup(bundle_svc.stream_zip(b["files"], b["prefix"]), b["cleanup"])
    next(gen)
    gen.close()
    assert _redrop_left(esl_root) == []
    # ttl 지난 잔여 폴더 정리 — hex 아닌 이름·링크는 건드리지 않음
    root = esl_root / "_redrop"
    old = time.time() - 7200
    stale, fresh, other = "a" * 32, "b" * 32, "keep_me"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f.txt").write_text("x")
    for n in (stale, fresh, other):
        (root / n).mkdir()
        (root / n / "f.txt").write_text("x")
    os.symlink(outside, root / ("c" * 32))
    for n in (stale, other):
        os.utime(root / n, (old, old))
    os.utime(root / ("c" * 32), (old, old), follow_symlinks=False)
    assert _get(client, sid, "d001", world["e2"]).status_code == 200
    assert _redrop_left(esl_root) == sorted([fresh, other, "c" * 32])
    assert (outside / "f.txt").exists() and (root / ("c" * 32)).is_symlink()


# ================================================================ V-RD-14 거부 코드
def test_rd14_rejections(client, engine, world, esl_root, inputs_root, tmp_path, fake_dashboard, clock, settings_dict):
    sid = world["sid"]
    r = _get(client, sid, "d003")
    assert r.status_code == 409 and _code(r) == "REDROP_DESIGN_NOT_READY"
    assert r.json()["detail"]["design_id"] == "d003" and r.json()["detail"]["status"] == "FAILED_MESH"
    r = _get(client, sid, "d404")
    assert r.status_code == 404 and _code(r) == "REDROP_DESIGN_NOT_FOUND"
    for bad in ("D001", "d-1", "x" * 65):
        r = _get(client, sid, bad)
        assert r.status_code == 422 and _code(r) == "INVALID_PARAMS", bad
    r = _get(client, sid, "d001", "not-a-uuid")
    assert r.status_code == 422 and _code(r) == "INVALID_PARAMS"
    assert _get(client, "00000000-0000-0000-0000-000000000000").status_code == 404
    # 누적 Case · 절대경로 include · 엔진 rad 없음 · 보관 Case
    cum = _case(engine, inputs_root, "cum", cumulative=True)
    absi = _case(engine, inputs_root, "absi", abs_include=True)
    noeng = _case(engine, inputs_root, "noeng", engine_rad=False)
    arch = _case(engine, inputs_root, "arch", status="ARCHIVED")
    ents = {k: _entry(engine, c["id"], 10 + i) for i, (k, c) in enumerate(
        {"cum": cum, "absi": absi, "noeng": noeng, "arch": arch}.items())}
    sid2, _b = _study(engine, esl_root, [world["e1"], *ents.values()])
    r = _get(client, sid2, "d001", ents["cum"])
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "VD_CUMULATIVE_EXCLUDED" and d["problems"][0]["code"] == "VD_CUMULATIVE_EXCLUDED"
    assert str(inputs_root) not in json.dumps(d)
    r = _get(client, sid2, "d001", ents["absi"])
    assert r.status_code == 422 and _code(r) == "VD_INCLUDE_LAYOUT"
    r = _get(client, sid2, "d001", ents["noeng"])
    assert r.status_code == 422 and _code(r) == "VD_ENGINE_MISSING"
    r = _get(client, sid2, "d001", ents["arch"])
    assert r.status_code == 409 and _code(r) == "REDROP_CASE_NOT_READY"
    assert r.json()["detail"]["entry_id"] == ents["arch"]
    # 엔트리 목록 판정(DB 만): 보관·누적 = ok false + 사유, 엔진 없음·절대경로는 요청 때 판정이라 ok true
    es = {e["entry_id"]: e for e in api(client, "GET", f"/doe/studies/{sid2}").json()["redrop_entries"]}
    assert es[ents["arch"]] == {**es[ents["arch"]], "ok": False, "blocked": "원 Case 가 없거나 보관됨"}
    assert es[ents["cum"]]["ok"] is False and es[ents["cum"]]["blocked"] == "누적 Case — 재낙하 입력 불가"
    assert es[ents["noeng"]]["ok"] is True and es[ents["absi"]]["ok"] is True
    assert _redrop_left(esl_root) == []
    # 기준 메시와 다른 노드 집합 → 409
    np.savez(world["base"] / "run" / "designs" / "d001" / "design.npz", node_id=NID[:-1], x=X1[:-1])
    r = _get(client, sid)
    assert r.status_code == 409 and _code(r) == "REDROP_NODESET_MISMATCH"
    assert {"n_base", "n_design", "n_only_base", "n_only_design"} <= set(r.json()["detail"]) and _redrop_left(esl_root) == []
    # 설정: enabled=false → 503, 크기 상한 → 413(임시 폴더 생성 전)
    for key, val, status, code in (("enabled", False, 503, "REDROP_DISABLED"),):
        d = copy.deepcopy(settings_dict)
        d["bead_doe"]["redrop"] = {key: val}
        with _app(tmp_path, engine, fake_dashboard, clock, d) as c2:
            r = api(c2, "GET", f"/doe/studies/{world['sid']}/designs/d000/redrop")
            assert r.status_code == status and _code(r) == code
            s = api(c2, "GET", f"/doe/studies/{world['sid']}").json()
            assert s["redrop_ok"] is False and s["redrop_blocked"] == "재낙하 입력 받기가 꺼져 있습니다"
    d = copy.deepcopy(settings_dict)
    d["ui"] = {**d.get("ui", {}), "max_bundle_bytes": 10}
    with _app(tmp_path, engine, fake_dashboard, clock, d) as c3:
        r = api(c3, "GET", f"/doe/studies/{world['sid']}/designs/d000/redrop")
        dd = r.json()["detail"]
        assert r.status_code == 413 and dd["code"] == "BUNDLE_TOO_LARGE" and dd["limit"] == 10 and dd["size"] > 10
        assert str(inputs_root) not in json.dumps(dd) and _redrop_left(esl_root) == []


def test_rd14_base_changed(client, world, esl_root):
    b = world["c1"]["dir"] / "m_0000.rad"
    raw = b.read_bytes().split(b"\n")
    i = next(k for k, ln in enumerate(raw) if ln.startswith(b"         3"))
    raw[i] = b"%10d%20.6f%20.6f%20.6f" % (3, 99.0, 0.0, 1.5)
    b.write_bytes(b"\n".join(raw))
    r = _get(client, world["sid"])
    assert r.status_code == 409 and _code(r) == "REDROP_BASE_CHANGED"
    assert r.json()["detail"]["n_changed"] == 1 and r.json()["detail"]["max_diff"] == pytest.approx(79.0)
    assert _redrop_left(esl_root) == []


# ================================================================ V-RD-15 권한
def test_rd15_permissions(client, world):
    sid = world["sid"]
    assert _get(client, sid, token="tok-general").status_code == 200        # 프로젝트 viewer(읽기)
    assert _get(client, sid, token="tok-nonmember").status_code == 403
    assert _get(client, "11111111-1111-1111-1111-111111111111", token="tok-nonmember").status_code == 404
    assert client.get(f"{API}/doe/studies/{sid}/designs/d001/redrop").status_code == 401


# ================================================================ V-RD-19 엔트리 거부
def test_rd19_entry_rejections(client, engine, world, esl_root, inputs_root):
    sid = world["sid"]
    other_case = _case(engine, inputs_root, "o1")
    foreign_study_entry = _entry(engine, other_case["id"], 5)                       # 다른 스터디에 속한 실제 엔트리
    foreign_project_entry = _entry(engine, other_case["id"], 6, project_id="p-2")    # 다른 프로젝트의 실제 엔트리
    for eid in (foreign_study_entry, foreign_project_entry, str(uuid.uuid4())):
        r = _get(client, sid, "d001", eid)
        assert r.status_code == 422 and _code(r) == "REDROP_ENTRY_NOT_IN_STUDY" and r.json()["detail"]["entry_id"] == eid
    assert _redrop_left(esl_root) == []
    ghost = str(uuid.uuid4())                                                       # 엔트리 행 없음
    sid2, _b = _study(engine, esl_root, [world["e1"], ghost])
    r = _get(client, sid2, "d001", ghost)
    assert r.status_code == 409 and _code(r) == "REDROP_ENTRY_NOT_READY" and r.json()["detail"]["entry_id"] == ghost
    sid3, _b = _study(engine, esl_root, [foreign_project_entry, world["e1"]])        # 다른 프로젝트 엔트리가 스터디 목록에 있어도
    r = _get(client, sid3, "d001", foreign_project_entry)
    assert r.status_code == 409 and _code(r) == "REDROP_ENTRY_NOT_READY"
    assert _redrop_left(esl_root) == []


def test_rd19_no_base_entry_requires_entry_id(client, engine, world, esl_root):
    sid, _b = _study(engine, esl_root, [world["e1"]], base_entry=None)
    r = _get(client, sid)
    assert r.status_code == 422 and _code(r) == "INVALID_PARAMS"
    assert _get(client, sid, "d001", world["e1"]).status_code == 200


# ================================================================ V-RD-20 엔트리 목록·이름
def test_rd20_entries_list_detail_and_list_null(client, engine, world, esl_root, inputs_root):
    s = api(client, "GET", f"/doe/studies/{world['sid']}").json()
    assert s["redrop_ok"] is True and s["redrop_blocked"] is None
    assert [e["entry_id"] for e in s["redrop_entries"]] == [world["e1"], world["e2"]]
    assert [e["is_base"] for e in s["redrop_entries"]] == [True, False]
    assert [e["label"] for e in s["redrop_entries"]] == ["55QX10A Corner 1", "55QX10A Corner 2"]
    assert s["redrop_entries"][0] == {"entry_id": world["e1"], "label": "55QX10A Corner 1", "case_id": world["c1"]["id"],
                                      "case_title": "Case c1", "is_base": True, "ok": True, "blocked": None}
    lst = [x for x in api(client, "GET", "/doe/studies?project_id=p-1").json() if x["id"] == world["sid"]][0]
    assert lst["redrop_entries"] is None and lst["redrop_ok"] is True and lst["redrop_blocked"] is None
    # 가능한 엔트리 없음 → redrop_ok false
    arch = _case(engine, inputs_root, "arch2", status="ARCHIVED")
    ea = _entry(engine, arch["id"], 3)
    sid, _b = _study(engine, esl_root, [ea])
    s2 = api(client, "GET", f"/doe/studies/{sid}").json()
    assert s2["redrop_ok"] is False and s2["redrop_blocked"] == "재낙하 입력을 만들 수 있는 엔트리가 없습니다"


def test_rd20_slug_rules_and_content_disposition(client, engine, world, esl_root, inputs_root):
    from esl_platform.api.services.redrop import content_disposition, slug

    assert slug('A/B:C*?"<>|  D\tE', "e" * 36, 40) == "A_B_C_D_E"
    assert slug("..__x__..", "abcdef01-2345", 40) == "x"
    assert slug("가" * 100, "abcdef01-2345", 40) == "가" * 40
    assert slug("a" * 10 + "_" + "b" * 10, "abcdef01-2345", 11) == "a" * 10          # 자른 뒤 끝 _ 제거
    assert slug(' / \\ : ', "abcdef01-2345", 40) == "abcdef01"                          # 비면 entry_id 앞 8자
    assert slug(unicodedata_nfd("한글"), "abcdef01", 40) == "한글"                       # NFC
    c = _case(engine, inputs_root, "kr")
    e = _entry(engine, c["id"], 1, name='모델/A:1 "x"')
    sid, _b = _study(engine, esl_root, [e])
    r = _get(client, sid, "d001")
    cd = r.headers["content-disposition"]
    star = re.search(r"filename\*=UTF-8''([^;]+)", cd).group(1)
    assert unquote(star) == f"redrop_d001_모델_A_1_x_Corner_1_{sid[:8]}.zip"
    assert re.search(r'filename="([^"]*)"', cd).group(1).isascii() and "__" in cd
    assert content_disposition("abc.zip") == "attachment; filename=\"abc.zip\"; filename*=UTF-8''abc.zip"
    z = _zip(r)
    assert z.namelist()[0].startswith(f"redrop_d001_모델_A_1_x_Corner_1_{sid[:8]}/")


def unicodedata_nfd(s: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFD", s)
