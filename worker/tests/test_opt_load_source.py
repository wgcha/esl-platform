"""v0.24.4 P3 W3 — 비드 최적화 하중 출처 주입(계약 esl_jig_case.md §9·V-0244-JIG-14, esl_validate_sources.md V-0244-VAL-8).

코어 A3 의 ``esl.library.source_load.find(key, meta, raw) -> (dir, doc, f, bc, why)`` 는 가짜 모듈(monkeypatch)로 대신한다 —
형식은 계약 P3 절대로 가정. 코어 ``esl.opt`` 단계(opt_prep·opt_load)는 실제 코드, 입력은 합성 판·항목 폴더.
DB·워커 프로세스 없음(코어 어댑터 단계 함수를 직접 부른다).
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from esl_worker import core_adapter as ca
from test_opt_e2e import PART, plate, write_case_rad, write_entry

pytestmark = pytest.mark.filterwarnings("ignore")


# ---------------------------------------------------------------- 가짜 A3 source_load
class FakeSource:
    """key → 항목별 (f 배율·doc·bc) 규칙. find 호출을 기록한다."""

    def __init__(self, mesh, rules):
        self.mesh, self.rules, self.calls = mesh, rules, []

    def module(self):
        m = types.ModuleType("esl.library.source_load")
        m.find = self.find
        return m

    def find(self, key, meta, raw):
        self.calls.append(key)
        r = self.rules.get(key)
        if r is None:
            return None, None, None, None, f"{key.upper()}_NOT_FOUND: 시험용 — 결과 없음"
        f = np.asarray(raw["f"], dtype=np.float64) * float(r.get("scale", 1.0))
        return f"/fake/04_esl/{meta['entry_id']}", r.get("doc"), f, r.get("bc"), ""


def jig_bc(mesh, nodes, *, kind=1, val=0.0):
    nid = np.asarray(mesh["node_id"])
    sel = np.repeat(np.asarray(nodes, dtype=np.int64), 3)
    dirs = np.tile(np.eye(3), (len(nodes), 1))
    return {"bc_node": sel, "bc_dir": dirs, "bc_val": np.full(sel.size, val), "bc_kind": np.full(sel.size, kind, np.int8),
            "sp_node": np.zeros(0, np.int64), "sp_dir": np.zeros((0, 3)), "sp_k": np.zeros(0), "sp_g": np.zeros(0)}


def tie_nodes(mesh):
    """판의 네 모서리 근처 + 중앙 노드(강체 6모드를 구속)."""
    nid = mesh["node_id"]
    X = mesh["x0"]
    idx = [int(np.argmin(np.linalg.norm(X - c, axis=1))) for c in
           (X.min(0), np.array([X[:, 0].max(), 0, X[:, 2].min()]), np.array([X[:, 0].min(), 0, X[:, 2].max()]), X.max(0))]
    return [int(nid[i]) for i in idx]


# ---------------------------------------------------------------- 환경
@pytest.fixture()
def world(tmp_path, monkeypatch):
    mesh = plate()
    esl_root = tmp_path / "esl"
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    ids = ["Ea", "Eb"]
    for i, (eid, kind) in enumerate(zip(ids, ("bend", "twist"))):
        write_entry(esl_root, eid, mesh, kind, 2.0 - i, scene=i + 1)
    rad = inputs / "c1_0000.rad"
    write_case_rad(rad, mesh)
    entries = [{"id": e, "dir": str(esl_root / "_library" / "entries" / e), "mode": None, "inch": 55} for e in ids]
    return {"mesh": mesh, "tmp": tmp_path, "esl_root": esl_root, "rad": rad, "entries": entries, "ids": ids,
            "monkeypatch": monkeypatch}


def lib_of(w, key=None, *, scenario="S1", **extra):
    L = {"run_id": "r1", "scenario": scenario, "title": None, "cfg": {}, "core": {}, "library": {},
         "lib_root": str(w["esl_root"] / "_library"), "templates_root": str(w["tmp"] / "tpl"), "entries": w["entries"],
         "base": {"entry_id": w["ids"][0], "rad_path": str(w["rad"]), "part_title": PART}, "template": None,
         "design": {}, "options": {"load_strategy": "A"}, "warnings": []}
    if key is not None:
        L["load_source"] = key
    L.update(extra)
    return L


def run_stages(w, L, out: Path, stages=("opt_prep", "opt_load")):
    out.mkdir(parents=True, exist_ok=True)
    echo = []
    for st in stages:
        ca.run_opt_stage({"stage": st, "out": str(out), "lib": L}, echo.append)
    return echo


def install(w, rules):
    fake = FakeSource(w["mesh"], rules)
    w["monkeypatch"].setitem(sys.modules, "esl.library.source_load", fake.module())
    return fake


def loads(out: Path):
    z = np.load(out / "load" / "loads.npz")
    return {k: z[k] for k in z.files}


def target_json(out: Path):
    return json.loads((out / "target" / "target.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 시험
def test_no_load_source_is_unchanged_and_full_equals_default(world):
    """load_source 없음 = 지금 동작(출처 모듈을 부르지 않음·target 에 출처 표식 없음), 'full'(legacy) 도 같은 하중."""
    fake = install(world, {})
    a, b = world["tmp"] / "a", world["tmp"] / "b"
    run_stages(world, lib_of(world), a)
    run_stages(world, lib_of(world, "full"), b)
    assert fake.calls == []                                   # legacy 열 = 항목 자신의 f — find 를 부르지 않음
    assert "load_source" not in target_json(a)["source"] and "load_source" not in json.loads(
        (a / "target" / "prep.json").read_text(encoding="utf-8"))["summary"]
    assert "load_source" not in json.loads((a / "load" / "load.json").read_text(encoding="utf-8"))["summary"]
    la, lb = loads(a), loads(b)
    assert set(la) == set(lb) and all(np.array_equal(la[k], lb[k]) for k in la)
    assert (a / "load" / "selection.json").read_bytes() == (b / "load" / "selection.json").read_bytes()
    assert target_json(b)["source"]["load_source"] == {"key": "full"}
    assert target_json(a)["supports"] == target_json(b)["supports"]


def test_s1_nodal_source_replaces_load_keeps_321(world):
    fake = install(world, {"bforce": {"scale": 3.0}})
    a, b = world["tmp"] / "a", world["tmp"] / "b"
    run_stages(world, lib_of(world), a)
    run_stages(world, lib_of(world, "bforce"), b)
    assert set(fake.calls) == {"bforce"} and len(fake.calls) >= 2
    assert target_json(b)["supports"] == target_json(a)["supports"]       # 비지그 출처 = 기준 ESL 3-2-1 그대로
    la, lb = loads(a), loads(b)
    labs = [k for k in la if k.startswith("f_")]
    assert labs and sorted(labs) == sorted(k for k in lb if k.startswith("f_"))
    # 선정(MAC 병합)으로 라벨이 같다는 가정 없이: 라벨이 같으면 3배, 아니면 노름 합이 3배
    na = sum(float(np.linalg.norm(la[k])) for k in labs)
    nb = sum(float(np.linalg.norm(lb[k])) for k in labs)
    assert nb == pytest.approx(3.0 * na, rel=1e-9)
    lj = json.loads((b / "load" / "load.json").read_text(encoding="utf-8"))["summary"]["load_source"]
    assert lj["key"] == "bforce" and set(lj["entries"]) == set(world["ids"])
    assert lj["entries"]["Ea"] == "/fake/04_esl/Ea"
    pj = json.loads((b / "target" / "prep.json").read_text(encoding="utf-8"))["summary"]
    assert pj["load_source"] == {"key": "bforce"}


def test_s1_jig_fixed_translation_injects_supports(world):
    nodes = tie_nodes(world["mesh"])
    bc = jig_bc(world["mesh"], nodes)
    doc = {"method": "fixed", "tie_dofs": "translation", "status": "ok"}
    fake = install(world, {"jig": {"scale": 2.0, "doc": doc, "bc": bc}})
    out = world["tmp"] / "j"
    echo = run_stages(world, lib_of(world, "jig"), out)
    assert fake.calls.count("jig") >= 4                       # prep(항목마다) + load(항목마다)
    t = target_json(out)
    assert [(s["node_id"], s["dof"]) for s in t["supports"]] == [(n, "123") for n in sorted(nodes)]
    assert t["source"]["load_source"] == {"key": "jig", "support": "jig"}
    assert any("지그 지지 4개" in x for x in echo)
    # 덱까지: 같은 지지가 SPC1 카드(원본 한 곳 = Target.supports)
    ca.run_opt_stage({"stage": "opt_deck", "out": str(out), "lib": lib_of(world, "jig")}, lambda _m: None)
    deck = "\n".join(p.read_text() for p in (out / "deck").glob("*") if p.is_file())
    spc = sorted(int(x.split(",")[3]) for x in deck.splitlines() if x.startswith("SPC1,") and x.split(",")[2] == "123")
    assert spc == sorted(nodes)                                   # 선정 C·덱 SPC1 = 같은 지지(Target.supports 한 곳)
    assert not any(x.startswith("SPC1,") and x.split(",")[2] not in ("123",) for x in deck.splitlines())


@pytest.mark.parametrize("doc", [
    {"method": "fixed", "tie_dofs": "normal"},            # normal 국부 구속
    {"method": "prescribed", "tie_dofs": "translation"},  # 강제 변위
    {"method": "spring", "tie_dofs": "translation"},      # 스프링
    {"method": "nope", "tie_dofs": "translation"},
])
def test_s1_jig_unsupported_kinds_422(world, doc):
    install(world, {"jig": {"doc": doc, "bc": jig_bc(world["mesh"], tie_nodes(world["mesh"]))}})
    with pytest.raises(ca.CoreError) as ei:
        run_stages(world, lib_of(world, "jig"), world["tmp"] / "x", stages=("opt_prep",))
    assert ei.value.code == "LOAD_SOURCE_UNSUPPORTED"


def test_jig_support_reason_columns_only():
    ok = ca.jig_support_reason({"method": "fixed", "tie_dofs": "translation"})
    assert ok is None
    for d in ({"method": "fixed", "tie_dofs": "normal"}, {"method": "prescribed", "tie_dofs": "translation"},
              {"method": "spring", "tie_dofs": "translation"}, {}, None):
        assert ca.jig_support_reason(d)


def test_jig_supports_must_agree_across_entries(world):
    nodes = tie_nodes(world["mesh"])
    other = list(reversed(nodes))[:3] + [nodes[0] + 1]
    doc = {"method": "fixed", "tie_dofs": "translation"}
    fake = install(world, {})
    seq = [jig_bc(world["mesh"], nodes), jig_bc(world["mesh"], other)]

    def find(key, meta, raw):
        i = 0 if meta["entry_id"] == "Ea" else 1
        return "/d", doc, np.asarray(raw["f"], float), seq[i], ""
    sys.modules["esl.library.source_load"].find = find
    with pytest.raises(ca.CoreError) as ei:
        run_stages(world, lib_of(world, "jig"), world["tmp"] / "x", stages=("opt_prep",))
    assert ei.value.code == "LOAD_SOURCE_UNSUPPORTED" and "지지가 다릅니다" in ei.value.message
    assert fake.calls == []


def test_jig_degenerate_support_rejected(world):
    n0 = int(world["mesh"]["node_id"][0])
    doc = {"method": "fixed", "tie_dofs": "translation"}
    install(world, {"jig": {"doc": doc, "bc": jig_bc(world["mesh"], [n0, n0 + 1])}})
    with pytest.raises(ca.CoreError) as ei:
        run_stages(world, lib_of(world, "jig"), world["tmp"] / "x", stages=("opt_prep",))
    assert ei.value.code == "SUPPORT_DEGENERATE"


def test_source_without_load_is_unavailable(world):
    install(world, {})                                         # find → f None
    out = world["tmp"] / "u"
    with pytest.raises(ca.CoreError) as ei:
        run_stages(world, lib_of(world, "bforce"), out)
    assert ei.value.code == "LOAD_SOURCE_UNAVAILABLE" and "BFORCE_NOT_FOUND" in ei.value.message
    with pytest.raises(ca.CoreError) as ei:                    # 지그 계열은 prep 에서 먼저(지지를 읽어야 하므로)
        run_stages(world, lib_of(world, "jig"), world["tmp"] / "u2", stages=("opt_prep",))
    assert ei.value.code == "LOAD_SOURCE_UNAVAILABLE"


def test_unknown_source_key(world):
    install(world, {})
    with pytest.raises(ca.CoreError) as ei:
        run_stages(world, lib_of(world, "nope"), world["tmp"] / "k", stages=("opt_prep",))
    assert ei.value.code == "INPUT_INVALID"


# ---------------------------------------------------------------- S2(템플릿·셀 매핑)
def s2_lib(w, key):
    from esl.opt import target as tg
    from esl.library import _util as U

    arrs, meta = tg.build_template(w["mesh"])
    d = w["tmp"] / "tpl" / "T1"
    d.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(d / "template.npz", **{k: np.asarray(v) for k, v in arrs.items()})
    (d / "template.json").write_text(json.dumps(U.jsonable(meta)), encoding="utf-8")
    fr = meta["frame"]
    ents = [{**e, "L_xi": fr["L_xi"], "L_eta": fr["L_eta"], "grid": (24, 14)} for e in w["entries"]]
    tpl = {"id": "T1", "dir": str(d), "inch": 55, "L_xi": fr["L_xi"], "L_eta": fr["L_eta"], "file_name": "t.fem",
           "format": "fem", "sha256": "0" * 64}
    return lib_of(w, key, scenario="S2", entries=ents, base=None, template=tpl)


def test_s2_nodal_source_regenerates_cell_summary(world):
    fake = install(world, {"bforce": {"scale": 3.0}})
    a, b = world["tmp"] / "a", world["tmp"] / "b"
    run_stages(world, s2_lib(world, None), a)
    run_stages(world, s2_lib(world, "bforce"), b)
    assert set(fake.calls) == {"bforce"} and len(fake.calls) >= 2
    la, lb = loads(a), loads(b)
    labs = [k for k in la if k.startswith("f_")]
    na = sum(float(np.linalg.norm(la[k])) for k in labs)
    nb = sum(float(np.linalg.norm(lb[k])) for k in labs)
    assert nb == pytest.approx(3.0 * na, rel=1e-6)           # 셀 합력·합모멘트가 3배 → 매핑 하중도 3배(선형)
    assert [(s["node_id"], s["dof"]) for s in target_json(b)["supports"]] == \
        [(s["node_id"], s["dof"]) for s in target_json(a)["supports"]]


def test_s2_jig_source_unsupported(world):
    doc = {"method": "fixed", "tie_dofs": "translation"}
    install(world, {"jig": {"doc": doc, "bc": jig_bc(world["mesh"], tie_nodes(world["mesh"]))}})
    with pytest.raises(ca.CoreError) as ei:
        run_stages(world, s2_lib(world, "jig"), world["tmp"] / "s", stages=("opt_prep",))
    assert ei.value.code == "LOAD_SOURCE_UNSUPPORTED"


def test_worker_jig_support_rule_is_the_core_function(world):
    """통합 D-0.24.4-JIG: 워커 지그 지지 규칙 = 코어 esl.opt.target 한 곳(core_adapter 는 위임) — 결과·오류 코드 일치."""
    import esl.opt.target as tg
    from esl.errors import EslError

    nodes = tie_nodes(world["mesh"])
    cases = [
        ({"method": "fixed", "tie_dofs": "translation"}, jig_bc(world["mesh"], nodes)),
        ({"method": "fixed", "tie_dofs": "normal"}, jig_bc(world["mesh"], nodes)),
        ({"method": "spring", "tie_dofs": "translation"}, jig_bc(world["mesh"], nodes)),
        ({"method": "fixed", "tie_dofs": "translation"}, jig_bc(world["mesh"], nodes, val=0.5)),
        ({"method": "fixed", "tie_dofs": "translation"}, None),
        (None, None),
    ]
    for doc, bc in cases:
        assert ca.jig_support_reason(doc) == tg.jig_support_reason(doc)
        try:
            want = ("ok", tg.jig_supports(doc, bc))
        except EslError as exc:
            want = ("err", exc.code)
        try:
            got = ("ok", ca.opt_jig_supports(doc, bc))
        except ca.CoreError as exc:
            got = ("err", exc.code)
        assert got == want
