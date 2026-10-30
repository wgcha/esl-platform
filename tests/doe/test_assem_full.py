"""v0.12.1 paicad --assem-dir = 모델 전체 사본 prep/assem_full(esl.doe.assem_full): starter include 트리(폴더 밖 상위·형제
include, 순환), 허용 루트 밖 거부, 원본 불변, 엔진 rad 설정, 스캔 정규화(실서버 형태 카드: /SURF/PART/EXT·#title·주석 머리,
/SURF/SUBSET/EXT, /GRNOD/GENE, 솔리드 /SURF → /SURF/SEG: 브릭 외곽면·내부면 제외·ALL·테트라·혼합), 모핑 사본 복원,
(paicad 소스가 있으면) 실제 paicad fixed-scan 계산으로 shell-shell·shell-solid tie 고정 노드."""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

from esl.doe import assem_full as A
from esl.errors import EslError


def I(*v):  # noqa: E743 - 10칸 정수 줄
    return "".join(f"{x:10d}" for x in v)


def node(n, x, y, z):
    return f"{n:10d}{x:20.6f}{y:20.6f}{z:20.6f}"


def bn(i, j, k):
    return 101 + i + 3 * j + 6 * k


def parts_inc() -> str:
    L = ["#RADIOSS include 101_parts.inc", "/NODE"]
    k = 0
    for j in range(3):
        for i in range(3):
            k += 1
            L.append(node(k, 10.0 * i, 10.0 * j, 0.0))                       # Ch/R 1..9 (z=0)
    for n, (x, y) in zip(range(201, 205), [(0, 0), (10, 0), (10, 10), (0, 10)]):
        L.append(node(n, x, y, 1.0))                                         # 유리 쉘 201..204 (z=1)
    for kz, z in enumerate((-5.0, -1.0)):
        for j in range(2):
            for i in range(3):
                L.append(node(bn(i, j, kz), 10.0 * i, 10.0 * j, z))          # 브릭 101..112
    for n, xyz in zip(range(301, 306), [(0, 0, -20), (10, 0, -20), (0, 10, -20), (0, 0, -30), (5, 5, -10)]):
        L.append(node(n, *xyz))
    for n, xyz in zip(range(401, 406), [(50, 0, 0), (60, 0, 0), (60, 10, 0), (50, 10, 0), (55, 5, -5)]):
        L.append(node(n, *xyz))
    L += ["/PART/7", "CHASSIS REAR", I(1, 1), "/PART/76", "GLASS", I(1, 1), "/PART/75", "SOLID A", I(2, 1, 5),
          "/PART/80", "TET B", I(2, 1, 6), "/PART/90", "MIXED", I(1, 1)]
    L += ["/SHELL/7", I(1, 1, 2, 5, 4), I(2, 2, 3, 6, 5), I(3, 4, 5, 8, 7), I(4, 5, 6, 9, 8)]
    L += ["/SHELL/76", I(101, 201, 202, 203, 204)]
    e1 = [bn(0, 0, 0), bn(1, 0, 0), bn(1, 1, 0), bn(0, 1, 0), bn(0, 0, 1), bn(1, 0, 1), bn(1, 1, 1), bn(0, 1, 1)]
    e2 = [x + 1 for x in e1]
    L += ["/BRICK/75", "#  brick_ID    node1 ...", I(201, *e1), I(202, *e2)]
    L += ["/TETRA4/80", I(301, 301, 302, 303, 304), I(302, 302, 303, 304, 305)]
    L += ["/SHELL/90", I(401, 401, 402, 403, 404), "/TETRA4/90", I(402, 401, 402, 403, 405)]
    # 실서버 형태: #title 줄·주석 머리
    L += ["/SURF/PART/EXT/1360", "#title", "SET-COMP-GLASS-UPPER_75", "#  parts_ID", I(7),
          "/SURF/PART/EXT/1361", "#title", "SET-SOLID-75", I(75),
          "/SURF/PART/ALL/1363", "SET-SOLID-75-ALL", I(75),
          "/SURF/PART/1364", "MIXED", I(90),
          "/SURF/SEG/1365", "PLAIN SEG", I(1, 1, 2, 5, 4)]
    return "\n".join(L) + "\n"


