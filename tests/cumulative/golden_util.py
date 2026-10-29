"""V-CI-B1 골든 정규화: 비누적 씬 산출물을 시간·버전·경로를 지운 내용 지문으로 바꾼다.

- npz: 배열별 (dtype, shape, sha256(bytes)) — zip 시각과 무관.
- json: 시각 키·문자열, 버전 문자열, 실행 루트 경로를 지운 뒤 정렬 직렬화의 sha256.
- 그 외 텍스트(csv·inc·fem·html): 시각·버전·루트 경로 치환 후 sha256.
- run.json 은 config 스냅샷(설정 예시 파일 변경 영향)·이력·시각을 빼고 비교한다.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re

import numpy as np

TS = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z?")
VER = re.compile(r"(?:esl|ESL)[ _-]?v?\d+\.\d+\.\d+|\bv?0\.\d+\.\d+\b")
TIME_KEYS = {"created_at", "started_at", "finished_at", "updated_at", "elapsed", "elapsed_s", "seconds",
             "esl_version", "version", "timing", "wall_s", "time_s"}


def _text(s: str, root: str) -> str:
    s = s.replace(root, "<ROOT>").replace(root.replace("\\", "/"), "<ROOT>")
    s = TS.sub("<TS>", s)
    return VER.sub("<VER>", s)


def _clean(o, root):
    if isinstance(o, dict):
        return {k: _clean(v, root) for k, v in o.items()
                if k not in TIME_KEYS and not k.endswith(("_seconds", "_s", "_mb", "mtime")) and not k.startswith("mem_")}
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
            if f.endswith(".npz"):
                with np.load(p, allow_pickle=False) as z:
                    res[rel] = {k: [str(z[k].dtype), list(z[k].shape),
                                    hashlib.sha256(np.ascontiguousarray(z[k]).tobytes()).hexdigest()[:16]]
                                for k in sorted(z.files)}
            elif f.endswith(".json"):
                with open(p, encoding="utf-8") as fh:
                    o = json.load(fh)
                if rel == "run.json":
                    for k in ("config", "history", "stages"):
                        o.pop(k, None)
                s = json.dumps(_clean(o, root), sort_keys=True, ensure_ascii=False)
                res[rel] = hashlib.sha256(s.encode()).hexdigest()[:16]
            else:
                with open(p, "rb") as fh:
                    b = fh.read()
                try:
                    t = _text(b.decode("utf-8"), root)
                    if f.endswith(".html"):
                        t = re.sub(r"\d+(?:\.\d+)?\s*(?:s|초)\b", "<DUR>", t)
                    res[rel] = hashlib.sha256(t.encode()).hexdigest()[:16]
                except UnicodeDecodeError:
                    res[rel] = hashlib.sha256(b).hexdigest()[:16]
    return res


def env_key() -> str:
    import scipy
    return f"{platform.system()}-{platform.machine()}-np{np.__version__}-sp{scipy.__version__}"
