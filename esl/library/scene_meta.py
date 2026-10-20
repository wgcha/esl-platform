"""씬 메타 파싱 (계약 esl_p2_library.md §2).

``parse(path, rules=None) -> dict``: 경로·파일명에서 설정 정규식(named group)으로 필드를 뽑고 ISTA 6 면 번호를 해석한다.

- 경로 구분자는 ``/`` 로 정규화한 뒤 ``rules["scene_regex"]``(문자열 또는 목록)의 각 정규식을 ``re.search`` 로 적용한다.
  필드별로 **처음 일치한 값**을 쓴다(디렉터리 규칙과 파일명 규칙을 따로 두어 한쪽이 실패해도 다른 쪽 필드는 살린다).
- ``inch`` 가 정규식에 없으면 ``model`` 에 ``rules["inch_regex"]``(기본: 앞 2~3자리 숫자)를 적용.
- 실패 필드는 ``None`` + ``warnings`` (선택 필드 ``rules["optional_fields"]`` 는 경고 없음).
- ISTA 6(``rules["ista6"]``, config/ista6.yaml): orient 숫자 = 충돌 면 번호. 면 1개 = Face, 2개 = Edge, 3개 = Corner.
  마주보는 면(1-3, 2-4, 5-6)이 함께 있거나 중복·범위 밖이면 경고. drop_type 과 면 수가 다르면 경고.

기본 규칙 예: ``F:/Hyper_work/VD_25y/75QN80H/75QN80H_v072_260511/CUMULATIVE/17_Corner_Drop_2nd_Scene10_Corner146_2nd_comp.h3d``
→ project VD_25y, model 75QN80H, inch 75, version v072, date 260511, scenario CUMULATIVE, seq 17, drop_type Corner,
round 2nd, scene 10, orient 146, suffix 2nd, variant comp.
"""
from __future__ import annotations

import re

import numpy as np

_ORD = r"\d+(?:st|nd|rd|th)"
DEFAULT_SCENE_REGEX = [
    # 디렉터리: <project>/<model>/<model>_<version>_<date>/<scenario>/<파일 또는 씬 폴더>
    r"(?:^|/)(?P<project>[^/]+)/(?P<model>[^/]+)/[^/]*?_(?P<version>v\d+)_(?P<date>\d{6})/(?P<scenario>[^/]+)/[^/]+",
    # 시나리오 폴더가 없는 경우: <project>/<model>/<model>_<version>_<date>/<파일>
    r"(?:^|/)(?P<project>[^/]+)/(?P<model>[^/]+)/[^/]*?_(?P<version>v\d+)_(?P<date>\d{6})/[^/]+$",
    # 파일명(=폴더명): <seq>_<drop_type>_Drop[_<round>]_Scene<scene>_<type><orient>[_<suffix>][_<variant>][.ext]
    (r"(?i)(?:^|/)(?P<seq>\d+)_(?P<drop_type>Corner|Edge|Face)_Drop(?:_(?P<round>" + _ORD + r"))?"
     r"_Scene(?P<scene>\d+)_(?P<orient_type>Corner|Edge|Face)(?P<orient>\d{1,3})"
     r"(?:_(?P<suffix>" + _ORD + r"))?(?:_(?P<variant>[A-Za-z][A-Za-z0-9]*))?(?=\.[A-Za-z0-9]+$|/|$)"),
]
DEFAULT_INCH_REGEX = r"^(?P<inch>\d{2,3})(?=\D|$)"
FIELDS = ("project", "model", "inch", "version", "date", "scenario", "seq", "drop_type", "round", "scene",
          "orient", "suffix", "variant")
DEFAULT_OPTIONAL = ("round", "suffix", "variant")
INT_FIELDS = ("inch", "seq", "scene")
DROP_CLASS = {1: "Face", 2: "Edge", 3: "Corner"}
DEFAULT_OPPOSITE = [[1, 3], [2, 4], [5, 6]]


def default_rules() -> dict:
    return {"scene_regex": list(DEFAULT_SCENE_REGEX), "inch_regex": DEFAULT_INCH_REGEX,
            "optional_fields": list(DEFAULT_OPTIONAL), "ista6": None}


def _canon_drop(v: str | None) -> str | None:
    if v is None:
        return None
    s = v.strip().lower()
    return {"corner": "Corner", "edge": "Edge", "face": "Face"}.get(s, v)


def _date_iso(d: str | None) -> str | None:
    """YYMMDD → 20YY-MM-DD (유효한 날짜일 때만)."""
    if not d or not re.fullmatch(r"\d{6}", d):
        return None
    y, m, dd = 2000 + int(d[:2]), int(d[2:4]), int(d[4:])
    if not (1 <= m <= 12 and 1 <= dd <= 31):
        return None
    return f"{y:04d}-{m:02d}-{dd:02d}"


