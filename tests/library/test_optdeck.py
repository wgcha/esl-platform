"""P2 §4 OptiStruct DTPG 덱: 소형 골든 + 구조 검사(FORCE 합 = 하중, 비설계 PSHELL 제외, minmax/weighted, 고정형식)."""
import os

import numpy as np
import pytest

from esl.errors import EslError
from esl.library import optdeck as od

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
UPDATE = os.environ.get("ESL_UPDATE_GOLDEN") == "1"


def small_mesh():
    """3×2 판(가로 X, 세로 Z): 첫 열 TRIA 4개 + QUAD 4개, PID 70/71, 두께 2.0/2.5."""
    xs, zs = np.array([0.0, 10.0, 20.0, 30.0]), np.array([0.0, 10.0, 20.0])
    X0 = np.array([[x, 0.0, z] for x in xs for z in zs])
    nid = lambda i, j: i * 3 + j   # noqa: E731
    conn, et = [], []
    for i in range(3):
        for j in range(2):
            a, b, c, d = nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)
            if i == 0:
                conn += [[a, b, c, -1], [a, c, d, -1]]
                et += [3, 3]
            else:
                conn.append([a, b, c, d])
                et.append(4)
    conn = np.array(conn)
    ne = conn.shape[0]
    pid = np.where(np.arange(ne) < 6, 70, 71)
    return {"node_id": 101 + np.arange(12), "x0": X0, "elem_id": 1001 + np.arange(ne), "elem_type": np.array(et),
            "conn": conn, "elem_pid": pid, "thickness": np.where(pid == 70, 2.0, 2.5),
            "E": np.full(ne, 2.1e5), "nu": np.full(ne, 0.3)}


def load_cases():
    f1 = np.zeros((12, 3))
    f1[[0, 11], 1] = [5.0, -5.0]
    f1[[3, 8], 2] = [1.25, -1.25]
    f2 = np.zeros((12, 3))
    f2[[1, 10], 0] = [-2.0, 2.0]
    return [{"label": "REP1_Corner146", "entry_id": "Eaaa", "f": f1, "ref": 2.5},
            {"label": "REP2_Face3", "entry_id": "Ebbb", "f": f2}]


SUP = [(101, "123"), (110, "12"), (103, "2")]
DESIGN = {"nondesign_node_ids": [112], "nondesign_radius": 10.5, "id_offset": 500}


def _read(d, n):
    return open(os.path.join(d, n), encoding="ascii").read()


def test_golden_small_deck(tmp_path):
    s = od.write(small_mesh(), load_cases(), SUP, DESIGN, str(tmp_path))
    assert s["files"] == ["esl_bead.fem", "esl_loads.inc", "run_optistruct.bat", "README.txt"]
    for n in ("esl_bead.fem", "esl_loads.inc"):
        got = _read(tmp_path, n)
        gp = os.path.join(GOLDEN, "optdeck_small_" + n)
        if UPDATE:
            os.makedirs(GOLDEN, exist_ok=True)
            with open(gp, "w", encoding="ascii", newline="\n") as fh:
                fh.write(got)
        assert got == open(gp, encoding="ascii").read(), n
    bat = open(tmp_path / "run_optistruct.bat", "rb").read()
    assert b"\r\n" in bat and b"\n" not in bat.replace(b"\r\n", b"")
    assert b"%ALTAIR_HOME%\\hwsolvers\\scripts\\optistruct.bat" in bat and b'"esl_bead.fem" -nt 4 %*' in bat
    # 노드 112(30,0,20) 반경 10.5 → 노드 109·111·112 → 요소 1006·1007·1008 비설계
    assert s["n_design_elems"] == 5 and s["n_nondesign_elems"] == 3 and s["nondesign_reasons"]["by_radius"] == 3


def _cards(text):
    """자유형식 카드 → [(name, [fields...])] (연속 줄 '+,' 합침, 주석·case control 제외)."""
    out = []
    bulk = False
    for ln in text.splitlines():
        if ln.startswith("BEGIN BULK"):
            bulk = True
            continue
        if not bulk or ln.startswith("$") or not ln.strip():
            continue
        parts = ln.split(",")
        if parts[0] == "+":
            out[-1][1].extend(parts[1:])
        else:
            out.append((parts[0], parts[1:]))
    return out


