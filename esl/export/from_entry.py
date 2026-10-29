"""라이브러리 항목 → 내보내기(계약 esl_menu_restructure.md §6.4, v0.10.0).

원본 = 항목 폴더 ``raw.npz``(allow_pickle=False)·``entry.json`` (Case 폴더는 읽기만 — 검증 스냅샷이 있을 때만). 출력 =
호출자가 준 폴더(``<esl_root>/_exports/<batch>/<NN>_<label>/``). 작성기는 ``stage_export`` 와 같은 것(``plan_ids``·
``radioss.write_cload_inc``·``write_bcs_inc``·``optistruct.write_force_fem``·``csvout``)을 같은 순서·같은 헤더로 부르므로
같은 입력이면 inc·fem 본문은 ``stage_export`` 와 바이트 동일(헤더 첫 줄 생성 시각 제외).

CSV(라이브러리): ``f_eq.csv``(같은 헤더), ``u_rel.csv``(같은 헤더, ``u_total`` 열은 항목에 없어 빈칸 + 경고),
``supports_321.csv``(node_id, dof), 검증 스냅샷이 있으면 ``reactions_321.csv``·``validation.csv``.
``tstar_candidates.csv``·``hotspots.csv`` 는 Case 자료라 넣지 않는다.

``run_items``: 묶음 항목을 순서대로(항목별 try) 처리. ``id_offset`` 이 ``"after:<entry_id>"`` 이면 앞 항목 결과
``<out_root>/<after_label>/export.json`` 의 ``id_next`` 를 시작 오프셋으로 쓴다(다른 작업의 항목이면 생길 때까지
``wait_s`` 대기 → ``EXPORT_ORDER_TIMEOUT``, 앞 항목 실패 → ``EXPORT_ORDER_PREV_FAILED``). 결과는 항목 폴더
``export.json``(성공·실패 모두, 임시 파일 → rename).

쓰기 안전(통합 검증 지적 4b): 항목 결과는 ``<out_root>/.<label>.part-<uuid>/`` 에 먼저 쓰고(새 이름 mkdir — 기존 링크를
따라가지 않음) 끝나면 ``<out_root>/<label>`` 로 rename(기존 폴더는 ``_backup/<ts>/`` 로). 쓰기·rename 전마다
``out_root`` 부터 대상까지 경로 성분이 심링크·junction·reparse point 가 아니고 realpath 가 ``out_root`` 안인지 확인
(아니면 ``PATH_UNSAFE`` — 그 항목만 실패, Case 폴더 등 바깥에 쓰지 않음).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import stat
import time
import uuid
from types import SimpleNamespace

import numpy as np

import esl
from esl.errors import EslError
from esl.export import AUTO_BASE, all_ids, csvout, force_mask, optistruct, plan_ids, radioss

EXPORT_JSON = "export.json"
# 플랫폼 run 스냅샷 05_val 표식 파일(그 검증의 DB id, 플랫폼 core_outputs.VAL_MARKER 와 같은 이름)
VAL_MARKER = "platform_validation_id.txt"
SUPPORTS_HEADER = ("node_id", "dof")
TARGETS = ("radioss_inc", "fem", "csv")
U_TOTAL_WARNING = "u_total 은 라이브러리 항목에 없어 u_rel.csv 의 *_total 열을 비움 — Case 결과 zip 참고"


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json_atomic(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, default=lambda x: x.tolist() if hasattr(x, "tolist") else str(x))
        fh.write("\n")
    os.replace(tmp, path)


def _load_npz(path: str) -> dict:
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def load_entry_model(entry_dir: str):
    """→ (model, raw, meta). model 은 write_force_fem 이 요구하는 속성(node_id·x0·elem_id·elem_type·conn·elem_pid·
    thickness·mats·max_ids·part_id·part_title·units_label)."""
    ej = os.path.join(entry_dir, "entry.json")
    rz = os.path.join(entry_dir, "raw.npz")
    miss = [n for n, p in (("entry.json", ej), ("raw.npz", rz)) if not os.path.isfile(p)]
    if miss:
        raise EslError("ENTRY_FILES_MISSING", f"항목 폴더에 {miss} 가 없음: {entry_dir}")
    meta = _read_json(ej)
    raw = _load_npz(rz)
    m = meta.get("model") or {}
    if not m.get("mats"):
        raise EslError("INPUT_INVALID", f"항목 entry.json 에 재료(model.mats)가 없음: {entry_dir}")
    model = SimpleNamespace(
        node_id=raw["node_id"], x0=raw["x0"], elem_id=raw["elem_id"], elem_type=raw["elem_type"].astype(np.int8),
        conn=raw["conn"], elem_pid=raw["elem_pid"], elem_mid=raw.get("elem_mid"), thickness=raw["thickness"],
        mats=m.get("mats") or [], max_ids=m.get("max_ids") or {},
        part_id=int(m["part_id"]) if m.get("part_id") is not None else None, part_title=m.get("part_title"),
        units_label=m.get("units_label") or "")
    return model, raw, meta


def _validation_for(meta: dict, validation_id: str | None, warnings: list[str]) -> dict | None:
    """항목 검증 스냅샷(<run 스냅샷>/05_val/validation.json, 읽기만). validation_id 를 주면 표식(VAL_MARKER)이 같을 때만,
    아니면 등록 당시 sha256 이 같을 때만. esl_ref 가 항목 ESL 결과와 다르면 쓰지 않는다."""
    src = meta.get("source") or {}
    snap = src.get("snapshot_dir")
    path = os.path.join(snap, "05_val", "validation.json") if snap else None
    rec = (src.get("files") or {}).get("validation.json") or {}
    if path is None or not os.path.isfile(path):
        path = rec.get("path") if rec.get("path") and os.path.isfile(rec.get("path")) else None
    if path is None:
        return None
    try:
        if validation_id:
            mk = os.path.join(os.path.dirname(path), VAL_MARKER)
            with open(mk, "r", encoding="utf-8") as fh:
                if fh.read().strip() != str(validation_id):
                    warnings.append("검증 스냅샷이 항목의 검증과 다름 — validation.csv·reactions_321.csv 생략")
                    return None
        else:
            from esl.library._util import sha256_file

            if rec.get("sha256") and sha256_file(path) != rec["sha256"]:
                warnings.append("검증 스냅샷이 등록 이후 바뀜 — validation.csv·reactions_321.csv 생략")
                return None
        val = _read_json(path)
    except (OSError, ValueError):
        return None
    ref = (meta.get("quality") or {}).get("esl_ref")
    if ref is not None and val.get("esl_ref") is not None and val.get("esl_ref") != ref:
        warnings.append("검증 스냅샷이 이 항목 ESL 결과의 것이 아님 — 검증 결과 없이 내보냄")
        return None
    return val


def export_entry(entry_dir: str, out_dir: str, targets, cfg: dict, id_offset, *, validation_id: str | None = None,
                 echo=None) -> dict:
    """항목 1개 → out_dir(이미 만들어진 빈 폴더). 반환 {files, id_range, id_max_used, id_next, id_offset_used,
    id_plan, warnings, targets} (export.json 은 run_items 가 쓴다)."""
    from esl.pipeline import normalize_export_targets

    targets = normalize_export_targets(targets)
    warnings: list[str] = []
    model, raw, meta = load_entry_model(entry_dir)
    nid, X0 = model.node_id, model.x0
    F = np.asarray(raw["f"], dtype=np.float64)
    sup_ids = [(int(n), str(d)) for n, d in zip(raw["support_node_id"], raw["support_dof"])]
    val = _validation_for(meta, validation_id, warnings)
    if val is None:
        warnings.append("검증(05_val) 결과 없음 — validation.csv·reactions_321.csv 생략")
    elif val.get("verdict") != "PASS":
        warnings.append(f"검증 {val.get('verdict')} 상태로 내보냄")
    ecfg = cfg["export"]
    rcfg = ecfg["radioss"]
    mask = force_mask(F, ecfg["force_zero_tol_rel"])
    want_ids = "radioss_inc" in targets or "fem" in targets
    plan = None
    lo = hi = None
    if want_ids:
        groups, _ = optistruct.pshell_groups(model.elem_pid, model.thickness)
        with_inc = "radioss_inc" in targets
        plan = plan_ids(id_offset, model.max_ids, len(sup_ids) if with_inc else 0, len(groups),
                        int(mask.any(axis=1).sum()) if with_inc else 0, int(mask.sum()) if with_inc else 0)
        lo, hi = plan["range"]
        ids = all_ids(plan)
        assert all(lo <= v <= hi for v in ids) and len(set(ids)) == len(ids)
        if plan["id_offset_auto"] and plan["id_offset"] != AUTO_BASE:
            warnings.append(f"export.radioss.id_offset=auto: rad 기존 ID 와 겹치지 않도록 생성 ID 를 "
                            f"{plan['id_offset'] + 1} 부터 배정")
    fr = meta.get("tstar") or {}
    units = cfg["units"]
    hdr = [f"ESL export (esl {esl.__version__})  generated {_utcnow()}",
           f"part {model.part_id} '{model.part_title}'  frame {fr.get('frame_index')}  t* = {fr.get('time')!r} "
           f"({fr.get('source')})",
           f"units: {units['label']} (force {units['force']}, length {units['length']}); rad /BEGIN: '{model.units_label}'",
           f"generated ID range [{lo}, {hi}] ({plan['n_ids'] if plan else 0} IDs, id_offset {plan['id_offset'] if plan else None})",
           f"validation: {val['verdict'] if val else 'N/A'}"]
    nf = ecfg["num_format"]
    files: list[str] = []
    out: dict = {"targets": list(targets)}

    def f(name: str) -> str:
        return os.path.join(out_dir, name)

    if "radioss_inc" in targets:
        rc = radioss.write_cload_inc(f("esl_cload.inc"), nid, F, mask, plan, rcfg["func_mode"], rcfg["ramp_time"], nf,
                                     hdr + [f"/CLOAD: |F_c| > {ecfg['force_zero_tol_rel']:g}*max|F|"])
        rb = radioss.write_bcs_inc(f("esl_bcs.inc"), sup_ids, plan,
                                   hdr + ["3-2-1 statically determinate supports (Tx Ty Tz flags, rotations free)"])
        files += ["esl_cload.inc", "esl_bcs.inc"]
        out.update(n_cload=rc["n_cload"], n_cload_nodes=rc["n_grnod"], n_bcs=rb["n_bcs"])
    if "fem" in targets:
        fo = optistruct.write_force_fem(f("esl_force.fem"), model, F, mask, sup_ids, plan, nf,
                                        hdr + [f"SPC SID {plan['fem_spc_sid']}, LOAD SID {plan['fem_load_sid']}"])
        files += ["esl_force.fem"]
        out.update(n_force=fo["n_force"], n_pshell=fo["n_pshell"])
    if "csv" in targets:
        c = ecfg["csv"]
        fmt = csvout.CsvFormat(c["delimiter"], c["float_format"])
        csvout.write_csv(f("f_eq.csv"), csvout.F_EQ_HEADER, csvout.f_eq_rows(nid, X0, F, raw["is_bc"]), fmt)
        ur = np.asarray(raw["u_rel"], dtype=np.float64)
        csvout.write_csv(f("u_rel.csv"), csvout.U_REL_HEADER,
                         ((int(nid[i]), *ur[i], None, None, None) for i in range(nid.size)), fmt)
        warnings.append(U_TOTAL_WARNING)
        csvout.write_csv(f("supports_321.csv"), SUPPORTS_HEADER, sup_ids, fmt)
        files += ["f_eq.csv", "u_rel.csv", "supports_321.csv"]
        if val is not None:
            rs = val.get("reactions") or []
            tot = np.sum([r["r"] for r in rs], axis=0) if rs else np.zeros(3)
            rows = [(r["node_id"], r["dof"], *r["r"]) for r in rs] + [("SUM", None, *tot)]
            csvout.write_csv(f("reactions_321.csv"), csvout.REACTIONS_HEADER, rows, fmt)
            csvout.write_validation_csv(f("validation.csv"), val, fmt)
            files += ["reactions_321.csv", "validation.csv"]
    if echo:
        echo(f"[export] 항목 {meta.get('entry_id')}: 대상 {list(targets)}, 파일 {len(files)}개"
             + (f", ID [{lo}..{hi}] ({plan['n_ids']}개)" if plan else ""))
    used_off = plan["id_offset"] if plan else id_offset
    out.update(files=files, id_range=[lo, hi] if plan else None, id_max_used=plan["max_used"] if plan else None,
               id_next=plan["max_used"] if plan else used_off, id_offset_used=used_off,
               id_plan=None if plan is None else {k: (v if not isinstance(v, list) or len(v) <= 6 else [v[0], v[-1]])
                                                  for k, v in plan.items()},
               validation_used=val is not None, warnings=warnings)
    return out


def _wait_prev(path: str, wait_s: float, poll_s: float) -> dict:
    end = time.monotonic() + float(wait_s)
    while True:
        if os.path.isfile(path):
            try:
                return _read_json(path)
            except (OSError, ValueError):
                pass                         # 쓰는 중(rename 전) — 다시 읽음
        if time.monotonic() >= end:
            raise EslError("EXPORT_ORDER_TIMEOUT", f"앞 항목 결과를 {wait_s:g} s 안에 받지 못함 — 같은 모델 ID 연속 배정 불가")
        time.sleep(poll_s)


_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _is_link_like(path: str) -> bool:
    """심링크 또는 Windows junction·reparse point(없는 경로는 False) — 플랫폼 core.uploads.is_link_like 와 같은 판정."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & _REPARSE:
        return True
    isj = getattr(os.path, "isjunction", None)
    return bool(isj and isj(path))


