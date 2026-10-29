"""paicad 입출력 계층 (계약 esl_bead_doe.md §6, BD-D-19). **실행은 하지 않는다** — 워커(D3 ``paicad_proc``)가
여기서 만든 argv 를 ``localproc``(셸 없이)로 돌리고, 종료코드·stdout·출력 폴더를 여기에 넘겨 판정한다.

- argv: 설정 ``commands.paicad_*`` 템플릿의 ``{name}`` 을 값으로 바꾼다. ``{name?}`` 가 None 이면 **바로 앞 플래그와
  함께 제거**(빈 문자열은 유지 — ③ ``--fixed-dir ""``). 그 밖 자리표시자가 None·누락이면 ``CONFIG_INVALID``.
  argv[0] 은 ``{paicad}`` 여야 한다(허용목록). 값은 str·int 만(사용자 문자열은 호출자가 넣지 않는다 — 파트는 id).
- stdout: ``PAICAD PROGRESS n msg`` → 진행률, 마지막 ``PAICAD RESULT status code report`` → 결과.
- 판정: 종료 0 + RESULT OK/PASS + 보고 JSON 존재·status OK/PASS = 성공. 실패 코드 → 플랫폼 코드는
  ``resources/doe_messages.json`` 원본 1곳(§6.3, 모르는 코드는 종료코드 범주).
- 보고 JSON 은 크기 상한(``limits.max_json_mb``) 후 파싱. 키 검사(R-BD-6)는 각 reader 가 한다.
"""
from __future__ import annotations

import json
import os
import re

import numpy as np

from esl.doe import FAILED, SKIPPED, commands, load_messages
from esl.errors import EslError

# paicad 보고 파일 이름(0.14.0 소스 확인값)
EXTRACT_JSON = "shell_features.json"
SCAN_JSON = "shell_scan.json"
FIXED_NPZ = "fixed_nodes.npz"
TAG_JSON = "shell_tag.json"
UPDATE_JSON = "shell_update.json"
MORPH_JSON = "shell_morph.json"
CHECK_JSON = "shell_check.json"
RUN_JSON = "shell_run.json"
GRID_MANIFEST = "grid_manifest.json"
SAMPLE_BREP = "sample.brep"
REPORT_OF = {"fixed_scan": SCAN_JSON, "extract": EXTRACT_JSON, "tag": TAG_JSON, "update": UPDATE_JSON,
             "run": RUN_JSON, "grid": GRID_MANIFEST}

TYPE_LETTER = {"BEAD_DEPTH": "D", "BEAD_WIDTH": "W", "BEAD_POS_U": "U", "BEAD_POS_V": "V"}
FIXED_KINDS = ("INTER_TYPE2_SECONDARY", "INTER_TYPE2_MAIN", "RBE2", "RBE3", "RBODY", "BCS", "SHARED")
EXIT_ARGS, EXIT_INTERNAL, EXIT_INTERRUPTED = 2, 20, 130
PATH_KEYS = ("assem_dir", "out_dir", "cad", "features", "fixed_dir", "tag_dir", "values", "cells", "thumb",
             "options", "body_map", "update_dir", "morph_dir", "check_dir", "out_files_dir")

_PH = re.compile(r"\{([a-z_]+)(\?)?\}")
_PROGRESS = re.compile(r"^PAICAD PROGRESS (-?\d+)(?: (.*))?$")
_RESULT = re.compile(r"^PAICAD RESULT (\S+) (\S+) (\S+)\s*$")


# ---------------------------------------------------------------- argv
def build_argv(template: list, values: dict) -> list[str]:
    """argv 템플릿 + 값 → argv (선택 쌍 규칙, §6.1)."""
    if not isinstance(template, list) or not template or template[0] != "{paicad}":
        raise EslError("CONFIG_INVALID", "paicad 명령 템플릿 argv[0] 은 '{paicad}' 이어야 함")
    out: list[str] = []
    for tok in template:
        if not isinstance(tok, str):
            raise EslError("CONFIG_INVALID", f"argv 템플릿 항목은 문자열: {tok!r}")
        m = _PH.fullmatch(tok)
        if m is None:
            if "{" in tok or "}" in tok:
                raise EslError("CONFIG_INVALID", f"argv 템플릿 자리표시자 형식 오류: {tok!r}")
            out.append(tok)
            continue
        name, opt = m.group(1), m.group(2) == "?"
        v = values.get(name)
        if v is None:
            if opt:
                if out and out[-1].startswith("-") and len(out) > 1:
                    out.pop()
                continue
            raise EslError("CONFIG_INVALID", f"paicad 인자 '{name}' 값이 없음")
        if isinstance(v, bool) or not isinstance(v, (str, int, os.PathLike)):
            raise EslError("CONFIG_INVALID", f"paicad 인자 '{name}' 는 문자열·정수 (값 {type(v).__name__})")
        out.append(os.fspath(v) if isinstance(v, os.PathLike) else str(v))
    return out


