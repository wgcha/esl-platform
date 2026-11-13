"""④ 형상 비교 전용 하중 전달 주변(계약 esl_load_transfer.md LT-7·8·9, §13.2 — 공용 모듈 load_transfer 밖).

평가 영역(③ ``step_graph.region_mask`` 재사용)·지지 이전(기준 d000 지지 → 형상 최근접 노드)·참값 a_direct 메시(스터디 물성)·
W 연산자 파일 캐시(prep/shapes/<did>/transfer.npz).
"""
from __future__ import annotations

import hashlib
import os

import numpy as np

from esl.errors import EslError
from esl.opt import target as tg


# 하중 전달 공용 모듈 밖)
def region_of(mesh: dict, a_xyz, rcfg: dict, h: float) -> tuple[np.ndarray | None, dict]:
    """LT-8 형상 평가 영역(③ ``step_graph.region_mask`` 재사용) → (요소 bool | None(= 전체), 정보)."""
    from esl.doe import step_graph as sg
    cfg = {"select": {"step_graph": {"region": {k: rcfg.get(k) for k in ("mode", "pad_mm", "min_frac")}}}}
    m, info = sg.region_mask(mesh, a_xyz, cfg, h)
    return (None if info["n_out"] == 0 else m), info


def region_messages(info: dict, rcfg: dict) -> tuple[list[dict], list[dict]]:
    """(경고 COMPARE_REGION_SMALL, 정보 COMPARE_REGION) 구조화 dict."""
    warns, infos = [], []
    if info["n_out"] > 0:
        infos.append({"code": "COMPARE_REGION", "n_in": info["n_in"], "n_out": info["n_out"],
                      "out_bbox": info["out_bbox"], "mode": info["mode"]})
    if float(info["n_in"]) < float(rcfg["min_frac"]) * float(info["n_in"] + info["n_out"]):
        warns.append({"code": "COMPARE_REGION_SMALL", "frac": info["frac"], "min_frac": float(rcfg["min_frac"])})
    return warns, infos


def region_nodes(mesh: dict, region) -> np.ndarray:
    from esl.doe import step_graph as sg
    return sg.region_nodes(mesh, region)


def auto_supports(mesh: dict, region) -> list:
    """영역 노드로 PCA 3-2-1(영역 = 전체면 ``target.auto_supports`` 와 같음)."""
    if region is None:
        return tg.auto_supports(mesh)
    rn = region_nodes(mesh, region)
    return tg.auto_supports({"x0": np.asarray(mesh["x0"])[rn], "node_id": np.asarray(mesh["node_id"])[rn]})


def support_xyz(mesh: dict, supports) -> list[dict]:
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    pos = {int(v): i for i, v in enumerate(nid.tolist())}
    X = np.asarray(mesh["x0"], dtype=np.float64)
    return [{"node_id": int(n), "dof": str(d), "xyz": X[pos[int(n)]].tolist()} for n, d in supports]


def _support_ok(mesh: dict, sup) -> bool:
    from esl.mech import supports as msup
    try:
        sr = tg.support_check(mesh, sup)
    except EslError:
        return False
    return sr["rank"] >= 6 and sr["sigma_ratio"] >= msup.DEGENERATE_RATIO


def transfer_supports(ref: list[dict], mesh: dict, region, tol: float) -> tuple[list, dict]:
    """LT-7 기준 d000 지지점(xyz) → 형상 영역 최근접 노드(동률 = 작은 인덱스), 같은 dof. 거리 > tol 또는 rank < 6 →
    영역 auto 3-2-1(fallback). 반환 (지지 [(node_id, dof)], {mode, max_dist_mm, reason?})."""
    X = np.asarray(mesh["x0"], dtype=np.float64)
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    rn = np.flatnonzero(region_nodes(mesh, region))
    sup, dmax = [], 0.0
    for s in ref:
        d = np.linalg.norm(X[rn] - np.asarray(s["xyz"], dtype=np.float64), axis=1)
        j = int(np.argmin(d))
        dmax = max(dmax, float(d[j]))
        sup.append((int(nid[rn[j]]), str(s["dof"])))
    if dmax > float(tol):
        reason = f"distance {dmax:.3g} mm > {float(tol):g} mm"
    elif not _support_ok(mesh, sup):
        reason = "rank < 6"
    else:
        return sup, {"mode": "transfer", "max_dist_mm": dmax}
    return auto_supports(mesh, region), {"mode": "fallback", "max_dist_mm": dmax, "reason": reason}

def a_direct_mesh(raw: dict, props: dict) -> dict:
    """참값 a_direct 용 A 메시(스터디 물성으로 덮어씀)."""
    ne = int(np.asarray(raw["elem_type"]).size)
    m = {k: np.asarray(raw[k]) for k in ("node_id", "x0", "elem_id", "elem_type", "conn")}
    m["elem_pid"] = np.asarray(raw.get("elem_pid", np.zeros(ne, np.int64)))
    m["thickness"] = np.full(ne, float(props["t"]))
    m["E"] = np.full(ne, float(props["E"]))
    m["nu"] = np.full(ne, float(props["nu"]))
    return m


# ====================================================================== W 저장
def save_work(path: str, Ws: dict, key: str, writer=None) -> str:
    """prep/shapes/<did>/transfer.npz: 키 = A 메시 sha 앞 16자(+ _elem·_nodes·_w·_dist), key = 대상 메시·영역·설정 해시."""
    from esl.doe.mesh_gmsh import save_npz_det
    arr = {"key": np.asarray(key)}
    for sha, W in Ws.items():
        arr.update({f"{sha}_elem": W["elem"], f"{sha}_nodes": W["nodes"], f"{sha}_w": W["w"], f"{sha}_dist": W["dist"],
                    f"{sha}_meta": np.asarray([W["newton_fallback_n"], W["max_dist_mm"], W["seconds"]], np.float64)})
    g = writer.guard if writer is not None else (lambda p: p)
    save_npz_det(g(path), arr)
    return path


def load_work(path: str, key: str) -> dict:
    """save_work 역(키 다르면 빈 dict — 다시 만듦)."""
    if not os.path.isfile(path):
        return {}
    with np.load(path, allow_pickle=False) as z:
        if "key" not in z.files or str(np.asarray(z["key"]).ravel()[0]) != key:
            return {}
        out = {}
        for k in z.files:
            if k.endswith("_elem"):
                sha = k[:-5]
                meta = z[f"{sha}_meta"]
                out[sha] = {"elem": z[k], "nodes": z[f"{sha}_nodes"], "w": z[f"{sha}_w"], "dist": z[f"{sha}_dist"],
                            "newton_fallback_n": int(meta[0]), "max_dist_mm": float(meta[1]), "seconds": float(meta[2])}
        return out


def work_key(t_mesh: dict, region, wcfg: dict, h: float, placement_sha: str = "global") -> str:
    h_ = hashlib.sha256(b"esl/lt_work/1\n")
    from esl.doe import load_transfer as ltm
    h_.update(ltm.mesh_sha(t_mesh).encode())
    h_.update(b"-" if region is None else np.packbits(np.asarray(region, bool)).tobytes())
    h_.update(repr((sorted((wcfg or {}).items()), float(h), placement_sha)).encode())
    return h_.hexdigest()