def _within(path: str, root: str) -> bool:
    a, b = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(root))
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


def _check_safe(out_root: str, path: str) -> None:
    """out_root 와 out_root 아래 path 까지 이미 있는 성분이 링크·junction 이 아니고 realpath(path) ⊂ realpath(out_root)."""
    rootn = os.path.normpath(out_root)
    if _is_link_like(rootn):
        raise EslError("PATH_UNSAFE", "내보내기 묶음 폴더가 링크입니다")
    rel = os.path.relpath(os.path.normpath(path), rootn)
    if rel == os.curdir or rel.startswith(os.pardir) or os.path.isabs(rel):
        raise EslError("PATH_UNSAFE", f"내보내기 묶음 폴더 밖 경로입니다: {rel}")
    cur = rootn
    for comp in rel.split(os.sep):
        cur = os.path.join(cur, comp)
        if _is_link_like(cur):
            raise EslError("PATH_UNSAFE", f"링크 경로에는 쓰지 않습니다: {os.path.relpath(cur, rootn)}")
    if not _within(path, rootn):
        raise EslError("PATH_UNSAFE", "실제 경로가 내보내기 묶음 폴더 밖입니다")


def _new_stage(out_root: str, label: str) -> str:
    """새 이름의 빈 작업 폴더(mkdir 은 기존 경로·링크를 따라가지 않고 실패)."""
    st = os.path.join(out_root, f".{label}.part-{uuid.uuid4().hex[:12]}")
    _check_safe(out_root, st)
    os.mkdir(st)
    _check_safe(out_root, st)
    return st


