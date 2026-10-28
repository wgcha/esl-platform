"""④ 3D 하중 보기 고정 fixture 생성(계약 esl_3d_load.md V-L3-5·6): tests/fixtures/view3d/small/.

작은 합성 판(접힌 플랜지 포함, 사각형 + 삼각형)으로 ``esl.view3d.build_view`` 를 돌려 프런트 시험이 쓰는 바이너리를 만든다.
결정적(난수 시드 고정, created_at 고정). 출력(< 100 KB): part.glb · part_lod.glb · values.bin · manifest.json ·
expected.json(Python 복원값: 위치 mm, p·fn·fmag·u) · inputs.json(입력 노드값 — 복원 오차 확인용).

사용: python scripts/gen_view3d_fixture.py [--check]   (--check: 파일이 최신이 아니면 종료코드 1)
`synth_mesh()` 는 백엔드·코어 시험이 공용으로 쓰는 합성 메시 생성기다.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from esl import view3d  # noqa: E402

OUT = os.path.join(ROOT, "tests", "fixtures", "view3d", "small")
CREATED_AT = "2026-10-28T00:00:00Z"
FIX_CFG = {"lod_min_nodes": 0, "lod_target_vertices": 40, "top_max": 100, "cluster_k_max": 5, "kmeans_max_iter": 50}


def synth_mesh(nx: int, ny: int, *, h: float = 2.0, bend: float = 0.0, tri_every: int = 0, seed: int = 1,
               load_frac: float = 1.0) -> dict[str, np.ndarray]:
    """nx×ny 칸 판 메시(요소 = 사각형, tri_every>0 이면 그 간격 칸마다 삼각형 2개로 쪼갬).

    bend ≠ 0 이면 x > 중앙 부분을 위로 꺾음(접힌 플랜지). node_id 는 섞은 값, F 는 자기평형(ΣF = 0), u_rel 은 작은 난수.
    반환 {node_id, x0, conn, elem_type, f, u_rel, nx, ny}. conn 은 노드 위치 인덱스(삼각형은 4열째 = 3열째).
    """
    rng = np.random.default_rng(seed)
    xs, ys = np.meshgrid(np.arange(nx + 1, dtype=float) * h, np.arange(ny + 1, dtype=float) * h, indexing="ij")
    zs = np.zeros_like(xs)
    if bend:
        zs = np.where(xs > (nx * h) / 2, (xs - (nx * h) / 2) * bend, 0.0)
    x0 = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1)
    idx = np.arange((nx + 1) * (ny + 1)).reshape(nx + 1, ny + 1)
    conn, et = [], []
    for i in range(nx):
        for j in range(ny):
            a, b, c, d = idx[i, j], idx[i + 1, j], idx[i + 1, j + 1], idx[i, j + 1]
            if tri_every and (i * ny + j) % tri_every == 0:
                conn += [[a, b, c, c], [a, c, d, d]]
                et += [3, 3]
            else:
                conn.append([a, b, c, d])
                et.append(4)
    n = x0.shape[0]
    f = rng.normal(size=(n, 3)) * 10.0
    loaded = rng.random(n) <= load_frac if load_frac < 1.0 else np.ones(n, bool)
    f[~loaded] = 0.0
    f[loaded] -= f[loaded].sum(axis=0) / loaded.sum()                                  # ΣF = 0 (자기평형)
    return {"node_id": (rng.permutation(n) + 100).astype(np.int64), "x0": x0, "conn": np.array(conn, np.int64),
            "elem_type": np.array(et, np.int64), "f": f, "u_rel": rng.normal(size=(n, 3)) * 1e-2, "nx": nx, "ny": ny}


def generate(out_dir: str) -> None:
    m = synth_mesh(11, 7, bend=0.4, tri_every=7, seed=7)
    sup = [{"node_id": int(m["node_id"][0]), "dof": "123"}, {"node_id": int(m["node_id"][8]), "dof": "13"},
           {"node_id": int(m["node_id"][20]), "dof": "3"}]
    os.makedirs(out_dir, exist_ok=True)
    man = view3d.build_view(out_dir, node_id=m["node_id"], x0=m["x0"], conn=m["conn"], elem_type=m["elem_type"],
                            f=m["f"], u_rel=m["u_rel"], supports=sup, cfg=FIX_CFG, key="fixture0000000001",
                            esl_run_id="fixture-run", created_at=CREATED_AT)
    n = int(man["n_nodes"])
    with open(os.path.join(out_dir, "values.bin"), "rb") as fh:
        vals = view3d.unpack_values(fh.read(), man["values"]["arrays"], n)
    js, binb = view3d.read_glb(os.path.join(out_dir, "part.glb"))
    node = js["nodes"][0]
    pos = np.frombuffer(binb, np.dtype("<i2"), count=n * 4).reshape(n, 4)[:, :3].astype(np.float64)
    xr = np.asarray(node["translation"]) + np.asarray(node["scale"]) * pos / 32767.0
    exp = {"n_nodes": n, "positions": xr.round(9).tolist(), "pa": vals["pa"].tolist(), "fn": vals["fn"].tolist(),
           "fmag": vals["fmag"].tolist(), "u": vals["u"].tolist()}
    with open(os.path.join(out_dir, "expected.json"), "w", encoding="utf-8") as fh:
        json.dump(exp, fh, separators=(",", ":"))
    inp = {"node_id": m["node_id"].tolist(), "x0": m["x0"].round(9).tolist(), "f": m["f"].tolist(),
           "u_rel": m["u_rel"].tolist()}
    with open(os.path.join(out_dir, "inputs.json"), "w", encoding="utf-8") as fh:
        json.dump(inp, fh, separators=(",", ":"))


def main(argv: list[str]) -> int:
    if "--check" in argv:
        with tempfile.TemporaryDirectory() as td:
            generate(td)
            bad = []
            for name in sorted(os.listdir(td)):
                a, b = os.path.join(td, name), os.path.join(OUT, name)
                if not os.path.isfile(b) or open(a, "rb").read() != open(b, "rb").read():
                    bad.append(name)
            if bad:
                print("fixture 가 최신이 아닙니다:", ", ".join(bad), "— python scripts/gen_view3d_fixture.py 로 다시 만드세요")
                return 1
        print("fixture 최신")
        return 0
    generate(OUT)
    print("wrote", OUT, sorted(os.listdir(OUT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
