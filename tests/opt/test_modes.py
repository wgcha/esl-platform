"""V-OR-4 (코어): 변형 모드 분류 — 굽힘 P2(s)·뒤틀림 s t·덴팅 국부 범프·0 변위(None)·혼합 경계, 기준값 경계,
rule_version 변경 시 auto 만 재계산·user 유지, 사용자 값 검사."""
import numpy as np
import pytest

import synth_opt as so
from esl.errors import EslError
from esl.library import normalize as nz
from esl.opt import modes, settings

MC = settings()["mode"]


def field(m, w):
    fr = nz.frame(m["x0"], None, m["conn"], m["elem_type"])
    return fr, np.asarray(w)[:, None] * np.asarray(fr["n"])[None, :]


def st(m):
    fr = nz.frame(m["x0"], None, m["conn"], m["elem_type"])
    loc = nz.local_coords(fr, m["x0"])
    return 2 * loc[:, 0] - 1, 2 * loc[:, 1] - 1


@pytest.fixture(scope="module")
def mesh():
    return so.plate(40, 26, Lx=400, Lz=260, n_tria_cols=2)


def cls(m, w, mc=MC):
    fr, u = field(m, w)
    return modes.classify(m["x0"], m["conn"], m["elem_type"], u, fr, mc)


def test_pure_modes(mesh):
    s, t = st(mesh)
    rigid = 0.3 + 0.2 * s - 0.1 * t                       # 강체·평면 성분은 에너지에서 제외
    r = cls(mesh, 0.5 * (3 * s ** 2 - 1) + rigid)
    assert r["mode"] == "bend" and r["metrics"]["bend"] > 0.99
    r = cls(mesh, 0.5 * (3 * t ** 2 - 1))
    assert r["mode"] == "bend"
    r = cls(mesh, s * t + rigid)
    assert r["mode"] == "twist" and r["metrics"]["twist"] > 0.99
    r = cls(mesh, np.exp(-((s - 0.4) ** 2 + (t + 0.3) ** 2) / 0.005))
    assert r["mode"] == "dent" and r["metrics"]["resid"] >= 0.5 and r["metrics"]["kappa"] >= 0.6
    r = cls(mesh, np.zeros_like(s))
    assert r["mode"] is None and r["warnings"]
    r = cls(mesh, rigid)                                   # 평면 성분뿐 → 분류 불가
    assert r["mode"] is None


def test_mixed_boundary_and_thresholds(mesh):
    s, t = st(mesh)
    p2 = 0.5 * (3 * s ** 2 - 1)
    # 굽힘·뒤틀림 에너지가 같아지는 혼합비 근처: 큰 쪽이 이김
    eb = cls(mesh, p2)["metrics"]["energy_tot"]
    et = cls(mesh, s * t)["metrics"]["energy_tot"]
    a = np.sqrt(et / eb)                                   # a·P2 와 s t 의 에너지 같음
    assert cls(mesh, 1.05 * a * p2 + s * t)["mode"] == "bend"
    assert cls(mesh, 0.95 * a * p2 + s * t)["mode"] == "twist"
    # 덴팅 기준 경계: 같은 범프+굽힘 장, dent_resid_min 을 실제 resid 위/아래로
    w = np.exp(-((s - 0.4) ** 2 + (t + 0.3) ** 2) / 0.005) + 0.05 * p2
    base = cls(mesh, w)
    res = base["metrics"]["resid"]
    assert cls(mesh, w, {**MC, "dent_resid_min": res - 1e-6})["mode"] == "dent"
    assert cls(mesh, w, {**MC, "dent_resid_min": res + 1e-6})["mode"] in ("bend", "twist")
    k = base["metrics"]["kappa"]
    assert cls(mesh, w, {**MC, "dent_resid_min": 0.0, "dent_conc_min": k + 1e-6})["mode"] != "dent"


def test_record_refresh_keeps_user(mesh):
    s, t = st(mesh)
    auto = cls(mesh, s * t)
    dm = modes.record(auto)
    assert dm["auto"] == "twist" and modes.effective(dm) == "twist"
    dm = modes.set_user(dm, "bend", "차완기", "2026-10-28T00:00:00Z")
    assert modes.effective(dm) == "bend"
    mc2 = {**MC, "rule_version": 2}
    assert modes.needs_refresh(dm, mc2) and not modes.needs_refresh(dm, MC)
    new = modes.refresh(dm, cls(mesh, 0.5 * (3 * s ** 2 - 1), mc2))
    assert new["auto"] == "bend" and new["user"] == "bend" and new["user_by"] == "차완기" and new["rule_version"] == 2
    back = modes.set_user(new, None, "x", "y")
    assert back["user"] is None and back["user_by"] is None and modes.effective(back) == "bend"
    with pytest.raises(EslError) as ei:
        modes.set_user(dm, "warp", None, None)
    assert ei.value.code == "INVALID_PARAMS"


def test_classify_from_solved_esl(mesh):
    """실제 쉘 해 u_rel(3-2-1) 에서도 굽힘·뒤틀림 하중은 그대로 분류(라이브러리 등록 경로). 자유판 3-2-1 의 국부
    하중은 관성 평형 때문에 전체 굽힘이 지배적이라 덴팅은 위 합성 장으로 시험한다."""
    m = so.plate(30, 20, Lx=400, Lz=260)
    sup = so.supports_321(m)
    for kind, want in (("bend", "bend"), ("twist", "twist")):
        e = so.FakeEntry(kind, m, so.load(m, kind), sup)
        r = modes.classify_raw(e.raw, e.meta["frame"], MC)
        assert r["mode"] == want, (kind, r["metrics"])
