"""Ground-truth comparison for the frozen H6 / H5 fixtures (V-BG-1·2). numpy only — no gmsh / shapely."""
from __future__ import annotations

import collections

import numpy as np

INV = {0: "floor", 1: "wall", 2: "island", 3: "lance"}
JTYPE = {"TL_side": "W", "TL_top": "W", "TR_side": "W", "TR_top": "W", "BL_corner": "L", "BR_corner": "L",
         "T_legL": "T", "T_comb1": "T", "T_comb2": "T", "T_legR": "T", "ch1_flare": "Y", "ch2_flare": "Y",
         "step_ch1_pL": "step", "step_ch1_pC": "step", "step_ch2_pC": "step", "step_ch2_pR": "step"}


def _gt(fx, key):
    names = fx[f"gt_{key}_names"]
    v = names[fx[f"gt_{key}"]].astype(object)
    v[v == ""] = None
    return v


def centroids(x0, conn):
    C = np.asarray(conn, np.int64)
    q = C[:, 3] >= 0
    c = x0[C[:, :3]].sum(axis=1)
    c[q] += x0[C[q, 3]]
    return c / np.where(q, 4.0, 3.0)[:, None]


def evaluate_h6(graph, labels, fx, seg_raw=None) -> dict:
    """V-BG-1 metrics. seg_raw = pre-absorption segment label (``classify_full`` aux) for the 23-segment IoU and the
    segment label accuracy (absorbed corners / short strips / spurs are junction zones in ``labels``)."""
    x0, conn = fx["x0"], fx["conn"]
    gcls, gpiece, gtrans, gisl, gseg = (_gt(fx, k) for k in ("cls", "piece", "trans", "island", "seg"))
    gtier = fx["gt_tier"].astype(np.int64)
    ne = gcls.size
    pcls = np.array([INV[int(c)] for c in labels["cls"]], dtype=object)
    pfl = labels["floor"].astype(np.int64)
    # floor id -> GT piece name (majority)
    fmap = {}
    for f in graph["floors"]:
        m = (pfl == f["id"]) & (pcls == "floor")
        vals = [v for v in gpiece[m] if v is not None]
        fmap[f["id"]] = collections.Counter(vals).most_common(1)[0][0] if vals else None

    def nm(p):
        if p is None or p < 0:
            return "?"
        return fmap.get(p) or f"f{p}"
    tr = {t["id"]: t for t in graph["transitions"]}
    ptr = labels["transition"].astype(np.int64)
    ppiece = np.array([nm(p) if c == "floor" else None for p, c in zip(pfl.tolist(), pcls)], dtype=object)
    ptrans = np.array([f"{nm(tr[t]['upper'])}|{nm(tr[t]['lower'])}" if (c == "wall" and t >= 0) else None
                       for t, c in zip(ptr.tolist(), pcls)], dtype=object)
    res = {"n_elems": int(ne)}
    cl = {}
    for k in ("floor", "wall", "island", "lance"):
        m = gcls == k
        pm = pcls == k
        tp = int((m & pm).sum())
        cl[k] = {"recall": tp / max(int(m.sum()), 1), "precision": tp / max(int(pm.sum()), 1)}
    res["class"] = cl
    res["class_acc"] = float((gcls == pcls).mean())
    mf = gcls == "floor"
    mw = gcls == "wall"
    ok_f = mf & (pcls == "floor") & (ppiece == gpiece)
    ok_w = mw & (pcls == "wall") & (ptrans == gtrans)
    res["floor_piece_acc"] = float(ok_f.sum() / mf.sum())
    res["wall_owner_acc"] = float(ok_w.sum() / mw.sum())
    mt = mf | mw
    res["tier_acc"] = float(((labels["tier"].astype(np.int64) == gtier) & mt).sum() / mt.sum())
    c = centroids(x0, conn)
    # segments (pre-absorption units)
    pseg = np.asarray(seg_raw if seg_raw is not None else labels["segment"], np.int64)
    exp = sorted({x for x in gseg if x is not None and not str(x).startswith("J:")})
    used, rows, nfound = set(), [], 0
    for k in exp:
        m = gseg == k
        vals = pseg[m]
        vals = vals[vals >= 0]
        best, biou = None, 0.0
        for v in np.unique(vals).tolist():
            pm = pseg == v
            iou = float((m & pm).sum() / (m | pm).sum())
            if iou > biou:
                best, biou = int(v), iou
        ok = biou >= 0.5 and best not in used
        if ok:
            used.add(best)
        nfound += ok
        rows.append({"gt": k, "pred": best, "iou": round(biou, 3)})
    res["segments"] = {"expected": len(exp), "found_iou50": int(nfound), "rows": rows,
                       "extra_units": sorted(set(np.unique(pseg[pseg >= 0]).tolist()) - used)}
    jn = [str(x) for x in fx["exp_junction_names"]]
    jx = fx["exp_junction_xy"]
    dj = np.min(np.hypot(c[:, None, 0] - jx[None, :, 0], c[:, None, 1] - jx[None, :, 1]), axis=1)
    pmap = {}
    for v in np.unique(pseg[pseg >= 0]).tolist():
        vals = [x for x in gseg[pseg == v] if x is not None]
        pmap[int(v)] = collections.Counter(vals).most_common(1)[0][0] if vals else None
    ms = np.array([x is not None and not str(x).startswith("J:") for x in gseg]) & (dj > 10)
    pnm = np.array([pmap.get(int(v)) if v >= 0 else None for v in pseg.tolist()], dtype=object)
    res["segment_elem_acc"] = float((ms & (pnm == gseg)).sum() / ms.sum())
    # junctions (world xy of pos)
    pj = graph["junctions"]
    P = np.array([j["pos"][:2] for j in pj]) if pj else np.zeros((0, 2))
    jrows, usedj = [], set()
    for k, (x, y) in zip(jn, jx.tolist()):
        d = np.hypot(P[:, 0] - x, P[:, 1] - y) if len(P) else np.zeros(0)
        hit = None
        for o in np.argsort(d).tolist():
            if d[o] > 35:
                break
            if o not in usedj:
                hit = o
                break
        if hit is not None:
            usedj.add(hit)
        jrows.append({"exp": k, "pred": None if hit is None else pj[hit]["id"],
                      "type": None if hit is None else pj[hit]["type"], "type_ok": hit is not None and
                      pj[hit]["type"] == JTYPE.get(k)})
    res["junctions"] = {"expected": len(jn), "found": sum(r["pred"] is not None for r in jrows),
                        "type_ok": sum(r["type_ok"] for r in jrows), "pred_total": len(pj), "rows": jrows,
                        "types": dict(collections.Counter(j["type"] for j in pj))}
    # islands
    pi = labels["island"].astype(np.int64)
    names = sorted({x for x in gisl if x is not None})
    found, lance_ok, strad, missed = 0, 0, [], []
    for nmx in names:
        m = gisl == nmx
        vals = pi[m]
        vals = vals[vals >= 0]
        if vals.size == 0:
            missed.append(nmx)
            continue
        best = int(np.bincount(vals).argmax())
        pm = pi == best
        iou = float((m & pm).sum() / (m | pm).sum())
        isl = graph["islands"][best]
        ok = iou >= 0.5
        found += ok
        if not ok:
            missed.append(nmx)
        if nmx.startswith("lance"):
            lance_ok += int(ok and isl["lance"])
        if nmx.startswith("wboss"):
            strad.append(bool(isl["straddle"]))
    res["islands"] = {"expected": len(names), "found_iou50": int(found),
                      "lances_expected": sum(n.startswith("lance") for n in names), "lances_found": int(lance_ok),
                      "straddle_expected": len(strad), "straddle_found": int(sum(strad)), "missed": missed}
    hx = fx["exp_hole_xy"]
    ph = np.array([h["center"][:2] for h in graph["holes"]]) if graph["holes"] else np.zeros((0, 2))
    hit = fixed_ok = slot_ok = 0
    for (x, y), fxd, slot in zip(hx.tolist(), fx["exp_hole_fixed"].tolist(), fx["exp_hole_lance_slot"].tolist()):
        if not len(ph):
            break
        d = np.hypot(ph[:, 0] - x, ph[:, 1] - y)
        j = int(np.argmin(d))
        if d[j] < 3.0:
            hit += 1
            fixed_ok += int(graph["holes"][j]["fixed"] == fxd)
            slot_ok += int(slot and graph["holes"][j]["lance_slot"])
    res["holes"] = {"expected": int(len(hx)), "found": hit, "fixed_flag_ok": fixed_ok,
                    "lance_slots_expected": int(fx["exp_hole_lance_slot"].sum()), "lance_slots_found": slot_ok}
    wrong = np.where(gcls == "floor", ok_f, np.where(gcls == "wall", ok_w, gcls == pcls))
    res["label_acc_all"] = float(wrong.mean())
    return res


