"""V-CI-B1 골든 정규화: 비누적 씬 산출물을 시간·버전·경로를 지운 내용 지문으로 바꾼다.

- npz: 배열별 (dtype, shape, sha256(bytes)) — zip 시각과 무관.
- json: 시각 키·문자열, 버전 문자열, 실행 루트 경로를 지운 뒤 정렬 직렬화의 sha256.
- 그 외 텍스트(csv·inc·fem·html): 시각·버전·루트 경로 치환 후 sha256.
- run.json 은 config 스냅샷(설정 예시 파일 변경 영향)·이력·시각을 빼고 비교한다.
- v0.24.5(esl_validate_tiers.md §5-6, D-0.24.3-VAL-8 보충 선례): 판정 단계·MAC 의 의도 차이(05_val validation.json 새 키·
  옛 단일 기준 판정, validation.csv, 보고서 5절 판정 머리)는 ``tests/pipeline/vt_compat`` 로 v0.24.4 형식으로 되돌린 뒤 비교한다
  (보고서 = 되돌린 문서로 다시 그린 것). 나머지 값은 그대로.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys

import numpy as np

from esl import val_src as _vs

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))
import vt_compat as _vc  # noqa: E402

TS = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z?")
VER = re.compile(r"(?:esl|ESL)[ _-]?v?\d+\.\d+\.\d+|\bv?0\.\d+\.\d+\b")
TIME_KEYS = {"created_at", "started_at", "finished_at", "updated_at", "elapsed", "elapsed_s", "seconds",
             "esl_version", "version", "timing", "wall_s", "time_s"}
# v0.12.1(esl_strain_fallback.md §5): 기존 JSON 에 키 추가만 — 골든(v0.7.2) 비교에서는 뺀다(나머지 내용은 그대로 같아야 함)
ADDED_KEYS = {"strain_source", "strain_fallback"}
# v0.24.3(esl_validate_sources.md §4.5·§13): ④ 검증 출처별 — 새 파일(05_val/sources.json·05_val/<출처 dir>/)과 07_report 5절 끝
# 출처 표 블록(<!--val-src--> 표식)은 골든 비교에서 뺀다(기존 파일·나머지 내용은 그대로 같아야 함 — 같은 원칙)
ADDED_FILES = {f"05_val/{_vs.SOURCES_JSON}"}
ADDED_DIRS = tuple(f"05_val/{r['dir']}/" for r in _vs.VAL_PLAN if r["dir"])
ADDED_HTML = re.compile(r"<!--val-src-->.*?<!--/val-src-->", re.DOTALL)


def _text(s: str, root: str) -> str:
    s = s.replace(root, "<ROOT>").replace(root.replace("\\", "/"), "<ROOT>")
    s = TS.sub("<TS>", s)
    return VER.sub("<VER>", s)


def _clean(o, root):
    if isinstance(o, dict):
        return {k: _clean(v, root) for k, v in o.items()
                if k not in TIME_KEYS and k not in ADDED_KEYS and not k.endswith(("_seconds", "_s", "_mb", "mtime")) and not k.startswith("mem_")}
    if isinstance(o, list):
        return [_clean(v, root) for v in o]
    if isinstance(o, str):
        return _text(o, root)
    return o


def digest(out: str, root: str) -> dict:
    res: dict[str, object] = {}
    for base, dirs, files in os.walk(out):
        dirs[:] = sorted(d for d in dirs if d != "_backup")
        for f in sorted(files):
            p = os.path.join(base, f)
            rel = os.path.relpath(p, out).replace(os.sep, "/")
            if rel in ADDED_FILES or rel.startswith(ADDED_DIRS):
                continue
            if f.endswith(".npz"):
                with np.load(p, allow_pickle=False) as z:
                    res[rel] = {k: [str(z[k].dtype), list(z[k].shape),
                                    hashlib.sha256(np.ascontiguousarray(z[k]).tobytes()).hexdigest()[:16]]
                                for k in sorted(z.files)}
            elif f.endswith(".json"):
                with open(p, encoding="utf-8") as fh:
                    o = json.load(fh)
                if rel.startswith("05_val/") and f == "validation.json":
                    o = _vc.back_validation(o)
                if rel == "run.json":
                    for k in ("config", "history", "stages"):
                        o.pop(k, None)
                s = json.dumps(_clean(o, root), sort_keys=True, ensure_ascii=False)
                res[rel] = hashlib.sha256(s.encode()).hexdigest()[:16]
            else:
                with open(p, "rb") as fh:
                    b = fh.read()
                try:
                    t0 = b.decode("utf-8")
                    if f == "validation.csv":
                        t0 = _vc.back_csv(t0, p, out)
                    elif rel == "07_report/report.html":
                        t0 = _vc.back_report_html(out) or t0
                    t = _text(t0, root)
                    if f.endswith(".html"):
                        t = ADDED_HTML.sub("", t)
                        t = re.sub(r"\d+(?:\.\d+)?\s*(?:s|초)\b", "<DUR>", t)
                    res[rel] = hashlib.sha256(t.encode()).hexdigest()[:16]
                except UnicodeDecodeError:
                    res[rel] = hashlib.sha256(b).hexdigest()[:16]
    return res


def env_key() -> str:
    import scipy
    return f"{platform.system()}-{platform.machine()}-np{np.__version__}-sp{scipy.__version__}"
