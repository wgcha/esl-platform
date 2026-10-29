"""v0.8.0 검증 반영: 줄 길이 상한(줄바꿈 없는 거대 파일), /INISHE/EPSP_F NPT·NPG 상한, 숫자 의심 경고.

- rad·상태 파일 한 줄 > 상한 → RAD_PARSE_ERROR / STATE_PARSE_ERROR, 그 전까지만 읽음(메모리 ≈ 상한).
- include 스캐너는 오류 없이 그 파일만 건너뜀.
- NPT=40000(예전 int16 OverflowError) → STATE_PARSE_ERROR, 배열 int32.
- NaN·칸 폭 이상 → STATE_NUMBER_SUSPECT 경고(값 규칙 불변).
"""
import os
import subprocess
import sys

import numpy as np
import pytest

from esl.errors import EslError
from esl.rad import parse_rad, scan_include_refs
from esl.rad import parser as _p
from esl.rad import state as _st

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from test_state_parser import _sta_with  # noqa: E402

BIG = 200 * 1024 * 1024


def _huge(path, prefix: bytes = b""):
    """줄바꿈 없는 BIG 바이트 파일(앞 prefix + 0 바이트, 희소 파일이라 빠름)."""
    with open(path, "wb") as fh:
        fh.write(prefix)
        fh.truncate(BIG)
    return str(path)


def _rss_delta_mb(code: str) -> float:
    """새 파이썬 프로세스에서 code 실행 전후 최대 RSS 증가(MB, Linux ru_maxrss KB)."""
    prog = ("import resource, sys\n"
            "sys.path[:0] = " + repr([ROOT, os.path.join(ROOT, "backend"), os.path.join(ROOT, "worker")]) + "\n"
            "import esl.rad, esl.rad.parser, esl.rad.state\n"
            "r0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n" + code +
            "\nr1 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\nprint((r1 - r0) / 1024)\n")
    out = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr
    return float(out.stdout.strip().splitlines()[-1])


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="ru_maxrss 단위·희소 파일은 Linux 기준")


def test_huge_line_rad_is_rad_parse_error_with_bounded_memory(tmp_path):
    rad = _huge(tmp_path / "huge_0000.rad", b"#RADIOSS STARTER\n/BEGIN\n")
    with pytest.raises(EslError) as ei:
        parse_rad(rad, "plate")
    assert ei.value.code == "RAD_PARSE_ERROR" and "바이트를 넘음" in ei.value.message
    d = _rss_delta_mb(f"""
try:
    esl.rad.parse_rad({rad!r}, "plate")
except Exception as e:
    assert getattr(e, "code", "") == "RAD_PARSE_ERROR", e
""")
    assert d <= 1 + 24, d          # 상한 1 MB + 여유(예전 for/readline 은 +400 MB)


def test_huge_line_state_include_is_state_parse_error(tmp_path):
    p = _sta_with(tmp_path, ["        11         1         1 1.0000000000000E+00", " 1.0000000000000E-02"])
    _huge(tmp_path / "prev_0001.sta", b"#RADIOSS STATE FILE prev_0001.sta\n")
    with pytest.raises(EslError) as ei:
        parse_rad(p, "plate")
    assert ei.value.code == "STATE_PARSE_ERROR" and "prev_0001.sta" in ei.value.message
    # 상한을 설정으로 낮추면 그 값 기준
    with pytest.raises(EslError) as ei:
        parse_rad(p, "plate", max_line_bytes=4096)
    assert "4096 바이트" in ei.value.message
    d = _rss_delta_mb(f"""
try:
    esl.rad.parse_rad({str(p)!r}, "plate")
except Exception as e:
    assert getattr(e, "code", "") == "STATE_PARSE_ERROR", e
""")
    assert d <= 1 + 24, d


def test_include_scan_skips_huge_file_without_error(tmp_path):
    p = _sta_with(tmp_path, ["        11         1         1 1.0000000000000E+00", " 1.0000000000000E-02"])
    _huge(tmp_path / "prev_0001.sta")
    refs = scan_include_refs(str(p))
    assert [os.path.basename(r["path"]) for r in refs] == ["prev_0001.sta"] and refs[0]["found"]
    assert not _st.read_state_header(str(tmp_path / "prev_0001.sta"))
    d = _rss_delta_mb(f"esl.rad.scan_include_refs({str(p)!r}); esl.rad.state.read_state_header("
                      f"{str(tmp_path / 'prev_0001.sta')!r})")
    assert d <= 1 + 24, d


