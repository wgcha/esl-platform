"""paicad ``shell fixed-scan`` 결과 읽기 (v0.24.4 이동 — 원래 ``esl/doe/paicad_io.py``, 계약 esl_jig_case.md §4.1·D-0.24.4-JIG-10).

읽기 전용 IO(``shell_scan.json``·``fixed_nodes.npz``). 강성 스터디(prep/fixed)와 Case 지그(01_extract/jig_fixed — 워커
jig_prep 가 씀)가 함께 쓴다 — Case 파이프라인이 ``esl.doe`` 를 import 하지 않게 여기에 둔다. 옛 이름은
``esl.doe.paicad_io`` 가 같은 객체로 재수출한다(``read_json_limited`` 포함 — 보고 JSON 크기 상한 읽기).
"""
from __future__ import annotations

import json
import os

import numpy as np

from esl.errors import EslError

SCAN_JSON = "shell_scan.json"
FIXED_NPZ = "fixed_nodes.npz"
FIXED_KINDS = ("INTER_TYPE2_SECONDARY", "INTER_TYPE2_MAIN", "RBE2", "RBE3", "RBODY", "BCS", "SHARED")


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
