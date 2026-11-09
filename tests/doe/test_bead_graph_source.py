"""V-BG-4 (b, e) mesh source: H5 (gmsh STEP mesh) written as .rad + #include .inc and read back with the esl reader ->
same labels after element-ID mapping, same segment / junction / zone kinds."""
import os

import numpy as np
from _bg_util import CFG, bgr, esl_mesh  # noqa: F401
from beadgraph.testing import conformance as cf


def test_rad_include_roundtrip(tmp_path):
    import synth_doe as sd

    from esl.rad.parser import parse_rad_part
    fx = cf.load_fixture("h5")
    mesh = esl_mesh(fx)
    full = tmp_path / "full.rad"
    sd.write_mesh_rad(str(full), mesh)
    txt = full.read_text(encoding="latin-1").splitlines(keepends=True)
    i = next(k for k, ln in enumerate(txt) if ln.startswith("/NODE"))
    j = max(k for k, ln in enumerate(txt) if ln.startswith("/END"))
    (tmp_path / "inc").mkdir()
    (tmp_path / "inc" / "part.inc").write_text("".join(txt[i:j]), encoding="latin-1")
    (tmp_path / "main.rad").write_text("".join(txt[:i]) + "#include inc/part.inc\n" + "".join(txt[j:]),
                                       encoding="latin-1")
    rm = parse_rad_part(str(tmp_path / "main.rad"), sd.PART_ID, need_props=False, max_include_depth=4)
    X = np.asarray(rm.x0, float)
    C = np.asarray(rm.conn, np.int64)
    et = np.asarray(rm.elem_type).astype(int)
    C = np.where(np.arange(4)[None, :] < et[:, None], C, -1)
    import beadgraph
    g0, l0 = beadgraph.classify(fx["x0"], fx["conn"], fx["fixed"], bgr.graph_cfg(CFG))
    g1, l1 = beadgraph.classify(X, C, None, bgr.graph_cfg(CFG))
    # element mapping by element ID (fixture element i = ID i + 1)
    perm = np.asarray(rm.elem_id, np.int64) - 1
    assert cf.compare_labels(l0, l1, perm) == []
    assert cf._kinds(g0) == cf._kinds(g1)
    assert os.path.getsize(tmp_path / "inc" / "part.inc") > 0