SETS = "\n".join([
    "/SUBSET/5", "#title", "SUB-SOLIDS", "#  isubs1", I(6),
    "/SUBSET/6", "SUB-TET", "",
    "/SURF/SUBSET/EXT/1362", "#title", "SURF-SUBSET", I(5),
    "/GRNOD/GENE/20", "#title", "GLASS-NODES", "#  first_ID   last_ID", I(201, 202, 203, 204),
    "/GRNOD/NODE/22", "CHR-NODES", I(1, 2, 3),
    "/GRNOD/SUBSET/23", "G-SUBSET", I(6),
]) + "\n"

TIE = "\n".join([
    "/INCLUDE \"loop.inc\"",
    "/INTER/TYPE2/3008", "SHELL-SHELL", I(20, 1360),
    "/INTER/TYPE2/3009", "SHELL-SOLID", I(22, 1361),
]) + "\n"


def model(tmp_path: Path) -> dict:
    root = tmp_path / "inputs"
    case = root / "models" / "case"
    common = root / "models" / "common"
    shared = root / "shared"
    for d in (case, common, shared):
        d.mkdir(parents=True)
    (case / "101_parts.inc").write_text(parts_inc())
    (case / "model_0000.rad").write_text("#RADIOSS STARTER\n/BEGIN\nmodel\n/INCLUDE \"101_parts.inc\"\n"
                                          "/INCLUDE \"../common/tie.inc\"\n/INCLUDE \"../../shared/sets.inc\"\n/END\n")
    (case / "model_0001.rad").write_text("/RUN/model/1\n10.0\n")
    (case / "unrelated.inc").write_text("/NODE\n" + node(999, 0, 0, 0) + "\n")
    (common / "tie.inc").write_text(TIE)
    (common / "loop.inc").write_text("/INCLUDE \"tie.inc\"\n")                 # 순환
    (shared / "sets.inc").write_text(SETS)
    return {"root": root, "case": case, "starter": case / "model_0000.rad"}


def tree_sha(d: Path) -> dict:
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.rglob("*")) if p.is_file()}


def stage(m, tmp_path, **kw):
    dest = tmp_path / "out" / "prep" / "assem_full"
    dest.mkdir(parents=True)
    man = A.copy_model_full(str(m["starter"]), str(m["case"]), [str(m["root"])], str(dest), max_mb=kw.pop("max_mb", 10),
                            **kw)
    return dest, man


def block(text: str, head: str) -> list[str]:
    L = text.splitlines()
    i = L.index(head)
    j = next((k for k in range(i + 1, len(L)) if L[k].startswith("/")), len(L))
    return L[i:j]


def test_closure_outside_includes_cycle_and_inputs_unchanged(tmp_path):
    m = model(tmp_path)
    before = tree_sha(m["root"])
    dest, man = stage(m, tmp_path)
    rels = [f["rel"] for f in man["files"]]
    assert rels == ["model_0000.rad", "101_parts.inc", "_ext/models/common/tie.inc", "_ext/models/common/loop.inc",
                    "_ext/shared/sets.inc"]                       # 순환 1회씩, 엔진 rad·무관 파일 제외
    assert man["n_files"] == 5 and man["n_outside"] == 3
    assert (dest / "_ext" / "shared" / "sets.inc").is_file()
    assert tree_sha(m["root"]) == before                            # 원본 불변
    assert not any(p.is_symlink() for p in dest.rglob("*"))
    assert not list(dest.rglob("*.tmp"))
    for f in man["files"]:                                          # 정규화 안 한 파일 = 원본 그대로
        if not f["normalized"]:
            assert hashlib.sha256((dest / f["rel"]).read_bytes()).hexdigest() == f["sha256"]
    # 엔진 rad 설정
    d2 = tmp_path / "o2"
    d2.mkdir()
    man2 = A.copy_model_full(str(m["starter"]), str(m["case"]), [str(m["root"])], str(d2), max_mb=10, engine_rad=True)
    assert "model_0001.rad" in [f["rel"] for f in man2["files"]]


