"""가짜 paicad 0.14.0 CLI(워커 시험용, 계약 esl_bead_doe.md §6 — V-BD-3·11·14·15).

실제 paicad 의 인자·출력 규약을 흉내 낸다(physicsai release/v0.2.14 ``packages/paicad`` 소스 기준, 읽기만):
- ``version --json`` → {paicad, ocp, numpy, scipy, python}.
- ``shell fixed-scan --assem-dir --parts --out-dir [--options] [--threads]`` → shell_scan.json·fixed_nodes.npz
  (조립 폴더 아래 rad/inc 를 esl.rad 로 읽어 대상 파트 꼭짓점 근처 노드를 RBE2 클러스터로).
- ``shell extract --cad --out-dir [--assem-dir --body-map --options --no-png --threads]`` → shell_features.json
  (D1 fixture ``tests/doe/synth_doe.features_doc`` 형식, 판 범위 = 제어 파일 plate), beads/*.png.
- ``shell tag`` → shell_tag.json, ``shell update`` → sample.brep·shell_update.json·face_map.json,
  ``shell run`` → update/·morph/shell_morph.json·check/{shell_check.json, shell_run.json}·out_files/<rel>
  (원본 rad/inc 에서 **/NODE 좌표 필드만** 바꾼 사본, 노드가 바뀐 파일만 — synth_doe.morph_x, 고정 노드 불변),
  ``shell view grid`` → grid_manifest.json(nominal = {bbox, view_sha256} — 공칭 썸네일 없음)·cells/<id>/thumb.png.
- stdout ``PAICAD PROGRESS n msg``·마지막 ``PAICAD RESULT status code report``, 출력 폴더에 paicad.log,
  보고 파일이 이미 있으면 GEOM_OUTPUT_EXISTS(종료 20).

제어 파일(실행 파일 옆 ``fake_paicad_control.json``, 없으면 기본):
  version·ocp, plate{lo, hi}, n_beads, rules[{when:{name:[lo, hi]}, code}] (값이 모두 범위 안이면 그 코드로 실패 —
  GEOM_FEATURE_COLLISION·GEOM_CAD_FAILED(10), SHELL_FIXED_REGION_VIOLATION(10, 고정 폴더 있을 때만),
  GEOM_QUALITY·GEOM_MORPH_FAILED(11, shell run morph 에서만)), fail{명령: {exit, code, report}} (강제 실패),
  sleep{명령: 초}, view_error[셀 id], fixed_none, brep("gmsh" = 실제 판 BREP — ③), no_result[명령].
호출 기록: 같은 폴더 ``fake_paicad_calls.jsonl`` {cmd, argv, cwd, env, t0, t1, pid}.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for _p in (REPO, os.path.join(HERE, "doe"), os.path.join(HERE, "opt")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402

SELF = os.environ.get("FAKE_PAICAD_SELF") or os.path.abspath(sys.argv[0])
DIR = os.path.dirname(SELF)
VERSION = "0.14.0"
EXIT = {"OK": 0, "ARGS": 2, "INPUT": 3, "UPDATE": 10, "MORPH": 11, "GEOM": 12, "EMPTY": 13, "VIEW": 14, "INTERNAL": 20}
CODE_EXIT = {"GEOM_FEATURE_COLLISION": 10, "SHELL_FIXED_REGION_VIOLATION": 10, "GEOM_CAD_FAILED": 10,
             "GEOM_TOPOLOGY_CHANGED": 10, "GEOM_QUALITY": 11, "GEOM_MORPH_FAILED": 11, "GEOM_DEVIATION": 11}
MORPH_CODES = ("GEOM_QUALITY", "GEOM_MORPH_FAILED", "GEOM_DEVIATION")
COMP = "CHASSIS_REAR"


def ctl() -> dict:
    p = os.path.join(DIR, "fake_paicad_control.json")
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


CTL = ctl()


def record(cmd: str, t0: float) -> None:
    env = sorted(k for k in os.environ if k != "FAKE_PAICAD_SELF")
    row = {"cmd": cmd, "argv": sys.argv[1:], "cwd": os.getcwd(), "env": env, "t0": t0, "t1": time.time(),
           "pid": os.getpid()}
    with open(os.path.join(DIR, "fake_paicad_calls.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


class Rep:
    def __init__(self, out_dir: str | None):
        self.log_fh = None
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            self.log_fh = open(os.path.join(out_dir, "paicad.log"), "a", encoding="utf-8")

    def line(self, s: str) -> None:
        print(s, flush=True)
        if self.log_fh:
            self.log_fh.write(s + "\n")
            self.log_fh.flush()

    def progress(self, pct: int, msg: str) -> None:
        self.line(f"PAICAD PROGRESS {int(pct)} {msg}")

    def result(self, status: str, code: str | None, report: str | None) -> None:
        self.line(f"PAICAD RESULT {status} {code or '-'} {report or '-'}")


class Fail(Exception):
    def __init__(self, code: str, exit_code: int, message: str = "") -> None:
        super().__init__(code)
        self.code, self.exit_code, self.message = code, exit_code, message or code


def dump(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=1)


def env(**body) -> dict:
    out = {"schema_version": 1, "kind": "shell", "engine": "native", "engine_version": CTL.get("version", VERSION)}
    out.update(body)
    return out


def png(w: int = 4, h: int = 3, rgb=(30, 120, 200)) -> bytes:
    def chunk(t: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def no_overwrite(d: str, names) -> None:
    hit = [n for n in names if os.path.exists(os.path.join(d, n))]
    if hit:
        raise Fail("GEOM_OUTPUT_EXISTS", 20, f"output already exists: {', '.join(hit)}")


def forced(cmd: str) -> None:
    f = (CTL.get("fail") or {}).get(cmd)
    if f:
        raise Fail(f.get("code") or "GEOM_INTERNAL", int(f.get("exit", 20)), f.get("message") or "forced")


def maybe_sleep(cmd: str, rep: Rep, values: dict | None = None) -> None:
    s = float((CTL.get("sleep") or {}).get(cmd) or 0)
    when = CTL.get("sleep_when")             # {name: [lo, hi]} — 이 값 범위의 안만 잠듦
    if s and when and values is not None and not all(
            lo - 1e-9 <= float(values.get(n, float("nan"))) <= hi + 1e-9 for n, (lo, hi) in when.items()):
        s = 0.0
    end = time.time() + s
    k = 0
    while time.time() < end:
        time.sleep(min(0.1, max(0.0, end - time.time())))
        k += 1
        if k % 5 == 0:
            rep.progress(min(90, 10 + k), f"{cmd} working")


# ---------------------------------------------------------------- 메시
def plate_box():
    p = CTL.get("plate") or {"lo": [0.0, 0.0, 0.0], "hi": [300.0, 0.0, 200.0]}
    return np.array([p["lo"], p["hi"]], dtype=float)


def rad_files(assem: str) -> list[str]:
    out = []
    for root, _d, files in os.walk(assem, followlinks=False):
        for n in sorted(files):
            if os.path.splitext(n)[1].lower() in (".rad", ".inc"):
                out.append(os.path.join(root, n))
    return sorted(out)


def main_rad(assem: str) -> str:
    rads = [p for p in rad_files(assem) if p.lower().endswith(".rad")]
    if not rads:
        raise Fail("GEOM_INPUT_INVALID", 3, "no .rad in assembly")
    star = [p for p in rads if p.lower().endswith("_0000.rad")]
    return (star or rads)[0]


def part_mesh(assem: str, pid: int) -> dict:
    from esl.rad.parser import list_parts, parse_rad
    rad = main_rad(assem)
    parts = list_parts(rad)
    hit = [p for p in parts if int(p["id"]) == int(pid)]
    if not hit:
        raise Fail("SHELL_PART_NOT_FOUND", 3, f"part {pid} not found")
    m = parse_rad(rad, hit[0]["title"])
    return {"node_id": np.asarray(m.node_id), "x0": np.asarray(m.x0), "part_id": int(pid), "rad": rad}


def pid_of_body_map(path: str | None) -> int | None:
    if not path:
        return None
    with open(path, encoding="utf-8") as fh:
        m = json.load(fh)["map"]
    return int(str(next(iter(m.values()))).split(":")[1])


def load_values(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    return {k: float(v) for k, v in (d.get("values") or {}).items()}


def load_features(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def full_values(feats: dict, vals: dict) -> dict:
    out = {f["name"]: float(f["nominal"]) for f in feats.get("features") or []}
    unknown = [k for k in vals if k not in out]
    if unknown:
        raise Fail("GEOM_INPUT_INVALID", 3, f"unknown parameter: {unknown[0]}")
    out.update(vals)
    return out


def rule_code(values: dict, *, fixed: bool, stage: str) -> str | None:
    """stage = update|morph. 첫 일치 규칙의 코드."""
    for r in CTL.get("rules") or []:
        ok = all(lo - 1e-9 <= float(values.get(n, float("nan"))) <= hi + 1e-9 for n, (lo, hi) in r["when"].items())
        if not ok:
            continue
        code = r["code"]
        if code == "SHELL_FIXED_REGION_VIOLATION" and not fixed:
            continue
        if (code in MORPH_CODES) != (stage == "morph"):
            continue
        return code
    return None


# ---------------------------------------------------------------- 명령
def cmd_version(a, rep) -> int:
    d = {"paicad": CTL.get("version", VERSION), "ocp": CTL.get("ocp", "7.8.1.1.post1"), "numpy": np.__version__,
         "scipy": "1.x", "python": sys.version.split()[0]}
    print(json.dumps(d) if a.json else " ".join(f"{k} {v}" for k, v in d.items()), flush=True)
    return 0


def cmd_fixed_scan(a, rep) -> int:
    no_overwrite(a.out_dir, ["shell_scan.json", "fixed_nodes.npz"])
    rep.progress(5, "scanning assembly")
    forced("fixed-scan")
    pid = int(str(a.parts).split(",")[0])
    m = part_mesh(a.assem_dir, pid)
    maybe_sleep("fixed-scan", rep)
    X = m["x0"]
    groups = []
    if not CTL.get("fixed_none"):
        lo, hi = X.min(axis=0), X.max(axis=0)
        for c in ([lo[0], lo[1], lo[2]], [hi[0], lo[1], lo[2]], [lo[0], lo[1], hi[2]], [hi[0], lo[1], hi[2]]):
            d = np.linalg.norm(X - np.asarray(c), axis=1)
            groups.append([int(i) for i in np.argsort(d)[:2]])
    import synth_doe as sd
    sd.write_fixed(a.out_dir, {"node_id": m["node_id"], "x0": X}, groups)
    rep.progress(100, "fixed-scan done")
    rep.result("OK", None, "shell_scan.json")
    return 0


def cmd_extract(a, rep) -> int:
    no_overwrite(a.out_dir, ["shell_features.json"])
    rep.progress(5, "loading CAD")
    if not os.path.isfile(a.cad):
        raise Fail("GEOM_INPUT_INVALID", 3, "cad not found")
    forced("extract")
    maybe_sleep("extract", rep)
    import synth_doe as sd
    doc = sd.features_doc({"x0": plate_box()}, int(CTL.get("n_beads", 2)), comp=COMP,
                          fixed_overlap_last=bool(CTL.get("fixed_overlap_last")))
    pid = pid_of_body_map(a.body_map)
    doc["parts"] = [{"body": "SHEET", "part_id": pid, "title": None}]
    doc["engine_version"] = CTL.get("version", VERSION)
    if not a.no_png:
        for f in doc["features"]:
            p = os.path.join(a.out_dir, f["png"])
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as fh:
                fh.write(png())
    with open(os.path.join(a.out_dir, "parameter_extracted.xml"), "w", encoding="utf-8") as fh:
        fh.write("<parameters/>\n")
    dump(os.path.join(a.out_dir, "shell_features.json"), doc)
    rep.progress(100, f"{len(doc['beads'])} beads")
    rep.result("OK", None, "shell_features.json")
    return 0


def cmd_tag(a, rep) -> int:
    no_overwrite(a.out_dir, ["shell_tag.json"])
    forced("tag")
    if not os.path.isfile(os.path.join(a.fixed_dir, "shell_scan.json")):
        raise Fail("GEOM_INPUT_INVALID", 3, "fixed dir has no shell_scan.json")
    pid = pid_of_body_map(a.body_map)
    m = part_mesh(a.assem_dir, pid)
    maybe_sleep("tag", rep)
    dump(os.path.join(a.out_dir, "shell_tag.json"), env(status="OK", code=None, part_id=pid,
                                                        n_nodes=int(m["node_id"].size), warnings=[]))
    rep.progress(100, "tag done")
    rep.result("OK", None, "shell_tag.json")
    return 0


def write_brep(path: str, values: dict) -> None:
    """③: 판 BREP(제어 brep=gmsh 이면 실제 OCC 판 — D_1 이 공칭 4 에서 바뀌면 x 길이 ±2 mm/mm), 아니면 텍스트."""
    if CTL.get("brep") == "gmsh":
        import gmsh
        box = plate_box()
        lx, lz = float(box[1, 0] - box[0, 0]), float(box[1, 2] - box[0, 2])
        lx += 2.0 * (float(values.get(f"{COMP}_BEAD_D_1", 4.0)) - 4.0)
        lz += 1.0 * (float(values.get(f"{COMP}_BEAD_D_2", 4.0)) - 4.0)
        gmsh.initialize(["-noenv"], readConfigFiles=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            s = gmsh.model.occ.addRectangle(float(box[0, 0]), float(box[0, 2]), 0.0, lx, lz)
            gmsh.model.occ.rotate([(2, s)], 0, 0, 0, 1, 0, 0, np.pi / 2)    # XY → XZ 평면(y = 0)
            gmsh.model.occ.synchronize()
            gmsh.write(path)
        finally:
            gmsh.finalize()
        return
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("fake brep\n" + json.dumps(values, sort_keys=True) + "\n")


def do_update(cad: str, features: str, values_path: str, out_dir: str, fixed: bool, rep: Rep) -> dict:
    no_overwrite(out_dir, ["shell_update.json", "sample.brep", "face_map.json"])
    feats = load_features(features)
    vals = full_values(feats, load_values(values_path))
    code = rule_code(vals, fixed=fixed, stage="update")
    if code:
        dump(os.path.join(out_dir, "shell_update.json"), env(status="FAIL", code=code, category="GEOM",
                                                            message=f"fake {code}", values=vals))
        raise Fail(code, CODE_EXIT.get(code, 10), f"fake {code}")
    write_brep(os.path.join(out_dir, "sample.brep"), vals)
    dump(os.path.join(out_dir, "face_map.json"), {"schema_version": 1, "faces": []})
    dump(os.path.join(out_dir, "shell_update.json"), env(status="OK", code=None, values=vals, warnings=[]))
    return vals


def cmd_update(a, rep) -> int:
    rep.progress(5, "update")
    forced("update")
    maybe_sleep("update", rep, load_values(a.values))
    do_update(a.cad, a.features, a.values, a.out_dir, bool(a.fixed_dir), rep)
    rep.progress(100, "update done")
    rep.result("OK", None, "shell_update.json")
    return 0


def _node_line(nid: int, x) -> str:
    return f"{nid:>10d}{x[0]:>20.9f}{x[1]:>20.9f}{x[2]:>20.9f}"


def morph_copy(src: str, dst: str, newx: dict[int, np.ndarray]) -> int:
    """/NODE 블록의 대상 노드 줄만 좌표 교체(나머지 줄 그대로). 바뀐 노드 수."""
    from esl.doe.nodes import _parse_node_line
    out, n, in_node = [], 0, False
    with open(src, encoding="utf-8", errors="surrogateescape") as fh:
        for k, line in enumerate(fh, 1):
            s = line.rstrip("\r\n")
            if s[:1] == "/":
                toks = s[1:].split("/")[0].split()
                in_node = bool(toks) and toks[0].upper() == "NODE"
            elif in_node and s.strip() and s[:1] not in ("#", "$"):
                nid, _xyz = _parse_node_line(s, src, k)
                if nid in newx:
                    line = _node_line(nid, newx[nid]) + "\n"
                    n += 1
            out.append(line)
    if n:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            fh.writelines(out)
    return n


def cmd_run(a, rep) -> int:
    for d, names in ((a.update_dir, ["shell_update.json", "sample.brep"]), (a.morph_dir, ["shell_morph.json", "files"]),
                     (a.check_dir, ["shell_check.json", "shell_run.json"])):
        no_overwrite(d, names)
    forced("run")
    stages, fail = [], None
    rep.progress(2, "update")
    try:
        os.makedirs(a.update_dir, exist_ok=True)
        vals = do_update(a.cad, a.features, a.values, a.update_dir, True, rep)
        stages.append({"step": "update", "exit_code": 0, "status": "OK"})
        maybe_sleep("run", rep, vals)
        rep.progress(35, "morph")
        code = rule_code(vals, fixed=True, stage="morph")
        if code:
            dump(os.path.join(a.morph_dir, "shell_morph.json"), env(status="FAIL", code=code, files=[]))
            raise Fail(code, CODE_EXIT.get(code, 11), f"fake {code}")
        pid = pid_of_body_map(a.body_map)
        m = part_mesh(a.assem_dir, pid)
        import synth_doe as sd
        x = sd.morph_x({"x0": m["x0"]}, vals)
        with np.load(os.path.join(a.fixed_dir, "fixed_nodes.npz"), allow_pickle=False) as z:
            fixed_ids = set(int(v) for v in z["node_id"])
        newx = {}
        for i, nid in enumerate(m["node_id"].tolist()):
            if int(nid) in fixed_ids:
                continue
            if np.linalg.norm(x[i] - m["x0"][i]) > 0:
                newx[int(nid)] = x[i]
        files, rels = [], []
        for src in rad_files(a.assem_dir):
            rel = os.path.relpath(src, a.assem_dir).replace(os.sep, "/")
            n = morph_copy(src, os.path.join(a.morph_dir, "files", rel), newx)
            if n:
                files.append({"rel": rel, "moved_nodes": n})
        dump(os.path.join(a.morph_dir, "shell_morph.json"), env(status="OK", code=None, files=files))
        stages.append({"step": "morph", "exit_code": 0, "status": "OK"})
        rep.progress(70, "check")
        for f in files:
            src = os.path.join(a.morph_dir, "files", *f["rel"].split("/"))
            dst = os.path.join(a.out_files_dir, *f["rel"].split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(src, "rb") as s, open(dst, "wb") as d:
                d.write(s.read())
            rels.append(f["rel"])
        dump(os.path.join(a.check_dir, "shell_check.json"), env(status="PASS", code=None, out_files=rels, warnings=[]))
        stages.append({"step": "check", "exit_code": 0, "status": "PASS"})
    except Fail as e:
        fail = e
    doc = env(status="FAIL" if fail else "PASS", code=fail.code if fail else None,
              message=fail.message if fail else None, stages=stages, out_files=[] if fail else rels,
              solver="radioss")
    dump(os.path.join(a.check_dir, "shell_run.json"), doc)
    rep.progress(100, f"shell run {doc['status']}")
    rep.result(doc["status"], doc["code"], "shell_run.json")
    return fail.exit_code if fail else 0


def cmd_grid(a, rep) -> int:
    no_overwrite(a.out_dir, ["grid_manifest.json", "cells"])
    rep.progress(5, "loading")
    forced("grid")
    with open(a.cells, encoding="utf-8") as fh:
        cells = json.load(fh)["cells"]
    with open(a.thumb_options, encoding="utf-8") as fh:
        topts = json.load(fh)
    feats = load_features(a.features)
    fixed = bool(a.fixed_dir)
    if fixed and not os.path.isfile(os.path.join(a.fixed_dir, "shell_scan.json")):
        raise Fail("GEOM_INPUT_INVALID", 3, "fixed dir")
    maybe_sleep("grid", rep)
    rows = []
    for i, c in enumerate(cells):
        rep.progress(15 + int(80 * i / max(1, len(cells))), f"cell {i + 1}/{len(cells)} {c['id']}")
        vals = full_values(feats, {k: float(v) for k, v in (c.get("values") or {}).items()})
        code = rule_code(vals, fixed=fixed, stage="update")
        cd = os.path.join(a.out_dir, "cells", c["id"])
        os.makedirs(cd, exist_ok=True)
        if c["id"] in (CTL.get("view_error") or []):
            status, code = "ERROR", "VIEW_TOO_LARGE"
        else:
            status = "FAIL" if code else "OK"
            with open(os.path.join(cd, "thumb.png"), "wb") as fh:
                fh.write(png(rgb=(200, 60, 60) if code else (30, 120, 200)))
            dump(os.path.join(cd, "preview_manifest.json"), {"status": status, "code": code, "values": vals})
        rows.append({"id": c["id"], "status": status, "code": code, "category": None, "max_disp_mm": None,
                     "total_s": 0.0})
    box = plate_box()
    dump(os.path.join(a.out_dir, "grid_manifest.json"), {
        "schema_version": 1, "kind": "shell", "engine_version": CTL.get("version", VERSION),
        "camera": {"view_dir": topts.get("view_dir"), "center": box.mean(axis=0).tolist(), "scale": 1.0,
                   "digest": "fake"},
        "disp_range_mm": topts.get("disp_range_mm"),
        "nominal": {"bbox": box.tolist(), "view_sha256": hashlib.sha256(b"nominal").hexdigest()},
        "cells": rows, "timing": {"load_s": 0.0, "total_s": 0.0}})
    rep.progress(100, "grid done")
    rep.result("OK", None, "grid_manifest.json")
    return 0


# ---------------------------------------------------------------- argparse
def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="paicad", allow_abbrev=False)
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("version", allow_abbrev=False)
    v.add_argument("--json", action="store_true")
    sh = sub.add_parser("shell", allow_abbrev=False)
    ss = sh.add_subparsers(dest="shell_cmd", required=True)

    def common(x, threads=True, options=True):
        if options:
            x.add_argument("--options")
        if threads:
            x.add_argument("--threads", type=int)
        return x

    f = common(ss.add_parser("fixed-scan", allow_abbrev=False))
    for k in ("--assem-dir", "--out-dir"):
        f.add_argument(k, required=True)
    f.add_argument("--parts")
    f.add_argument("--features")
    e = common(ss.add_parser("extract", allow_abbrev=False))
    for k in ("--cad", "--out-dir"):
        e.add_argument(k, required=True)
    e.add_argument("--assem-dir")
    e.add_argument("--body-map")
    e.add_argument("--no-png", action="store_true")
    t = common(ss.add_parser("tag", allow_abbrev=False))
    for k in ("--cad", "--features", "--assem-dir", "--fixed-dir", "--out-dir"):
        t.add_argument(k, required=True)
    t.add_argument("--body-map")
    u = common(ss.add_parser("update", allow_abbrev=False))
    for k in ("--cad", "--features", "--values", "--out-dir"):
        u.add_argument(k, required=True)
    u.add_argument("--fixed-dir")
    u.add_argument("--body-map")
    r = common(ss.add_parser("run", allow_abbrev=False))
    for k in ("--cad", "--features", "--values", "--assem-dir", "--tag-dir", "--fixed-dir", "--update-dir",
              "--morph-dir", "--check-dir", "--out-files-dir"):
        r.add_argument(k, required=True)
    for k in ("--body-map", "--thickness", "--solver"):
        r.add_argument(k)
    vw = ss.add_parser("view", allow_abbrev=False)
    vs = vw.add_subparsers(dest="view_cmd", required=True)
    g = common(vs.add_parser("grid", allow_abbrev=False))
    for k in ("--cad", "--features", "--cells", "--out-dir", "--fixed-dir", "--thumb-options"):
        g.add_argument(k, required=True)
    for k in ("--tag-dir", "--body-map", "--view-options"):
        g.add_argument(k)
    return p


OUT_OF = {"fixed-scan": "out_dir", "extract": "out_dir", "tag": "out_dir", "update": "out_dir", "run": "check_dir",
          "grid": "out_dir"}
FN = {"fixed-scan": cmd_fixed_scan, "extract": cmd_extract, "tag": cmd_tag, "update": cmd_update, "run": cmd_run,
      "grid": cmd_grid}
REPORT = {"fixed-scan": "shell_scan.json", "extract": None, "tag": "shell_tag.json", "update": "shell_update.json",
          "run": "shell_run.json", "grid": None}


def main(argv=None) -> int:
    t0 = time.time()
    a = parser().parse_args(argv)
    if a.cmd == "version":
        try:
            return cmd_version(a, None)
        finally:
            record("version", t0)
    name = "grid" if a.shell_cmd == "view" else a.shell_cmd
    out = getattr(a, OUT_OF[name])
    run_dir = os.path.join(DIR, "fake_paicad_running")       # 시작한 프로세스 pid(취소 시 트리 종료 확인용)
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, f"{os.getpid()}.json"), "w", encoding="utf-8") as fh:
        json.dump({"cmd": name, "argv": sys.argv[1:]}, fh)
    rep = Rep(out)
    try:
        code = FN[name](a, rep)
    except Fail as e:
        rep.line(f"[fake paicad] {e.code}: {e.message}")
        rp = REPORT.get(name)
        if rp and name != "run" and not os.path.exists(os.path.join(out, rp)):
            dump(os.path.join(out, rp), env(status="FAIL", code=e.code, category=None, message=e.message))
        if name not in (CTL.get("no_result") or []):
            rep.result("FAIL", e.code, rp if rp and os.path.exists(os.path.join(out, rp)) else None)
        code = e.exit_code
    finally:
        record(name, t0)
    return code


if __name__ == "__main__":
    sys.exit(main())
