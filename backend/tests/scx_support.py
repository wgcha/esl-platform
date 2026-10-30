"""v0.11.0 SCX 릴레이 시험 공용(계약 esl_scx_relay.md §14): 가짜 릴레이(backend/tests/scx/fake_scx_relay.py — physicsai 사본) +
SCX 설정 dict + 드라이브 합성 모델(rad·include·엔진·h3d). backend/tests/scx·worker/tests 가 같이 쓴다."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from esl_test_support import make_settings_dict

HERE = Path(__file__).resolve().parent
FAKE = HERE / "scx" / "fake_scx_relay.py"
ROOT_REL = "share/drop"


def load_fake():
    name = "esl_fake_scx_relay"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, FAKE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def start_relay(drive: Path):
    return load_fake().FakeRelay(drive).start()


def scx_settings(base: Path, relay, **over: Any) -> dict[str, Any]:
    """기능 A 를 켠 설정: upload_root, hpc.scx(가짜 릴레이·비밀 파일), scx_drive(루트 drop = share/drop 모든 프로젝트,
    p2only = share/p2 프로젝트 p-2 만), 짧은 재시도 대기."""
    d = make_settings_dict(base, ui={"browse_page_max": 50})
    d["storage"]["upload_root"] = str(base / "esl-input")
    d["upload"] = {"chunk_mb": 1, "max_file_bytes": 30_000_000, "max_upload_bytes": 50_000_000, "min_free_gb": 0,
                   "max_concurrent_per_user": 4}
    sec = relay.write_secret(base / "secrets" / "scx_relay_key")
    m = relay.config_mapping(str(sec))
    m.update(client_name="esl", drive_base="~/esl", health_ttl_s=0, http_timeout_s=5, transfer_timeout_s=20)
    d["hpc"] = {"mode": "scx", "scx": m}            # physicsai 블록 그대로(hpc.mode 등 다른 키는 무시)
    d["scx_drive"] = {"enabled": True, "file_retries": 2, "retry_wait_s": 0,
                      "roots": [{"key": "drop", "label": "낙하해석 공유", "rel": ROOT_REL},
                                {"key": "p2only", "label": "브래킷 전용", "rel": "share/p2", "projects": ["p-2"]}]}
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            d[k] = {**d[k], **v}
        else:
            d[k] = v
    return d


def mini_rad(includes: list[str] | None = None) -> bytes:
    """2×2 판 rad(파트 7 'Chassis rear') + /END 앞 #include 줄들."""
    from esl.rad import write_rad

    xs = np.array([[x, y, 0.0] for x in range(3) for y in range(3)], float) * 10.0
    conn = np.array([[1, 4, 5, 2], [2, 5, 6, 3], [4, 7, 8, 5], [5, 8, 9, 6]], dtype=np.int64)
    with tempfile.TemporaryDirectory() as td:
        p = write_rad(os.path.join(td, "m_0000.rad"), np.arange(1, 10), xs, np.arange(101, 105),
                      np.full(4, 4, np.int8), conn, 7, "Chassis rear", 70, 2.0, 700, 2.1e5, 0.3)
        lines = Path(p).read_text().splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith("/END"))
    for inc in reversed(includes or []):
        lines.insert(i, f"#include {inc}")
    return ("\n".join(lines) + "\n").encode()


H3D_BYTES = b"HYPER3D " + bytes(range(256)) * 4096       # ≈ 1 MB


def put(relay, rel: str, data: bytes) -> Path:
    p = relay.drive_file(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def build_model(relay, *, extra_includes: list[str] | None = None, engine: bool = True, h3d: bytes = H3D_BYTES) -> dict[str, Any]:
    """share/drop/A/model/ref_0000.rad(+ ../inc/part.inc → deep.inc, sub/b.inc) + ref_0001.rad(엔진) + share/drop/A/res/ref.h3d."""
    incs = ["../inc/part.inc", "sub/b.inc", *(extra_includes or [])]
    files = {
        f"{ROOT_REL}/A/model/ref_0000.rad": mini_rad(incs),
        f"{ROOT_REL}/A/inc/part.inc": b"# part include\n#include deep.inc\n",
        f"{ROOT_REL}/A/inc/deep.inc": b"# deep include (src folder relative)\n",
        f"{ROOT_REL}/A/model/sub/b.inc": b"# b include\n",
        f"{ROOT_REL}/A/res/ref.h3d": h3d,
    }
    if engine:
        files[f"{ROOT_REL}/A/model/ref_0001.rad"] = b"/RUN/ref/1\n0.01\n/END\n"
    for k, v in files.items():
        put(relay, k, v)
    return {"rad": "A/model/ref_0000.rad", "h3d": "A/res/ref.h3d", "files": files,
            "sha": {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}}
