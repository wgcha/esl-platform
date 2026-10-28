"""비드 최적화(v0.7.0, 계약 esl_opt_run.md) 백엔드 시험 도우미.

- 합성 판(XZ 평면, 법선 Y) 메시·변위(굽힘 P2(s) / 뒤틀림 s·t)로 실제 라이브러리 항목 폴더(entry.json·raw.npz·summary.npz)와
  DB 행을 만든다 — 지연 백필(topo_sha256·deform_mode)이 실제 코어 함수로 계산된다. entry.json 에는 topo·mode 를 넣지 않는다.
- 설정: opt_run.enabled + 가짜 OptiStruct·hw 실행 파일(빈 파일, 실행하지 않음) + 업로드 루트.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from esl_platform.core.db.tables import cases, library_entries
from esl_test_support import API, H, make_settings_dict
from p2_support import seed_run
from sqlalchemy import insert

W = H("tok-power", True)
R = H("tok-power")
OCT = {"Content-Type": "application/octet-stream"}


# ---------------------------------------------------------------- 설정
def opt_settings_dict(base: Path, *, solver: bool = True, **over: Any) -> dict[str, Any]:
    d = make_settings_dict(base)
    tools = base / "tools"
    tools.mkdir(exist_ok=True)
    os_exe = tools / "optistruct.bat"
    hw = tools / "hw.exe"
    if solver:
        os_exe.write_text("rem fake\n")
        hw.write_text("")
    up = base / "uploads"
    up.mkdir(exist_ok=True)
    d["storage"]["upload_root"] = str(up)
    d["altair"] = {**d["altair"], "optistruct_path": str(os_exe), "hw_exe_path": str(hw)}
    d["opt_run"] = {"enabled": True}
    d["upload"] = {**d.get("upload", {}), "max_concurrent_per_user": 20}
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            d[k] = {**d[k], **v}
        else:
            d[k] = v
    return d


# ---------------------------------------------------------------- 합성 메시·항목
def plate(nx: int = 12, ny: int = 8, Lx: float = 300.0, Lz: float = 200.0, node_base: int = 1, elem_base: int = 1,
          pid: int = 10, t: float = 1.5) -> dict[str, np.ndarray]:
    xs = np.linspace(0.0, Lx, nx + 1)
    zs = np.linspace(0.0, Lz, ny + 1)
    X = np.array([[x, 0.0, z] for x in xs for z in zs])
    conn = np.array([[i * (ny + 1) + j, (i + 1) * (ny + 1) + j, (i + 1) * (ny + 1) + j + 1, i * (ny + 1) + j + 1]
                     for i in range(nx) for j in range(ny)], dtype=np.int64)
    ne = conn.shape[0]
    return {"node_id": node_base + np.arange(X.shape[0], dtype=np.int64), "x0": X,
            "elem_id": elem_base + np.arange(ne, dtype=np.int64), "elem_type": np.full(ne, 4, dtype=np.int8),
            "conn": conn, "elem_pid": np.full(ne, pid, dtype=np.int64), "elem_mid": np.full(ne, 1, dtype=np.int64),
            "thickness": np.full(ne, t), "E": np.full(ne, 2.1e5), "nu": np.full(ne, 0.3)}


def disp(mesh: dict, kind: str, amp: float = 1.0) -> np.ndarray:
    from esl.library import normalize as nz

    fr = nz.frame(mesh["x0"], None, mesh["conn"], mesh["elem_type"])
    loc = nz.local_coords(fr, mesh["x0"])
    s, t = 2 * loc[:, 0] - 1, 2 * loc[:, 1] - 1
    if kind == "bend":
        w = 0.5 * (3 * s ** 2 - 1)
    elif kind == "twist":
        w = s * t
    elif kind == "zero":
        w = 0 * s
    else:
        raise ValueError(kind)
    return amp * w[:, None] * np.asarray(fr["n"])[None, :]


def write_entry_files(esl_root: Path, eid: str, mesh: dict, kind: str = "bend", *, inch: int | None = 55,
                      raw: bool = True) -> dict[str, Any]:
    from esl.library import normalize as nz

    d = esl_root / "_library" / "entries" / eid
    d.mkdir(parents=True, exist_ok=True)
    fr = nz.frame(mesh["x0"], None, mesh["conn"], mesh["elem_type"])
    u = disp(mesh, kind)
    f = u * 10.0
    nid = mesh["node_id"]
    sup = [{"node_id": int(nid[0]), "dof": "123"}, {"node_id": int(nid[-1]), "dof": "13"},
           {"node_id": int(nid[len(nid) // 2]), "dof": "1"}]
    meta = {"schema": "esl/library_entry/1", "entry_id": eid, "frame": fr, "grid": {"nx": 24, "ny": 14},
            "model": {"product": "55QX10A", "inch": inch, "n_nodes": int(nid.size), "n_elems": int(mesh["elem_id"].size)},
            "esl": {"supports": sup}}
    (d / "entry.json").write_text(json.dumps(meta), encoding="utf-8")
    np.savez_compressed(d / "summary.npz", total_F=np.zeros(3))
    if raw:
        ne = mesh["elem_id"].size
        np.savez_compressed(d / "raw.npz", **{k: np.asarray(v) for k, v in mesh.items()}, f=f, u_rel=u,
                            is_bc=np.zeros(nid.size, bool), support_node_id=np.array([s["node_id"] for s in sup]),
                            support_dof=np.array([s["dof"] for s in sup]))
        assert ne > 0
    return {"frame": fr, "supports": sup}


def make_case(engine, inputs_root: Path, cid: str = "c1", project_id: str = "p-1", rad: bool = True) -> dict[str, Any]:
    rad_path = inputs_root / f"{cid}_0000.rad"
    if rad:
        rad_path.write_text("#RADIOSS STARTER\n/END\n")
    with engine.begin() as c:
        c.execute(insert(cases).values(id=cid, project_id=project_id, folder_name=f"f_{cid}", title=f"Case {cid}",
                                       rad_path=str(rad_path), results_dir=str(inputs_root),
                                       input_fingerprint={"includes": []}, part_title="Chassis rear",
                                       created_by="u-power", created_by_name="파워"))
    return {"id": cid, "rad_path": str(rad_path)}


def seed_opt_entry(engine, esl_root: Path, case_id: str, mesh: dict | None = None, kind: str = "bend", *,
                   project_id: str = "p-1", inch: int | None = 55, L: tuple[float, float] | None = None,
                   raw: bool = True, scene_no: int = 1, status: str = "ACTIVE") -> str:
    mesh = mesh if mesh is not None else plate()
    run = seed_run(engine, case_id, project_id=project_id)
    eid = str(uuid.uuid4())
    info = write_entry_files(esl_root, eid, mesh, kind, inch=inch, raw=raw)
    fr = info["frame"]
    Lxi, Leta = L if L is not None else (fr["L_xi"], fr["L_eta"])
    dir_rel = f"_library/entries/{eid}"
    import datetime as _dt

    with engine.begin() as c:
        c.execute(insert(library_entries).values(
            id=eid, project_id=project_id, case_id=case_id, esl_run_id=run["run_id"], status=status,
            model={"name": "55QX10A", "inch": inch, "n_nodes": int(mesh["node_id"].size),
                   "n_elems": int(mesh["elem_id"].size)},
            scene={"drop_type": "Corner", "scene_no": scene_no, "warnings": []},
            quality={"verdict": "PASS", "fail_reasons": []},
            summary={"grid": {"nx": 24, "ny": 14}, "frame": {"L_xi": Lxi, "L_eta": Leta}},
            dir_rel=dir_rel, summary_rel=f"{dir_rel}/summary.npz", sha256="0" * 64, registered_by="u-power",
            registered_by_name="파워",
            retired_at=None if status == "ACTIVE" else _dt.datetime(2026, 10, 19, tzinfo=_dt.timezone.utc)))
    return eid


# ---------------------------------------------------------------- 템플릿 업로드
def fem_bytes(tmp: Path, mesh: dict | None = None) -> bytes:
    from esl.opt.femread import write_fem

    p = tmp / f"tpl_{uuid.uuid4().hex[:6]}.fem"
    write_fem(p, mesh if mesh is not None else plate())
    return p.read_bytes()


def upload_files(client, files: dict[str, bytes], token: str = "tok-power", project_id: str = "p-1",
                 complete_files: bool = True) -> str:
    hw = H(token, True)
    body = {"project_id": project_id, "name": "template",
            "files": [{"rel": rel, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for rel, b in files.items()]}
    r = client.post(f"{API}/uploads", json=body, headers=hw)
    assert r.status_code == 201, r.text
    uid = r.json()["upload_id"]
    if complete_files:
        for i, b in enumerate(files.values()):
            r = client.put(f"{API}/uploads/{uid}/files/{i}", params={"offset": 0}, content=b, headers={**hw, **OCT})
            assert r.status_code == 200, r.text
    return uid


def register_template(client, tmp: Path, *, token: str = "tok-power", title: str = "평판 v1", inch: int | None = None,
                      mesh: dict | None = None) -> dict[str, Any]:
    data = fem_bytes(tmp, mesh)
    uid = upload_files(client, {"rad/plate.fem": data}, token=token)
    hw = H(token, True)
    r = client.post(f"{API}/opt/templates/check", json={"project_id": "p-1", "upload_id": uid}, headers=hw)
    assert r.status_code == 200 and r.json()["ok"], r.text
    body = {"project_id": "p-1", "upload_id": uid, "sha256": r.json()["sha256"], "title": title}
    if inch is not None:
        body["inch"] = inch
    r = client.post(f"{API}/opt/templates", json=body, headers=hw)
    assert r.status_code == 201, r.text
    return r.json()


def run_body(entry_ids: list[str], scenario: str = "S1", **kw: Any) -> dict[str, Any]:
    return {"project_id": "p-1", "scenario": scenario, "entry_ids": entry_ids, **kw}


def tree(d: Path) -> dict[str, tuple[int, float]]:
    out = {}
    for root, _dirs, names in os.walk(d):
        for n in names:
            p = Path(root) / n
            st = p.stat()
            out[str(p.relative_to(d))] = (st.st_size, st.st_mtime)
    return out