def test_outside_root_rejected_and_size_limit(tmp_path):
    m = model(tmp_path)
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "x.inc").write_text("/NODE\n")
    (m["case"] / "model_0000.rad").write_text(f"/INCLUDE \"{other / 'x.inc'}\"\n")
    with pytest.raises(EslError) as e:
        stage(m, tmp_path)
    assert e.value.code == "PATH_OUTSIDE_ROOT" and "x.inc" in e.value.message
    m = model(tmp_path / "b")
    with pytest.raises(EslError) as e:
        A.copy_model_full(str(m["starter"]), str(m["case"]), [str(m["root"])], str(tmp_path), max_mb=1e-4)
    assert e.value.code == "ASSEM_TOO_LARGE"


def test_link_rejected(tmp_path):
    m = model(tmp_path)
    os.symlink(m["root"] / "shared" / "sets.inc", m["case"] / "lnk.inc")
    (m["case"] / "model_0000.rad").write_text("/INCLUDE \"lnk.inc\"\n")
    with pytest.raises(EslError) as e:
        stage(m, tmp_path)
    assert e.value.code == "PATH_OUTSIDE_ROOT"


def test_normalize_cards(tmp_path):
    m = model(tmp_path)
    dest, man = stage(m, tmp_path)
    p = (dest / "101_parts.inc").read_text()
    s = (dest / "_ext" / "shared" / "sets.inc").read_text()
    # (a) 쉘 /SURF/PART/EXT → /SURF/PART, 제목·주석·데이터 그대로
    assert block(p, "/SURF/PART/1360") == ["/SURF/PART/1360", "#title", "SET-COMP-GLASS-UPPER_75", "#  parts_ID", I(7)]
    # (d) 솔리드 EXT → /SURF/SEG: 브릭 2개 외곽면 10(공유 면 제외), ALL = 11
    seg = block(p, "/SURF/SEG/1361")
    assert seg[:3] == ["/SURF/SEG/1361", "#title", "SET-SOLID-75"] and len(seg) - 3 == 10
    shared = sorted([bn(1, 0, 0), bn(1, 1, 0), bn(1, 0, 1), bn(1, 1, 1)])
    keys = [sorted(set(A._ints(x)[1:5])) for x in seg[3:]]
    assert shared not in keys and all(len(k) == 4 for k in keys)
    assert len(block(p, "/SURF/SEG/1363")) - 2 == 11
    # 혼합 파트(쉘 1 + 테트라 면 4), 원래 /SURF/SEG 는 그대로
    mixed = block(p, "/SURF/SEG/1364")[2:]
    assert len(mixed) == 5 and A._ints(mixed[0])[1:] == [401, 402, 403, 404]
    assert all(A._ints(x)[3] == A._ints(x)[4] for x in mixed[1:])       # 삼각면 n4 = n3
    assert block(p, "/SURF/SEG/1365") == ["/SURF/SEG/1365", "PLAIN SEG", I(1, 1, 2, 5, 4)]
    # (b)+(d) /SURF/SUBSET/EXT → subset 5 ⊃ 6 → 파트 75(/PART subset 5)·80(subset 6): 브릭 10 + 테트라 2개 외곽 6
    ss = block(s, "/SURF/SEG/1362")
    assert len(ss) - 3 == 16
    # (b) /GRNOD/SUBSET → /GRNOD/PART, (c) /GRNOD/GENE → /GRNOD/NODE
    assert block(s, "/GRNOD/PART/23") == ["/GRNOD/PART/23", "G-SUBSET", I(80)]
    g = block(s, "/GRNOD/NODE/20")
    assert g[:4] == ["/GRNOD/NODE/20", "#title", "GLASS-NODES", "#  first_ID   last_ID"]
    assert A._ints(g[4]) == [201, 202, 203, 204]
    assert man["normalized"] == {"SURF/PART/EXT→SURF/PART": 1, "SURF/PART/EXT(솔리드)→SURF/SEG": 1,
                                 "SURF/PART/ALL(솔리드)→SURF/SEG": 1, "SURF/PART(솔리드)→SURF/SEG": 1,
                                 "SURF/SUBSET/EXT(솔리드)→SURF/SEG": 1, "GRNOD/GENE→GRNOD/NODE": 1,
                                 "GRNOD/SUBSET→GRNOD/PART": 1}
    assert man["n_normalized"] == 7
    # /NODE·요소 블록 불변
    o = (m["case"] / "101_parts.inc").read_text()
    assert block(p, "/NODE") == block(o, "/NODE") and block(p, "/BRICK/75") == block(o, "/BRICK/75")
    # 끄기
    d3 = tmp_path / "o3"
    d3.mkdir()
    man3 = A.copy_model_full(str(m["starter"]), str(m["case"]), [str(m["root"])], str(d3), max_mb=10,
                             fixed_scan={"enabled": False})
    assert man3["n_normalized"] == 0 and (d3 / "101_parts.inc").read_text() == o