def command_argv(key: str, values: dict, cfg: dict | None = None) -> list[str]:
    """``commands.<key>`` 템플릿(설정 우선) → argv. values 에 ``paicad`` (exe 경로)를 넣는다."""
    tpl = commands(cfg).get(key)
    if tpl is None:
        raise EslError("CONFIG_INVALID", f"알 수 없는 paicad 명령 키: {key}")
    return build_argv(tpl, values)


def parts_arg(part_ids) -> str:
    ids = sorted({int(p) for p in part_ids})
    if not ids:
        raise EslError("CONFIG_INVALID", "paicad --parts 에 파트 id 가 없음")
    return ",".join(str(i) for i in ids)


# ---------------------------------------------------------------- stdout
def parse_line(line: str):
    """('progress', pct, msg) | ('result', status, code|None, report|None) | None."""
    s = line.rstrip("\r\n")
    m = _PROGRESS.match(s)
    if m:
        return ("progress", max(0, min(100, int(m.group(1)))), m.group(2) or "")
    m = _RESULT.match(s)
    if m:
        code = None if m.group(2) == "-" else m.group(2)
        rep = None if m.group(3) == "-" else m.group(3)
        return ("result", m.group(1), code, rep)
    return None


def parse_stdout(text: str) -> dict:
    """{progress: [(pct, msg)], result: (status, code, report) | None} — 결과는 마지막 RESULT 줄."""
    prog, res = [], None
    for ln in (text or "").splitlines():
        p = parse_line(ln)
        if p is None:
            continue
        if p[0] == "progress":
            prog.append((p[1], p[2]))
        else:
            res = (p[1], p[2], p[3])
    return {"progress": prog, "result": res}


# ---------------------------------------------------------------- 코드 분류
def classify(stage: str, exit_code: int | None, code: str | None = None, *, timeout: bool = False,
             messages: dict | None = None) -> dict:
    """paicad 실패 → {code(플랫폼), paicad_code, exit_code, message, status}.

    stage: ``prep``(작업 실패) | ``preview``(셀) | ``design``(안 상태). status 는 design/preview 에서 안 상태
    (SKIPPED_*·FAILED_*), prep 에서는 None."""
    M = messages or load_messages()
    if timeout:
        pc = "PAICAD_TIMEOUT"
    elif exit_code == EXIT_ARGS:
        pc = "PAICAD_INTERNAL"
    elif exit_code in (EXIT_INTERNAL, EXIT_INTERRUPTED) and (code is None or code == "GEOM_INTERNAL"):
        pc = "PAICAD_FAILED"
    else:
        pc = M["paicad_codes"].get(code) if code else None
        if pc is None:
            ec = M["exit_category"]
            pc = ec.get(str(exit_code), ec["other"])
    status = None
    if stage == "prep":
        if pc in SKIPPED or pc in FAILED or pc == "THUMB_UNAVAILABLE":
            pc = "PAICAD_INPUT"
    else:
        status = pc if (pc in SKIPPED or pc in FAILED) else None
        if status is None and pc != "THUMB_UNAVAILABLE":
            status = "SKIPPED_GEOM" if stage == "preview" else "FAILED_MORPH"
    msg = M["messages"].get(pc, pc)
    if code and code not in M["paicad_codes"]:
        msg = f"{msg} (paicad {code})"
    return {"code": pc, "paicad_code": code, "exit_code": exit_code, "message": msg, "status": status}