def interpret_orient(orient: str | None, drop_type: str | None, ista6: dict | None) -> tuple[dict, list[str]]:
    """orient 숫자열 → 면 목록·낙하 분류·충격 방향(ISTA 6 normal_local 합의 반대가 아닌 '바닥 쪽' 방향)."""
    warns: list[str] = []
    out = {"faces": None, "drop_class": None, "impact_dir_local": None, "face_names": None}
    if orient is None:
        return out, warns
    digits = [int(c) for c in str(orient)]
    if any(d < 1 or d > 6 for d in digits) or len(set(digits)) != len(digits) or not 1 <= len(digits) <= 3:
        warns.append(f"orient '{orient}': ISTA 면 번호(1~6, 중복 없음, 1~3개)가 아님")
        return out, warns
    pairs = (ista6 or {}).get("opposite_pairs") or DEFAULT_OPPOSITE
    for a, b in pairs:
        if a in digits and b in digits:
            warns.append(f"orient '{orient}': 마주보는 면 {a}·{b} 가 함께 있음 — 꼭지점/모서리 불가")
            return out, warns
    faces = sorted(digits)
    cls = DROP_CLASS[len(faces)]
    out["faces"] = faces
    out["drop_class"] = cls
    if drop_type is not None and drop_type != cls:
        warns.append(f"drop_type '{drop_type}' 와 orient '{orient}'(면 {len(faces)}개 = {cls}) 불일치")
    fdef = (ista6 or {}).get("faces") or {}
    if fdef:
        names, vec = [], np.zeros(3)
        ok = True
        for f in faces:
            d = fdef.get(f) or fdef.get(str(f))
            if not d:
                ok = False
                continue
            names.append(d.get("name"))
            nl = d.get("normal_local")
            if nl is None:
                ok = False
            else:
                vec += np.asarray(nl, dtype=float)
        out["face_names"] = names
        if ok and np.linalg.norm(vec) > 0:
            out["impact_dir_local"] = (vec / np.linalg.norm(vec)).tolist()
    return out, warns


def drop_height(weight: float | None, drop_class: str | None, ista6: dict | None):
    """포장 중량 구간별 낙하 높이(ista6.yaml heights). 표 미입력·구간 없음이면 None."""
    if weight is None or drop_class is None or not ista6:
        return None
    for b in ((ista6.get("heights") or {}).get("bins") or []):
        lo = b.get("weight_min")
        hi = b.get("weight_max")
        if (lo is None or weight >= lo) and (hi is None or weight < hi):
            return b.get(drop_class)
    return None


def parse(path: str, rules: dict | None = None) -> dict:
    """경로 → 씬 메타 dict (FIELDS + date_iso, faces, drop_class, impact_dir_local, source, warnings)."""
    r = default_rules()
    if rules:
        r.update({k: v for k, v in rules.items() if v is not None})
    regs = r["scene_regex"]
    if isinstance(regs, str):
        regs = [regs]
    src = str(path)
    p = src.replace("\\", "/")
    vals: dict = {k: None for k in FIELDS}
    extra: dict = {}
    for rx in regs:
        m = re.search(rx, p)
        if not m:
            continue
        for k, v in m.groupdict().items():
            if v is None:
                continue
            if k in vals:
                if vals[k] is None:
                    vals[k] = v
            elif k not in extra:
                extra[k] = v
    warns: list[str] = []
    if vals["inch"] is None and vals["model"] is not None and r.get("inch_regex"):
        m = re.search(r["inch_regex"], vals["model"])
        if m:
            vals["inch"] = m.groupdict().get("inch") or (m.group(1) if m.groups() else m.group(0))
    for k in INT_FIELDS:
        if vals[k] is not None:
            try:
                vals[k] = int(vals[k])
            except ValueError:
                warns.append(f"{k} '{vals[k]}' 정수 변환 실패")
                vals[k] = None
    vals["drop_type"] = _canon_drop(vals["drop_type"])
    ot = _canon_drop(extra.get("orient_type"))
    if ot is not None and vals["drop_type"] is not None and ot != vals["drop_type"]:
        warns.append(f"파일명의 낙하 유형 '{vals['drop_type']}' 와 orient 접두 '{ot}' 불일치")
    opt = set(r.get("optional_fields") or ())
    for k in FIELDS:
        if vals[k] is None and k not in opt:
            warns.append(f"{k}: 경로에서 찾지 못함(null)")
    out = dict(vals)
    out["date_iso"] = _date_iso(vals["date"])
    if vals["date"] is not None and out["date_iso"] is None:
        warns.append(f"date '{vals['date']}' 가 YYMMDD 날짜가 아님")
    ori, w2 = interpret_orient(vals["orient"], vals["drop_type"], r.get("ista6"))
    out.update(ori)
    warns += w2
    out["extra"] = {k: v for k, v in extra.items() if k != "orient_type"}
    out["source"] = src
    out["warnings"] = warns
    return out