def test_tetra_exterior_and_bad_cards(tmp_path):
    M = A.Model()
    M.elems = {80: {"TETRA4": [[1, 2, 3, 4], [2, 3, 4, 5]]}, 81: {"BRICK": [[1, 2, 3, 4, 5, 6, 7, 8]]},
               82: {"PENTA6": [[1, 2, 3, 4, 5, 6]]}}
    assert len(A.solid_segments(M, [80], "EXT", "x")) == 6 and len(A.solid_segments(M, [80], "ALL", "x")) == 7
    assert len(A.solid_segments(M, [81], "EXT", "x")) == 6 and len(A.solid_segments(M, [82], "EXT", "x")) == 5
    cfg = A.norm_cfg({"rules": [["SURF/PART/EXT", "SURF/PART"]]})
    with pytest.raises(EslError) as e:
        A.normalize_lines(["/SURF/SUBSET/EXT/9", "T", I(77)], cfg, A.Model(), "a.inc")
    assert e.value.code == "FIXED_PARSE_FAILED" and "/SURF/SUBSET/EXT/9" in e.value.message and "77" in e.value.message
    with pytest.raises(EslError) as e:
        A.normalize_lines(["/GRNOD/GENE/4", "T", I(10, 5, 1)], cfg, A.Model(), "a.inc")
    assert "/GRNOD/GENE/4" in e.value.message
    M2 = A.Model()
    M2.subsets = {1: [2], 2: [1]}                                   # 순환 subset → 파트 없음 오류(무한 루프 아님)
    with pytest.raises(EslError):
        M2.subset_parts(1, "x")


def test_restore_out_files(tmp_path):
    m = model(tmp_path)
    dest, man = stage(m, tmp_path)
    of = tmp_path / "out_files"
    of.mkdir()
    staged = (dest / "101_parts.inc").read_text().splitlines()
    i = staged.index(node(5, 10.0, 10.0, 0.0))
    staged[i] = node(5, 10.0, 10.0, 1.5)                              # paicad 모핑 = /NODE 좌표만
    (of / "101_parts.inc").write_text("\n".join(staged) + "\n")
    assert A.restore_out_files(str(of), ["101_parts.inc"], man) == 1
    want = (m["case"] / "101_parts.inc").read_text().replace(node(5, 10.0, 10.0, 0.0), node(5, 10.0, 10.0, 1.5))
    assert (of / "101_parts.inc").read_text() == want                 # 원본 + 모핑 좌표(정규화 흔적 없음)
    bad = [x for x in staged if x != node(9, 20.0, 20.0, 0.0)]       # /NODE 줄 수 다름 → 복원 불가
    (of / "101_parts.inc").write_text("\n".join(bad) + "\n")
    with pytest.raises(EslError) as e:
        A.restore_out_files(str(of), ["101_parts.inc"], man)
    assert e.value.code == "PAICAD_FAILED"