# ---------------------------------------------------------------- 보고 JSON
def read_json_limited(path: str, max_mb: float) -> dict:
    try:
        size = os.path.getsize(path)
    except OSError:
        raise EslError("PAICAD_FAILED", f"paicad 보고 파일이 없음: {os.path.basename(path)}") from None
    if size > float(max_mb) * 1024 * 1024:
        raise EslError("PAICAD_FAILED", f"paicad 보고 파일이 상한 {max_mb} MB 를 넘음: {os.path.basename(path)}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        raise EslError("PAICAD_FAILED", f"paicad 보고 파일을 읽지 못함: {os.path.basename(path)}: {exc}") from None
    if not isinstance(doc, dict):
        raise EslError("PAICAD_FAILED", f"paicad 보고 파일 최상위가 객체가 아님: {os.path.basename(path)}")
    return doc


def judge(stage: str, exit_code: int | None, stdout: str, report_path: str | None, *, timeout: bool = False,
          max_mb: float = 64) -> dict:
    """§6.2 판정 → {ok, code, status, message, result, report(doc|None), warnings[]}.

    성공 = 종료 0 + RESULT OK/PASS + 보고 JSON 존재 + (보고에 status 가 있으면) OK/PASS."""
    res = parse_stdout(stdout)["result"]
    doc = None
    if report_path and os.path.isfile(report_path):
        try:
            doc = read_json_limited(report_path, max_mb)
        except EslError:
            doc = None
    warns = list((doc or {}).get("warnings") or [])
    good = ("OK", "PASS")
    if (not timeout and exit_code == 0 and res is not None and res[0] in good and doc is not None
            and doc.get("status", "OK") in good):
        return {"ok": True, "code": None, "status": None, "message": None, "result": res, "report": doc,
                "warnings": warns}
    code = (doc or {}).get("code") or (res[1] if res else None)
    if not timeout and exit_code == 0 and doc is None:
        c = {"code": "PAICAD_FAILED", "paicad_code": code, "exit_code": 0,
             "message": load_messages()["messages"]["PAICAD_FAILED"], "status": None if stage == "prep" else
             ("SKIPPED_GEOM" if stage == "preview" else "FAILED_MORPH")}
    else:
        c = classify(stage, exit_code if exit_code != 0 else None, code, timeout=timeout)
    return {"ok": False, "code": c["code"], "paicad_code": c["paicad_code"], "status": c["status"],
            "message": c["message"], "result": res, "report": doc, "warnings": warns,
            "detail": (doc or {}).get("message")}


# ---------------------------------------------------------------- 버전 (BD-D-19, §6.5)
def _ver(s) -> tuple:
    out = []
    for p in str(s).split("."):
        m = re.match(r"\d+", p)
        out.append(int(m.group(0)) if m else 0)
    return tuple(out + [0] * (3 - len(out)))


def parse_version_json(text: str) -> dict:
    try:
        d = json.loads(text)
    except ValueError:
        raise EslError("PAICAD_CHECK_FAILED", "paicad version --json 출력이 JSON 이 아님") from None
    if not isinstance(d, dict) or not isinstance(d.get("paicad"), str):
        raise EslError("PAICAD_CHECK_FAILED", "paicad version --json 에 paicad 버전이 없음")
    return d


def check_version(vjson: dict | None, cfg: dict) -> dict:
    """{ready, version, ocp, pinned, warning, reason} — reason ∈ PAICAD_VERSION_LOW·PAICAD_OCP_MISSING·None."""
    pc = cfg["paicad"]
    pinned = pc.get("pinned_version")
    if not vjson:
        return {"ready": False, "version": None, "ocp": None, "pinned": pinned, "warning": None,
                "reason": "PAICAD_CHECK_FAILED"}
    v = str(vjson.get("paicad"))
    ocp = vjson.get("ocp")
    out = {"ready": True, "version": v, "ocp": ocp, "pinned": pinned, "warning": None, "reason": None}
    if _ver(v) < _ver(pc["min_version"]):
        out.update(ready=False, reason="PAICAD_VERSION_LOW")
    elif ocp is None:
        out.update(ready=False, reason="PAICAD_OCP_MISSING")
    if pinned and v != str(pinned):
        out["warning"] = f"PAICAD_VERSION_PINNED: paicad {v} ≠ 배포 고정 {pinned}"
    return out


# ---------------------------------------------------------------- extract → 비드·변수 표
def read_features(d: str, max_mb: float = 64) -> dict:
    doc = read_json_limited(os.path.join(d, EXTRACT_JSON), max_mb)
    if doc.get("schema_version") != 1 or doc.get("kind") != "shell":
        raise EslError("PAICAD_FAILED", "shell_features.json 이 shell 스키마 1 이 아님")
    for k in ("parts", "beads", "features"):
        if not isinstance(doc.get(k), list):
            raise EslError("PAICAD_FAILED", f"shell_features.json 에 {k} 목록이 없음")
    for f in doc["features"]:
        for k in ("name", "type", "bead", "nominal"):
            if k not in f:
                raise EslError("PAICAD_FAILED", f"shell_features.json features 항목에 {k} 가 없음")
    return doc


def param_keys(doc: dict, options: dict | None = None) -> list[str]:
    """값 파일 키 = 그룹 대표 + 비그룹 이름(paicad ``shell.common.param_keys`` 와 같은 규칙)."""
    split = set((options or {}).get("symmetry_split") or [])
    grp = {g["id"]: g for g in doc.get("groups") or []}
    keys = []
    for f in doc["features"]:
        g = f.get("group")
        if g is None or g in split or grp.get(g, {}).get("parameter") == f["name"]:
            keys.append(f["name"])
    return keys


def _pair(x):
    if isinstance(x, dict) and "min" in x and "max" in x:
        return [float(x["min"]), float(x["max"])]
    if isinstance(x, (list, tuple)) and len(x) == 2:
        return [float(x[0]), float(x[1])]
    return None


def params_table(doc: dict, options: dict | None = None) -> list[dict]:
    """DoeParamsOut.params 행: {name, type D|W|U|V, bead, nominal, feasible, feasible_source, default_range,
    use_default, group_members}."""
    split = set((options or {}).get("symmetry_split") or [])
    grp = {g["id"]: g for g in doc.get("groups") or []}
    keys = set(param_keys(doc, options))
    out = []
    for f in doc["features"]:
        if f["name"] not in keys:
            continue
        t = TYPE_LETTER.get(f["type"])
        if t is None:
            continue
        g = f.get("group")
        members = list(grp[g]["members"]) if g is not None and g not in split and g in grp else [f["name"]]
        fe = f.get("feasible") or {}
        out.append({"name": f["name"], "type": t, "bead": f["bead"], "nominal": float(f["nominal"]),
                    "feasible": _pair(fe), "feasible_source": (fe.get("source") if isinstance(fe, dict) else None)
                    or "estimate", "default_range": _pair(f.get("range")) or _pair(fe),
                    "use_default": bool(f.get("use_default", True)), "group_members": members})
    out.sort(key=lambda r: r["name"])
    return out


def beads_table(doc: dict, frame: dict | None = None) -> list[dict]:
    """DoeParamsOut.beads 행(center_ab = frame 평면 좌표)."""
    from esl.opt.keepout import project_ab
    out = []
    for b in doc["beads"]:
        c = b.get("center") or [0.0, 0.0, 0.0]
        ab = project_ab(frame, c)[0].tolist() if frame else None
        nom = b.get("nominal") or {}
        png = None
        for f in doc["features"]:
            if f.get("bead") == b["id"] and f.get("png"):
                png = f["png"]
                break
        out.append({"id": b["id"], "k": b.get("k"), "shape": b.get("shape"), "sense": b.get("sense"),
                    "center_ab": ab, "nominal": {k: nom.get(k) for k in ("depth", "width", "length")},
                    "fixed_overlap": b.get("fixed_overlap"), "png": png})
    return out


def body_map_doc(extract0: dict, part_id: int) -> dict:
    """STEP 바디 1개 → {schema_version:1, map:{바디: "PART:<pid>"}} (바디 ≠ 1 → STEP_BODY_COUNT)."""
    bodies = [p.get("body") for p in extract0.get("parts") or [] if p.get("body")]
    if len(bodies) != 1:
        raise EslError("STEP_BODY_COUNT", f"STEP 바디가 {len(bodies)}개 — Ch/R 중립면 바디 1개만 지원")
    return {"schema_version": 1, "map": {bodies[0]: f"PART:{int(part_id)}"}}


def extract_warnings(doc: dict) -> list[dict]:
    return [{"code": w.get("code"), "bead": w.get("bead"), "message": w.get("message")}
            for w in doc.get("warnings") or [] if isinstance(w, dict)]


# ---------------------------------------------------------------- fixed-scan
def read_fixed(d: str, max_mb: float = 64) -> dict:
    """{doc, node_id, part, kind_mask, cluster, xyz, clusters[{id, center, kinds, nodes}]}."""
    doc = read_json_limited(os.path.join(d, SCAN_JSON), max_mb)
    if doc.get("status") != "OK":
        raise EslError("FIXED_PARSE_FAILED", f"fixed-scan 상태 {doc.get('status')} {doc.get('code')}")
    p = os.path.join(d, FIXED_NPZ)
    if not os.path.isfile(p):
        raise EslError("PAICAD_FAILED", "fixed_nodes.npz 가 없음")
    with np.load(p, allow_pickle=False) as z:
        arr = {k: np.asarray(z[k]) for k in ("node_id", "part", "kind_mask", "cluster", "xyz")}
    fx = doc.get("fixed") or {}
    return {"doc": doc, **arr, "clusters": list(fx.get("clusters") or [])}


def kind_labels(mask: int) -> list[str]:
    return [k for b, k in enumerate(FIXED_KINDS) if int(mask) & (1 << b)]


def fixed_points(fx: dict) -> list[dict]:
    """클러스터별 노드 평균 점 [{label, kind, xyz, n}] (§8.2, kind_mask 로 라벨)."""
    out = []
    cl = np.asarray(fx["cluster"], dtype=np.int64)
    X = np.asarray(fx["xyz"], dtype=np.float64).reshape(-1, 3)
    km = np.asarray(fx["kind_mask"], dtype=np.int64)
    for c in sorted(set(cl.tolist())):
        m = cl == c
        mask = int(np.bitwise_or.reduce(km[m])) if m.any() else 0
        kinds = kind_labels(mask)
        kind = next((k for k in ("RBE2", "RBE3", "RBODY", "INTER_TYPE2_SECONDARY", "INTER_TYPE2_MAIN", "BCS", "SHARED")
                     if k in kinds), kinds[0] if kinds else "FIXED")
        kind = "INTER_TYPE2" if kind.startswith("INTER_TYPE2") else kind
        out.append({"label": f"{kind}#{c}", "kind": kind, "xyz": X[m].mean(axis=0).tolist(), "n": int(m.sum())})
    return out


# ---------------------------------------------------------------- grid / run / update
def cell_state(cell: dict) -> dict:
    """grid_manifest 셀 → {id, state, code, warning} (§5: OK→READY, FAIL→스킵, ERROR VIEW_*→READY+경고, 그 밖→SKIPPED_GEOM)."""
    st, code = cell.get("status"), cell.get("code")
    if st == "OK":
        return {"id": cell["id"], "state": "READY", "code": None, "warning": None}
    if st == "ERROR" and str(code or "").startswith("VIEW_"):
        return {"id": cell["id"], "state": "READY", "code": code, "warning": "THUMB_UNAVAILABLE"}
    if st == "FAIL":
        c = classify("preview", 10, code)
        s = c["status"] if c["status"] in SKIPPED else "SKIPPED_GEOM"
        return {"id": cell["id"], "state": s, "code": code, "warning": None}
    return {"id": cell["id"], "state": "SKIPPED_GEOM", "code": code or "GEOM_INTERNAL", "warning": None}


def read_grid(d: str, ids: list[str] | None = None, max_mb: float = 64) -> dict:
    """{cells:[cell_state], counts{ok, collision, fixed, geom, thumb_warn}, missing[]}."""
    doc = read_json_limited(os.path.join(d, GRID_MANIFEST), max_mb)
    if not isinstance(doc.get("cells"), list):
        raise EslError("PAICAD_FAILED", "grid_manifest.json 에 cells 가 없음")
    rows = [cell_state(c) for c in doc["cells"] if isinstance(c, dict) and "id" in c]
    got = {r["id"] for r in rows}
    missing = [i for i in (ids or []) if i not in got]
    for i in missing:
        rows.append({"id": i, "state": "SKIPPED_GEOM", "code": "GRID_CELL_MISSING", "warning": None})
    rows.sort(key=lambda r: r["id"])
    cnt = {"ok": sum(r["state"] == "READY" for r in rows),
           "collision": sum(r["state"] == "SKIPPED_COLLISION" for r in rows),
           "fixed": sum(r["state"] == "SKIPPED_FIXED" for r in rows),
           "geom": sum(r["state"] == "SKIPPED_GEOM" for r in rows),
           "thumb_warn": sum(r["warning"] == "THUMB_UNAVAILABLE" for r in rows)}
    return {"cells": rows, "counts": cnt, "missing": missing, "manifest": doc}


def run_out_files(check_dir: str, max_mb: float = 64) -> tuple[list[str], dict]:
    """shell run(PASS) → (out_files 상대경로 목록, shell_run.json)."""
    doc = read_json_limited(os.path.join(check_dir, RUN_JSON), max_mb)
    if doc.get("status") != "PASS":
        raise EslError("PAICAD_FAILED", f"shell run 상태 {doc.get('status')} {doc.get('code')}")
    rels = doc.get("out_files") or []
    if not isinstance(rels, list) or not all(isinstance(r, str) for r in rels):
        raise EslError("PAICAD_FAILED", "shell_run.json out_files 형식 오류")
    return rels, doc


def morph_moved(morph_dir: str, max_mb: float = 64) -> int | None:
    """shell_morph.json files[].moved_nodes 합(없으면 None)."""
    p = os.path.join(morph_dir, MORPH_JSON)
    if not os.path.isfile(p):
        return None
    doc = read_json_limited(p, max_mb)
    try:
        return int(sum(int(f.get("moved_nodes") or 0) for f in doc.get("files") or []))
    except (TypeError, ValueError):
        return None
