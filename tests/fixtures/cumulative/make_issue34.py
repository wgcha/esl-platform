"""이슈 #34 실데이터 발췌 기반 fixture 생성(V-CI-P1). 생성 결과(issue34/)를 커밋한다 — 다시 만들 때만 실행.

- .str: 헤더·/BEGIN·/SHELL/         2 (요소 9개, THK 81–100열)·/TETRA4/        22·310·/NODE 첫 4행은 이슈 원문 그대로.
  쉘이 참조하는 노드(100970–100978, 101039–101047)는 같은 형식(I10 + F20×3, 음수면 공백 없이 붙음)으로 추가.
- .sta: /BEGIN·주석 7행·EPSP_F 블록 구조는 원문 그대로, 값은 집계 시험을 위해 일부 0 이 아닌 값으로 바꿈
  (100001: 0.001·(IPT·10+IPG), 100002: IPT 3 만 0.02, 100009: NPT=0·NPG=4 레코드 추가, 100006–100008 없음
  → STATE_PARTIAL). 비대상 블록(101054…, NPT=0 2091792…)·/INIBRI/STRA_F·/INIBRI/FAIL 는 원문 그대로.
- 주 rad: /BEGIN(같은 단위)·/PART/2 Chassis_Rear·/PROP/SHELL/2 (Thick 1.2)·/MAT/LAW2/2, 상태 파일 #include.
"""
from __future__ import annotations

import os

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "issue34")
RUN = "10_Edge_Drop_Scene07_Edge23_1st"
BEGIN = f"""/BEGIN
{RUN}
      2024         0
 1.0000000610352E+03 1.0000000474975E-03 1.0000000000000E+00
 1.0000000610352E+03 1.0000000474975E-03 1.0000000000000E+00
"""
SHELLS = [
    (100001, 100974, 100975, 101039, 100973, 1.1995980739594),
    (100002, 100973, 101039, 101040, 100972, 1.1986042261124),
    (100003, 100975, 100976, 101041, 101039, 1.2000597715378),
    (100004, 100972, 101040, 101042, 100971, 1.2001813650131),
    (100005, 100976, 100977, 101043, 101041, 1.1990697383881),
    (100006, 101039, 101041, 101044, 101040, 1.1992698907852),
    (100007, 100971, 101042, 101045, 100970, 1.1997190713882),
    (100008, 100977, 100978, 101046, 101043, 1.1993740797043),
    (100009, 101040, 101044, 101047, 101042, 1.1983038187027),
]
NODE_HEAD = [
    "    100001-4.4584247589111E+01-4.7285476684570E+01 2.0049779415131E+00",
    "    100002 6.1656719207764E+01-1.5657220458984E+02-2.5318062305450E-01",
    "    100003 5.6714900970459E+01-1.5135275268555E+02-1.5555009245872E-01",
    "    100004 5.1739978790283E+01-1.4624311828613E+02-6.1429217457771E-02",
]
COMMENT7 = """#---1----|----2----|----3----|----4----|----5----|----6----|----7----|----8----|----9----|----10---|
/INISHE/EPSP_F
#------------------------ REPEAT --------------------------
#  SHELLID, NPT, NPG, THK
# REPEAT IPT=1,MAX(1,NPT) : REPEAT IPG=1,NPG : EPSP(IPG,IPT)
#---------------------- END REPEAT ------------------------
#---1----|----2----|----3----|----4----|----5----|----6----|----7----|----8----|----9----|----10---|
"""


def f20(v: float) -> str:
    return f"{v:20.13E}"


def node_xyz(nid: int):
    """노드 좌표(결정적): 행 100970–100978 · 101039–101047 을 5 mm 격자 근처에 둔다."""
    if nid >= 101039:
        i, j = nid - 101039, 1
    else:
        i, j = nid - 100970, 0
    return (-40.0 + 5.0 * i + 0.013 * j, -47.0 - 5.0 * j - 0.021 * i, 2.0 + 0.0123 * i * j - 0.004 * i)


def vals_line(vs):
    return "".join(f20(v) for v in vs)


def record(sid, npt, npg, thk, vals):
    out = [f"{sid:10d}{npt:10d}{npg:10d}{f20(thk)}"]
    for k in range(0, len(vals), 5):
        out.append(vals_line(vals[k:k + 5]))
    return out


def epsp_100001():
    return [0.001 * (ipt * 10 + ipg) for ipt in range(1, 6) for ipg in range(1, 5)]   # IPG 빠름


def epsp_100002():
    return [0.02 if ipt == 3 else 0.0 for ipt in range(1, 6) for ipg in range(1, 5)]