def _paicad_src() -> Path | None:
    for p in (os.environ.get("PAICAD_SRC"), "/home/claude/wgcha/physicsai-platform/packages/paicad/src"):
        if p and (Path(p) / "paicad" / "shell" / "fixed.py").is_file():
            return Path(p)
    return None


@pytest.mark.skipif(_paicad_src() is None, reason="paicad 소스 없음(PAICAD_SRC)")
def test_real_paicad_fixed_scan_on_staged(tmp_path):
    sys.path.insert(0, str(_paicad_src()))
    try:
        from paicad.common import PaicadError
        from paicad.shell import opts
        from paicad.shell.assem import read_assembly
        from paicad.shell.fixed import compute_fixed
    finally:
        sys.path.pop(0)
    m = model(tmp_path)
    o = opts.load(None)
    fx0 = compute_fixed(read_assembly(m["case"]), [7], o)             # Case 폴더 제자리: 폴더 밖 TYPE2 를 못 봄
    assert not any(r["kind"].startswith("INTER_TYPE2") for r in fx0.refs)
    d0 = tmp_path / "raw"
    d0.mkdir()
    A.copy_model_full(str(m["starter"]), str(m["case"]), [str(m["root"])], str(d0), max_mb=10,
                      fixed_scan={"enabled": False})
    with pytest.raises(PaicadError):                                   # 전체 사본이어도 EXT·GENE 미지원
        compute_fixed(read_assembly(d0), [7], o)
    dest, _ = stage(m, tmp_path)
    fx = compute_fixed(read_assembly(dest), [7], o)
    ids = set(int(x) for x in fx.node_id)
    kinds = {r["kind"]: r for r in fx.refs}
    assert {1, 2, 3} <= ids                                            # shell-solid tie(3009): Ch/R secondary 고정
    assert kinds["INTER_TYPE2_SECONDARY"]["id"] == 3009
    assert kinds["INTER_TYPE2_MAIN"]["id"] == 3008 and {1, 2, 4, 5} <= ids   # shell-shell tie(3008): 유리 아래 main


# ---------------------------------------------------------------- 검증 지적 보완
def _model_from(lines_by_file, need):
    M = A.Model()
    for L in lines_by_file:
        M.scan(L)
    for L in lines_by_file:
        M.scan_elems(L, need)
    return M


def _e1():
    return [bn(0, 0, 0), bn(1, 0, 0), bn(1, 1, 0), bn(0, 1, 0), bn(0, 0, 1), bn(1, 0, 1), bn(1, 1, 1), bn(0, 1, 1)]


def test_shell_real_fields_and_mixed_surf():
    shell = ["/SHELL/95", "#   shell_ID     node1     node2     node3     node4                 phi            Thick",
             I(1, 1, 2, 5, 4) + f"{0.0:20.4f}{1.2:20.4f}", I(2, 2, 3, 6, 5) + f"{0.0:20.4f}{1.2:20.4f}",
             "3, 4, 5, 8, 7, 0.0, 1.2"]                                      # 자유 형식 + 실수 칸
    sh3 = ["/SH3N/95", I(4, 5, 6, 9) + f"{0.0:20.4f}{0.8:20.4f}"]
    brick = ["/BRICK/75", I(201, *_e1())]
    surf = ["/SURF/PART/EXT/1366", "#title", "MIXED SHELL+SOLID", I(95, 75)]
    L = shell + sh3 + brick + surf
    M = _model_from([L], {95, 75})
    assert len(M.elems[95]["SHELL"]) == 3 and M.elems[95]["SH3N"] == [[5, 6, 9, 9]]
    new, c = A.normalize_lines(L, A.norm_cfg(None), M, "x.inc")
    seg = block("\n".join(new), "/SURF/SEG/1366")[3:]
    assert len(seg) == 4 + 6 and c == {"SURF/PART/EXT(솔리드)→SURF/SEG": 1}
    assert A._ints(seg[0])[1:] == [1, 2, 5, 4] and A._ints(seg[3])[1:] == [5, 6, 9, 9]