def evaluate_h5(graph, labels, fx) -> dict:
    """V-BG-2: ring 4 sides + 2 vertical beads + 2 T, no ring-labelled wall on V1/V2, zones = 4 corners + 2 T."""
    lab = _gt(fx, "lab")
    seg = labels["segment"].astype(np.int64)
    segs = {s["id"]: s for s in graph["segments"]}
    sides = sorted({s["side"] for s in graph["segments"] if s["side"]})
    ring_ids = {s["id"] for s in graph["segments"] if s["type"] == "ring"}
    vwall = np.isin(lab, ["v1_s", "v2_s"])
    leak = int(np.isin(seg[vwall], list(ring_ids)).sum()) if ring_ids else 0
    vb = []
    for k in ("v1_f", "v2_f"):
        vals = seg[(lab == k) & (seg >= 0)]
        vb.append(int(np.bincount(vals).argmax()) if vals.size else -1)
    zones = collections.Counter(z["reason"] for z in graph["junction_zones"])
    jt = collections.Counter(j["type"] for j in graph["junctions"])
    return {"sides": sides, "n_ring_segments": len(ring_ids), "v_beads": vb,
            "v_types": [segs[v]["type"] if v in segs else None for v in vb], "ring_label_on_v_walls": leak,
            "junction_types": dict(jt), "zone_reasons": dict(zones), "n_zones": len(graph["junction_zones"])}