def test_normal_files_unchanged_by_line_limit(tmp_path):
    rows = ["        11         1         4 1.0000000000000E+00", " 1.0000000000000E-02" * 4]
    p = _sta_with(tmp_path, rows)
    a = parse_rad(p, "plate")
    b = parse_rad(p, "plate", max_line_bytes=128)       # 이 모델의 가장 긴 줄(약 100자)보다 큼
    assert a.state["epsp"].agg["max"][0] == b.state["epsp"].agg["max"][0] == pytest.approx(0.01)
    assert np.array_equal(a.x0, b.x0) and a.state["warnings"] == b.state["warnings"]
    assert not any(w.startswith("STATE_NUMBER_SUSPECT") for w in a.state["warnings"])
    assert "nonfinite" not in a.state["parse"]


def test_config_optional_line_limit_key():
    import copy

    import yaml

    from esl import config as C
    assert _p.max_line_bytes_of({}) == _p.DEFAULT_MAX_LINE_BYTES
    assert _p.max_line_bytes_of({"rad_max_line_kb": 64}) == 64 * 1024
    base = yaml.safe_load(open(os.path.join(ROOT, "config", "esl.example.yaml"), encoding="utf-8"))
    plain = C.validate_settings(copy.deepcopy(base))
    assert "rad_max_line_kb" not in plain["case"] and "max_npt" not in plain["cumulative"]   # 주입 안 함(해시 불변)
    assert C.cumulative_settings(plain)["max_npt"] == 100 and C.cumulative_settings(plain)["max_npg"] == 64
    cfg = copy.deepcopy(base)
    cfg["case"]["rad_max_line_kb"] = 64
    cfg["cumulative"]["max_npt"] = 300
    v = C.validate_settings(cfg)
    assert C.cumulative_settings(v)["max_npt"] == 300
    cfg["case"]["rad_max_line_kb"] = 0
    with pytest.raises(EslError):
        C.validate_settings(cfg)


# ------------------------------------------------------------------ NPT·NPG 상한
def test_npt_overflow_is_state_parse_error_not_overflow(tmp_path):
    rows = ["        11     40000         4 1.0000000000000E+00", " 1.0000000000000E-02" * 5]
    with pytest.raises(EslError) as ei:
        parse_rad(_sta_with(tmp_path, rows), "plate")
    assert ei.value.code == "STATE_PARSE_ERROR" and "NPT=40000" in ei.value.message and "max_npt" in ei.value.message
    rows = ["        11         1        65 1.0000000000000E+00"]
    with pytest.raises(EslError) as ei:
        parse_rad(_sta_with(tmp_path, rows), "plate")
    assert "NPG=65" in ei.value.message
    # 설정으로 상한을 올리면 해석(배열 int32 — int16 이면 넘침)
    rows = ["        11       200         1 1.0000000000000E+00"] + [" 1.0000000000000E-02" * 5] * 40
    m = parse_rad(_sta_with(tmp_path, rows), "plate", state_max_npt=300)
    ep = m.state["epsp"]
    assert ep.npt.dtype == np.int32 and ep.npt[0] == 200 and ep.agg["max"][0] == pytest.approx(0.01)


def test_non_target_npt_overflow_is_skipped(tmp_path):
    rows = ["        99     40000         4 1.0000000000000E+00",
            "        11         1         1 1.0000000000000E+00", " 3.0000000000000E-02"]
    m = parse_rad(_sta_with(tmp_path, rows), "plate")
    assert m.state["epsp"].agg["max"][0] == pytest.approx(0.03)


# ------------------------------------------------------------------ 숫자 의심 경고
def test_number_suspect_warning_nan_and_width(tmp_path):
    rows = ["        11         1         4 1.0000000000000E+00",
            "                 nan 1.0000000000000E-02-2.0000000000000E-02 3.0000000000000E-02"]
    m = parse_rad(_sta_with(tmp_path, rows), "plate")
    st = m.state
    w = [x for x in st["warnings"] if x.startswith("STATE_NUMBER_SUSPECT")]
    assert len(w) == 1 and "비유한값(NaN·Inf) 1개" in w[0] and "칸 폭 이상" in w[0]
    assert st["parse"]["nonfinite"] == 1 and st["parse"]["width_suspect"] >= 1
    assert np.isnan(st["epsp"].agg["max"][0])            # 값 사용 규칙은 그대로(NaN 통과)