def test_multiline_solids_and_ext_across_parts():
    b20 = list(range(1, 21))
    L = ["/BRIC20/60", I(1, *b20[:9]), I(*b20[9:19]), I(b20[19]),
         "/TETRA10/61", I(2, 31, 32, 33, 34, 35, 36, 37, 38, 39), I(40)]
    M = _model_from([L], {60, 61})
    assert M.elems[60]["BRIC20"] == [b20[:8]] and M.elems[61]["TETRA10"] == [[31, 32, 33, 34]]
    assert len(A.solid_segments(M, [60], "EXT", "x")) == 6 and len(A.solid_segments(M, [61], "EXT", "x")) == 4
    M2 = A.Model()
    M2.elems = {70: {"BRICK": [_e1()]}, 71: {"BRICK": [[x + 1 for x in _e1()]]}}   # 두 파트가 한 면으로 맞닿음
    assert len(A.solid_segments(M2, [70, 71], "EXT", "x")) == 10              # 맞닿은 면 제외
    assert len(A.solid_segments(M2, [70], "EXT", "x")) == 6
    with pytest.raises(EslError):                                             # 모자란 마지막 요소 → 가짜 면 금지
        _model_from([["/BRIC20/60", I(1, *b20[:9]), I(*b20[9:19])]], {60})


def test_restore_keeps_special_bytes(tmp_path):
    m = model(tmp_path)
    p = m["case"] / "101_parts.inc"
    raw = p.read_bytes().replace(b"/NODE\n", b"/NODE\n#\x85 note\x0c here\r\n", 1)
    p.write_bytes(raw)
    dest, man = stage(m, tmp_path)
    st = (dest / "101_parts.inc").read_bytes()
    assert b"#\x85 note\x0c here" in st                                       # 사본도 그대로(줄 분할 \r?\n)
    of = tmp_path / "of"
    of.mkdir()
    a, b = node(5, 10.0, 10.0, 0.0).encode(), node(5, 10.0, 10.0, 2.0).encode()
    (of / "101_parts.inc").write_bytes(st.replace(a, b))
    assert A.restore_out_files(str(of), ["101_parts.inc"], man) == 1
    assert (of / "101_parts.inc").read_bytes() == raw.replace(a, b)


def test_include_too_deep(tmp_path):
    m = model(tmp_path)
    with pytest.raises(EslError) as e:
        stage(m, tmp_path, max_depth=1)                                   # tie.inc → loop.inc 는 깊이 2
    assert e.value.code == "INCLUDE_TOO_DEEP"


def test_drop_derived_no_backup_inputs_untouched(tmp_path):
    from esl.library import _util as U
    m = model(tmp_path)
    before = tree_sha(m["root"])
    out = tmp_path / "out"
    dest, _ = stage(m, tmp_path)
    w = U.Writer(str(out), inputs=[("Case 입력", str(m["root"]))])
    assert A.drop_derived(str(out), w.guard) == [str(dest)]
    assert not dest.exists() and not (out / "_backup").exists()
    os.symlink(m["root"], out / "prep" / "a_assem_full")                      # 링크면 링크만 제거
    A.drop_derived(str(out), w.guard)
    assert not os.path.lexists(out / "prep" / "a_assem_full") and tree_sha(m["root"]) == before
    (m["root"] / "prep" / "assem_full").mkdir(parents=True)                   # 작업 폴더 밖은 삭제 거부
    with pytest.raises(EslError):
        A.drop_derived(str(m["root"]), w.guard)
    assert (m["root"] / "prep" / "assem_full").is_dir()