def main():
    os.makedirs(HERE, exist_ok=True)
    nodes = sorted({n for s in SHELLS for n in s[1:5]})
    lines = [f"#RADIOSS STATE FILE {RUN}_0002.sta", BEGIN.rstrip("\n"), "/SHELL/         2",
             "#  SHELLID      NOD1      NOD2      NOD3      NOD4                                THK"]
    for s in SHELLS:
        lines.append("".join(f"{v:10d}" for v in s[:5]) + " " * 30 + " " + f"{s[5]:.13E}".rjust(19))
    lines += ["", "", "/TETRA4/        22", "# TETRA4ID      NOD1      NOD2      NOD3      NOD4",
              "    706053    530713    309378    309380    307200", "/TETRA4/       310",
              "# TETRA4ID      NOD1      NOD2      NOD3      NOD4",
              "   2794814    897395    928071    897393    897396", "   2534936    921191    921193    921163    921192",
              "   2826424    936882    928748    902885    936885", "/TETRA4/        22",
              "# TETRA4ID      NOD1      NOD2      NOD3      NOD4", "    410293    335569    583812    335565    335566",
              "/NODE", "#    NODID               XCOOR               YCOOR               ZCOOR"]
    lines += NODE_HEAD
    for n in nodes:
        lines.append(f"{n:10d}" + "".join(f20(c) for c in node_xyz(n)))
    with open(os.path.join(HERE, f"{RUN}_0002.str"), "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")

    sta = ["", "", BEGIN.rstrip("\n"), COMMENT7.rstrip("\n").split("\n")[0]] + COMMENT7.rstrip("\n").split("\n")[1:]
    thk = {s[0]: s[5] for s in SHELLS}
    zero20 = [0.0] * 20
    sta += record(100001, 5, 4, thk[100001], epsp_100001())
    sta += record(100002, 5, 4, thk[100002], epsp_100002())
    for sid in (100003, 100004, 100005):
        sta += record(sid, 5, 4, thk[sid], zero20)
    sta += ["", ""] + COMMENT7.rstrip("\n").split("\n")
    sta += record(101054, 5, 4, 1.5999954938889, zero20) + record(101055, 5, 4, 1.6005058288574, zero20)
    sta += ["", ""] + COMMENT7.rstrip("\n").split("\n")
    sta += record(100009, 0, 4, thk[100009], [0.004, 0.003, 0.002, 0.001])
    sta += ["", ""] + COMMENT7.rstrip("\n").split("\n")
    for sid, t in ((2091792, 1.4193460941315), (2091793, 1.4193805456161), (2091794, 1.4193440675735)):
        sta += record(sid, 0, 4, t, [0.0] * 4)
    sta += ["", "",
            "#---1----|----2----|----3----|----4----|----5----|----6----|----7----|----8----|----9----|----10---|",
            "/INIBRI/STRA_F",
            "#------------------------ REPEAT -------------------------",
            "#  BRICKID      NPT    ISOLNOD    ISOLID",
            "# IF(NPT /= 0) REPEAT K=1,NPT",
            "#    E1,  E2,  E3",
            "#   E12, E23, E31",
            "#------------------------ REPEAT -------------------------",
            "#---1----|----2----|----3----|----4----|----5----|----6----|----7----|----8----|----9----|----10---|",
            "    924269         1         4         1",
            "-3.5189106711186E-04-4.5962637523189E-04-3.3091797376983E-04",
            "-3.0851305928081E-04 3.1190240406431E-04 2.4872072390281E-04",
            "    924271         1         4         1",
            "-3.5247433697805E-04-3.0561853782274E-04-3.5140171530657E-04",
            " 9.5004994363990E-05 1.3068412954453E-04 2.7573993429542E-04",
            "", "",
            "#------------------------ REPEAT --------------------------",
            "#  BRICKID      NLAY      NPTR      NPTS      NPTT      ILAY     IRUPT IRUPT_TYP     NUVAR      IMAT",
            "# REPEAT K=1,NPTR,NPTS*NPTT*NLAY",
            "#  UVAR(1,I) .............",
            "#    ...............              UVAR(NUVAR,I)",
            "#---------------------- END REPEAT ------------------------",
            "#---1----|----2----|----3----|----4----|----5----|----6----|----7----|----8----|----9----|----10---|",
            "#---1----|----2----|----3----|----4----|----5----|----6----|----7----|----8----|----9----|----10---|",
            "/INIBRI/FAIL"]
    with open(os.path.join(HERE, f"{RUN}_0002.sta"), "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(sta) + "\n")

    rad = [BEGIN.rstrip("\n").replace(RUN, "10_Edge_Drop_Scene07_Edge23_2nd"),
           "/PART/2", "Chassis_Rear", f"{2:10d}{2:10d}",
           "/PART/22", "Bracket", f"{22:10d}{2:10d}",
           "/PART/310", "Foam", f"{310:10d}{2:10d}",
           "/PROP/SHELL/2", "shell_t1p2",
           f"{24:10d}{0:10d}{0:10d}{0:10d}{0:10d}",
           "".join(f20(0.0) for _ in range(5)),
           f"{5:10d}{0:10d}{f20(1.2)}{f20(0.0)}",
           "/MAT/LAW2/2", "steel", f20(7.85e-9), f"{f20(2.1e5)}{f20(0.3)}",
           f"#include {RUN}_0002.str",
           f"#include {RUN}_0002.sta",
           "/END"]
    with open(os.path.join(HERE, "Scene07_Edge23_2nd_0000.rad"), "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(rad) + "\n")


if __name__ == "__main__":
    main()