def _publish(stage: str, d: str, out_root: str) -> None:
    """작업 폴더 → <out_root>/<label>. 기존 d(이전 실행)는 <out_root>/_backup/<ts>/<이름> 로(삭제 없음)."""
    _check_safe(out_root, d)
    if os.path.lexists(d):
        ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        bdir = os.path.join(out_root, "_backup", ts)
        _check_safe(out_root, bdir)
        os.makedirs(bdir, exist_ok=True)
        _check_safe(out_root, bdir)
        os.replace(d, os.path.join(bdir, os.path.basename(d)))
    _check_safe(out_root, d)
    os.replace(stage, d)


def run_items(items: list[dict], out_root: str, targets, cfg: dict, *, wait_s: float = 600.0, poll_s: float = 0.5,
              echo=None, progress=None) -> list[dict]:
    """items = [{entry_id, dir(항목 폴더 절대경로), label, id_offset("auto"|정수|"after:<entry_id>"), after_label?,
    validation_id?}] → 항목별 결과 [{entry_id, label, ok, files, id_range, id_max_used, warnings, error}].
    항목 실패는 다음 항목으로 진행(export.json 에 error 기록)."""
    out: list[dict] = []
    for k, it in enumerate(items):
        d = os.path.join(out_root, it["label"])
        stage = None
        rec = {"entry_id": it["entry_id"], "label": it["label"], "ok": False, "files": [], "id_range": None,
               "id_max_used": None, "id_next": None, "warnings": [], "error": None}
        try:
            off = it.get("id_offset", "auto")
            if isinstance(off, str) and off.startswith("after:"):
                prev_label = it.get("after_label")
                if not prev_label:
                    raise EslError("INPUT_INVALID", f"id_offset {off}: after_label 없음")
                if echo:
                    echo(f"[export] {it['label']}: 같은 모델 앞 항목({prev_label}) ID 사용량 대기")
                prev = _wait_prev(os.path.join(out_root, prev_label, EXPORT_JSON), wait_s, poll_s)
                if not prev.get("ok"):
                    raise EslError("EXPORT_ORDER_PREV_FAILED", f"같은 모델 앞 항목({prev_label})이 실패해 ID 를 이어 배정할 수 없음")
                off = prev.get("id_next")
                if off is None:
                    off = "auto"
            stage = _new_stage(out_root, it["label"])
            res = export_entry(it["dir"], stage, targets, cfg, off, validation_id=it.get("validation_id"), echo=echo)
            rec.update(ok=True, **{k2: res[k2] for k2 in ("files", "id_range", "id_max_used", "id_next", "warnings",
                                                          "id_offset_used", "id_plan", "validation_used")})
        except EslError as exc:
            rec["error"] = {"code": exc.code, "message": exc.message}
        except (OSError, ValueError, KeyError) as exc:
            rec["error"] = {"code": "EXPORT_FAILED", "message": f"{type(exc).__name__}: {exc}"[:400]}
        if rec["error"] and echo:
            echo(f"[export] {it['label']}: 실패 {rec['error']['code']}: {rec['error']['message']}")
        try:
            if stage is None:
                stage = _new_stage(out_root, it["label"])
            _check_safe(out_root, os.path.join(stage, EXPORT_JSON))
            _write_json_atomic(os.path.join(stage, EXPORT_JSON), {**rec, "entry_id": it["entry_id"],
                                                                 "targets": list(targets), "at": _utcnow()})
            _publish(stage, d, out_root)
        except (OSError, EslError) as exc:
            if echo:
                echo(f"[export] {it['label']}: 결과 쓰기 실패 {exc}")
            if rec["error"] is None:
                rec.update(ok=False, error={"code": getattr(exc, "code", "EXPORT_FAILED"),
                                            "message": str(getattr(exc, "message", exc))[:400]})
        out.append(rec)
        if progress:
            progress(100.0 * (k + 1) / max(1, len(items)))
    return out