@pytest.mark.parametrize("ver,head", [(2024, "#RADIOSS STARTER\n"), (2026, "#RADIOSS STARTER\n#- Radioss 2026.1\n")])
def test_radioss_2024_2026_format(tmp_path, ver, head):
    """2024.1·2026.1 형식: /BEGIN Invers, /SUBSET = title + 하위 subset 목록, 파트 소속 = /PART 3번째 칸,
    /GRNOD/GENE = first·last 쌍(줄당 ≤5), /SURF/SUBSET/EXT."""
    m = model(tmp_path)
    (m["case"] / "model_0000.rad").write_text(
        f"{head}/BEGIN\nmodel\n{I(ver, 0)}\n{I(1, 2, 3)}\n                  Mg                  mm                   s\n"
        "/INCLUDE \"101_parts.inc\"\n/INCLUDE \"../common/tie.inc\"\n/INCLUDE \"../../shared/sets.inc\"\n/END\n")
    (m["root"] / "shared" / "sets.inc").write_text("\n".join([
        "/SUBSET/5", "SUB-SOLIDS", "#    sub_ID1   sub_ID2", I(6),
        "/SUBSET/6", "SUB-TET",
        "/SURF/SUBSET/EXT/1362", "SURF-SUBSET", I(5),
        "/GRNOD/GENE/20", "GLASS-NODES", I(201, 202, 203, 204, 0, 0),
        "/GRNOD/NODE/22", "CHR-NODES", I(1, 2, 3)]) + "\n")
    dest, man = stage(m, tmp_path)
    assert man["subset_format"] == {"setting": "auto", "used": str(ver), "version": ver, "source": "begin"}
    s = (dest / "_ext" / "shared" / "sets.inc").read_text()
    assert len(block(s, "/SURF/SEG/1362")) - 2 == 16 and A._ints(block(s, "/GRNOD/NODE/20")[2]) == [201, 202, 203, 204]


def test_subset_format_legacy_and_header_detect(tmp_path):
    m = model(tmp_path)
    (m["root"] / "shared" / "sets.inc").write_text("\n".join([
        "/SUBSET/5", "OLD STYLE PARTS", I(75, 80),                       # 구형: 데이터 줄에 파트 id
        "/SURF/SUBSET/EXT/1362", "SURF-SUBSET", I(5)]) + "\n")
    (m["case"] / "model_0000.rad").write_text("#RADIOSS STARTER 2024.1\n/INCLUDE \"101_parts.inc\"\n"
                                              "/INCLUDE \"../../shared/sets.inc\"\n")
    with pytest.raises(EslError) as e:                                   # 2024 규칙(머리 주석 판정)에선 오판 대신 오류
        stage(m, tmp_path)
    assert e.value.code == "FIXED_PARSE_FAILED" and "/SURF/SUBSET/EXT/1362" in e.value.message
    d = tmp_path / "leg"
    d.mkdir()
    man = A.copy_model_full(str(m["starter"]), str(m["case"]), [str(m["root"])], str(d), max_mb=10,
                            fixed_scan={"subset_format": "legacy"})
    assert man["subset_format"]["used"] == "legacy" and man["subset_format"]["source"] == "header"
    assert len(block((d / "_ext" / "shared" / "sets.inc").read_text(), "/SURF/SEG/1362")) - 2 == 16
    (m["case"] / "model_0000.rad").write_text("/INCLUDE \"101_parts.inc\"\n")
    assert A.detect_version(str(m["starter"])) == {"version": None, "source": None}