def test_deck_structure_free(tmp_path):
    m = small_mesh()
    lcs = load_cases()
    s = od.write(m, lcs, SUP, DESIGN, str(tmp_path))
    fem = _read(tmp_path, "esl_bead.fem")
    cards = _cards(fem) + _cards("BEGIN BULK\n" + _read(tmp_path, "esl_loads.inc"))
    ids = s["ids"]
    # FORCE 합 = 하중 (subcase 별)
    for k, sid in enumerate(ids["load_sids"]):
        F = np.zeros((12, 3))
        for name, f in cards:
            if name == "FORCE" and int(f[0]) == sid:
                assert f[2] == "0" and float(f[3]) == 1.0
                F[int(f[1]) - 101] = [float(x) for x in f[4:7]]
        assert np.allclose(F, lcs[k]["f"], rtol=1e-9, atol=0)
    dtpg = [f for n, f in cards if n == "DTPG"]
    assert len(dtpg) == 1
    f = dtpg[0]
    assert f[0] == str(ids["dtpg"]) and f[1] == "PSHELL"
    k = f.index("BEAD")
    pids = [int(x) for x in f[2:k] if x]
    assert pids == s["design_pids"] and not set(pids) & set(s["nondesign_pids"])
    assert f[k + 1:k + 6] == ["10.", "60.", "3.", "YES", "BC"]
    assert f[f.index("BOUNDS") + 1:] == ["0.", "1."]
    dob = [f for n, f in cards if n == "DOBJREF"]
    assert [(int(x[0]), int(x[1]), x[2], float(x[3]), int(x[4])) for x in dob] == \
        [(ids["dobjref"], ids["dresp_comp"], "", 2.5, 1), (ids["dobjref"], ids["dresp_comp"], "", 1.0, 2)]
    assert f"DESOBJ(MINMAX) = {ids['dobjref']}" in fem
    assert fem.index("DESOBJ") < fem.index("SUBCASE 1") < fem.index("BEGIN BULK")
    # 비설계 요소(노드 112 반경 10.5 안 노드 사용)는 비설계 PSHELL
    pmap = {p["pid"]: p for p in s["pshell_map"]}
    for n, f in cards:
        if n in ("CQUAD4", "CTRIA3"):
            nodes = [int(x) for x in f[2:]]
            near = any(np.linalg.norm(m["x0"][v - 101] - m["x0"][11]) <= 10.5 for v in nodes)
            assert pmap[int(f[1])]["design"] is (not near)
    # SPC1 3-2-1
    assert [(f[1], int(f[2])) for n, f in cards if n == "SPC1"] == [("123", 101), ("12", 110), ("2", 103)]


def test_weighted_beadfrac_and_fixed_format(tmp_path):
    lcs = load_cases()
    lcs[1]["weight"] = 2.0
    s = od.write(small_mesh(), lcs, SUP, {**DESIGN, "objective": "weighted", "beadfrac_max": 0.3,
                                          "card_format": "fixed"}, str(tmp_path))
    fem = _read(tmp_path, "esl_bead.fem")
    assert f"DESOBJ(MIN) = {s['ids']['dresp_comp']}" in fem and "WEIGHT = 2." in fem and "WEIGHT = 1." in fem
    assert f"DESGLB = {s['ids']['dconstr_beadfrac']}" in fem and not any(ln.startswith("DOBJREF") for ln in fem.splitlines())
    opt = [ln for ln in fem.splitlines() if ln[:8].strip() in ("DTPG", "DRESP1", "DCONSTR", "+")]
    assert opt and all("," not in ln and len(ln) <= 72 and (len(ln) - 8) % 8 == 0 for ln in opt)
    assert any(ln.startswith("DRESP1") and "WCOMP" in ln for ln in opt)
    bf = [ln for ln in opt if ln.startswith("DRESP1") and "BEADFRAC" in ln][0]
    fields = [bf[k:k + 8].strip() for k in range(0, len(bf), 8)]
    assert fields[:5] == ["DRESP1", str(s["ids"]["dresp_beadfrac"]), "BEADF", "BEADFRAC", "DTPG"]
    assert fields[8] == str(s["ids"]["dtpg"])


def test_rejects():
    m = small_mesh()
    with pytest.raises(EslError):
        od.write(m, load_cases(), SUP, {"bead": {"skip": "LOAD"}}, "unused")
    with pytest.raises(EslError):
        od.write(m, load_cases(), [(999, "123")], {}, "unused")
    with pytest.raises(EslError):
        od.write(m, load_cases(), SUP, {"nondesign_pids": [70, 71]}, "unused")
    with pytest.raises(EslError):
        od.card("DTPG", ["123456789"], "fixed")
    assert od.real(1.0) == "1." and od.real(1.5e-12, 8) == "1.5E-12" and od.real(-210000.0) == "-210000."
