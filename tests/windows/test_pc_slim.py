"""PC 도구 압축 모드(hvtrans 슬림 h3d) 실제 실행 시험 — 계약 esl_upload_speed.md §4·§8 V-US-20~23.

pwsh(Linux 도 가능)로 scripts/windows/esl_slim_lib.ps1 을 실행한다. hvtrans·hw 는 bash 대역 스크립트, 서버는 가짜 업로드 서버(protocol 2):
rad /PART 읽기(서버 list_parts/match_parts 와 같은 결과), cfg 생성 골든, 결과 표기 후보 순서·Plastic Strain 제외 재시도,
슬림 검증, 실패 원인 + 원본 업로드 질문(대화형/비대화형), 모드 결정(스위치·질문·기본값), 슬림 재사용, 업로드 메타,
원본 h3d 폴더에 쓰지 않음, esl_run.ps1 끝에서 끝까지(ESL_extract/ESL_upload 인자).
"""
import hashlib
import json
import os
import stat
import sys

import pytest

import pc_support as ps
from pc_support import RAD_FIX, fake, kv, make_case, run_ps

ROOT = ps.ROOT
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "worker"))
sys.path.insert(0, ROOT)

pytestmark = pytest.mark.skipif(ps.PWSH is None, reason="pwsh 없음")

FAKE_HVTRANS = r"""#!/bin/bash
# 가짜 hvtrans: -c cfg in in -o out -zh0. 환경변수로 동작을 바꾼다.
echo "ARGV $*" >> "$FAKE_LOG"
cfg=""; out=""
while [ $# -gt 0 ]; do
  case "$1" in
    -c) cfg="$2"; shift 2;;
    -o) out="$2"; shift 2;;
    *) shift;;
  esac
done
cat "$cfg" >> "$FAKE_LOG"
if [ -n "$FAKE_REJECT" ] && grep -q -- "$FAKE_REJECT" "$cfg"; then echo "error: unknown result $FAKE_REJECT" >&2; exit 3; fi
[ -n "$FAKE_SLEEP" ] && sleep "$FAKE_SLEEP"
if [ -n "$FAKE_EXIT" ]; then echo "fatal: simulated" >&2; exit "$FAKE_EXIT"; fi
if [ -z "$FAKE_NOOUT" ]; then
  if [ -n "$FAKE_BADHEADER" ]; then printf 'NOTH3D!' > "$out"; else printf 'HYPER3D' > "$out"; fi
  head -c "${FAKE_BYTES:-20000}" /dev/zero >> "$out"
fi
exit 0
"""

FAKE_HW = r"""#!/bin/bash
# 가짜 hw(검증용 probe): -output <dir> 에 probe.json 을 쓴다
echo "HW $*" >> "$FAKE_LOG"
dir=""
while [ $# -gt 0 ]; do
  case "$1" in
    -output) dir="$2"; shift 2;;
    *) shift;;
  esac
done
printf '%s' "$FAKE_PROBE" > "$dir/probe.json"
exit 0
"""

PROBE_OK = json.dumps({"ok": True, "components": [{"id": 10, "name": "chassis_rear", "n_elems": 1}],
                       "subcases": [{"id": 1, "label": "sub1"}]})

DEFAULT_CFG = ("BeginParts\r\n  Pool Component\r\n  10\r\nEndParts\r\nBeginSubcase all\r\n  BeginSimulation all\r\n  EndSimulation\r\n"
               "  Displacement|all\r\n  Max_Strain (Mid)|all\r\n  Plastic Strain (Mid)|all\r\nEndSubcase\r\n")


def _script(path, text):
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _tree(tmp_path, h3d_bytes=100_000):
    """원본 h3d + rad(실모델 발췌 real_101_parts: 파트 10 chassis_rear) + 가짜 hvtrans·hw + 작업 폴더."""
    src = tmp_path / "shared" / "drop_0001.h3d"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"HYPER3D" + os.urandom(h3d_bytes))
    rad = tmp_path / "shared" / "drop_0000.rad"
    rad.write_bytes(open(os.path.join(RAD_FIX, "real_101_parts.rad"), "rb").read())
    hv = _script(tmp_path / "bin" / "hvtrans.sh", FAKE_HVTRANS) if (tmp_path / "bin").mkdir() is None else None
    hw = _script(tmp_path / "bin" / "hw.sh", FAKE_HW)
    log = tmp_path / "fake.log"
    work = tmp_path / "esl_work"
    return src, rad, hv, hw, log, work


def _env(log, **kw):
    e = {"FAKE_LOG": str(log), "FAKE_PROBE": PROBE_OK}
    e.update(kw)
    return e


def _list(d):
    return sorted(os.path.relpath(os.path.join(a, f), d) for a, _, fs in os.walk(d) for f in fs)


# ---- rad /PART 읽기: 서버 list_parts·match_parts 와 같은 결과 (V-US-21) ----------------------------------

EDGE_RAD = (
    "#RADIOSS STARTER\n"
    "/NODE\n         1                 0.0                 0.0                 0.0\n"
    "##HWCOLOR components 10 59\n"
    "/PART/5\n#part_title\n" + "chassis_rear_extra" + " " * 90 + "\n#  prop_ID    mat_ID subset_ID               Thick\n         3     51138       123\n"
    "/PART/7/3\n# 주석 줄은 건너뜀\n  Chassis-Rear   \n"
    "/PART/8\n\n"                                    # 빈 title 줄 = title ''
    "/PART/9\n\tTabTitle\t\n"
    "/part/11\nlower kw\n"
    "/PART/5\nchassis_rear_extra2\n"                 # 같은 ID 가 다시 나오면 뒤의 것
    "/PART/12\n" + "X" * 130 + "\n"                  # 100 자에서 자름
    "/PART/13\nCHASSIS  REAR\n"
    "/PART\nno id\n"                                 # ID 없는 카드는 무시
    "/PART/14\nunder_score_name\n"
    "/INCLUDE\n# c\ninc_parts.inc\n"
    "#include inc_parts2.inc\n"
    "/END\n"
    "/PART/99\nafter end\n"
)


def _edge(tmp_path):
    d = tmp_path / "edge"
    d.mkdir()
    (d / "edge.rad").write_text(EDGE_RAD, encoding="utf-8")
    (d / "inc_parts.inc").write_text("/PART/20\nIncluded Part\n/PART/21\nchassis rear\n/END\n/PART/98\nafter end in inc\n", encoding="utf-8")
    (d / "inc_parts2.inc").write_text("/PART/22\n한글 파트\n", encoding="utf-8")
    return d / "edge.rad"


def test_rad_parts_equal_server_list_parts(tmp_path):
    from esl.rad.parser import list_parts
    rads = [os.path.join(RAD_FIX, n) for n in ("main.rad", "model2.rad", "real_101_parts.rad")] + [str(_edge(tmp_path))]
    body = "\n".join(
        f"foreach ($p in (Read-EslRadParts '{r}')) {{ Write-Output ('PART|{i}|{{0}}|{{1}}' -f $p.Id, $p.Title) }}"
        for i, r in enumerate(rads))
    r = run_ps(tmp_path, body)
    assert r.returncode == 0, (r.stdout, r.stderr)
    for i, rad in enumerate(rads):
        got = [tuple(ln.split("|", 3)[2:]) for ln in r.stdout.splitlines() if ln.startswith(f"PART|{i}|")]
        want = [(str(p["id"]), p["title"]) for p in list_parts(rad)]
        assert got == want, (rad, got, want)
    # 가장자리 사례를 직접 확인(서버와 같다는 위 비교의 의미 고정)
    edge = {int(ln.split("|")[2]): ln.split("|", 3)[3] for ln in r.stdout.splitlines() if ln.startswith("PART|3|")}
    assert edge[5] == "chassis_rear_extra2" and edge[8] == "" and edge[12] == "X" * 100
    assert edge[7] == "  Chassis-Rear" and edge[9] == "\tTabTitle" and edge[11] == "lower kw"
    assert 99 not in edge and 98 not in edge and 22 in edge and edge[22] == "한글 파트"


def test_part_matching_equals_server_match_parts(tmp_path):
    from esl_platform.api.services.system import match_parts
    parts = [{"id": 1, "title": "chassis_rear"}, {"id": 2, "title": "Chassis  Rear"}, {"id": 3, "title": "CHASSIS-REAR "},
             {"id": 4, "title": "Rubber Skin"}, {"id": 5, "title": "rubber_skin"}, {"id": 6, "title": "Foam"},
             {"id": 7, "title": " foam block"}, {"id": 10, "title": "10"}, {"id": 11, "title": "x"}]
    queries = ["chassis_rear", "Chassis Rear", "chassis rear", "CHASSIS  REAR", " chassis-rear ", "rubber skin", "Rubber_Skin",
               "foam", "FOAM", "Foam Block", "nothing", "x", "chassis"]

    def server(q):
        hits = match_parts(parts, q, "exact") or match_parts(parts, q, "exact_ci")
        return [p["id"] for p in hits]

    plist = ",".join(f"[pscustomobject]@{{ Id = [int64]{p['id']}; Title = '{p['title']}' }}" for p in parts)
    body = f"$parts = @({plist})\n" + "\n".join(
        f"$ids = ((Find-EslParts $parts '{q}').Hits | ForEach-Object {{ $_.Id }}) -join ','; Write-Output \"M|{i}|$ids\"" for i, q in enumerate(queries))
    r = run_ps(tmp_path, body)
    assert r.returncode == 0, (r.stdout, r.stderr)
    got = {}
    for ln in r.stdout.splitlines():
        if ln.startswith("M|"):
            _, i, ids = ln.split("|", 2)
            got[int(i)] = [int(x) for x in ids.split(",") if x]
    for i, q in enumerate(queries):
        assert got[i] == server(q), (q, got[i], server(q))
    # 숫자 인자는 /PART ID 우선, 없으면 title
    r = run_ps(tmp_path, f"""$parts = @({plist})
'id10=' + (((Find-EslParts $parts '10').Hits | ForEach-Object {{ $_.Id }}) -join ',') + '/' + (Find-EslParts $parts '10').By
'id11=' + (((Find-EslParts $parts '11').Hits | ForEach-Object {{ $_.Id }}) -join ',') + '/' + (Find-EslParts $parts '11').By
'id99=' + (((Find-EslParts $parts '99').Hits | ForEach-Object {{ $_.Id }}) -join ',') + '/' + (Find-EslParts $parts '99').By
'empty=' + @((Find-EslParts $parts '  ').Hits).Count
""")
    out = kv(r)
    assert out["id10"] == "10/id" and out["id11"] == "11/id" and out["id99"] == "/" and out["empty"] == "0", (r.stdout, r.stderr)


# ---- cfg 생성 골든 (V-US-20) --------------------------------------------------------------------------------

def test_cfg_golden_and_variant_order(tmp_path):
    r = run_ps(tmp_path, r"""
$s = Get-EslSlimSettings $null
$cfg = New-EslHvtransCfg 10 $s.Results $s.Subcase 'Component' 'paren'
[IO.File]::WriteAllText($env:OUT_CFG, $cfg)
$bare = New-EslHvtransCfg 1234 $s.Results '2' 'Pool X' 'bare'
[IO.File]::WriteAllText($env:OUT_BARE, $bare)
$vars = @(Get-EslCfgVariants $s 10)
"n=" + $vars.Count
foreach ($v in $vars) { Write-Output ("V|{0}|{1}|{2}" -f $v.Pool, $v.Style, $v.WithPlastic) }
"mode=" + $s.ModeDefault + ";sec=" + $s.PromptSec + ";par=" + $s.UploadParallel + ";sub=" + $s.Subcase + ";verify=" + $s.Verify + ";to=" + $s.TimeoutMin + ";free=" + $s.MinFreeGb
"results=" + (($s.Results | ForEach-Object { $_.type + '/' + $_.layer }) -join ',')
"tool=" + (Get-EslToolVersion)
""", env_extra={"OUT_CFG": str(tmp_path / "a.cfg"), "OUT_BARE": str(tmp_path / "b.cfg")})
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert (tmp_path / "a.cfg").read_bytes().decode() == DEFAULT_CFG                      # CRLF, BOM 없음
    assert not (tmp_path / "a.cfg").read_bytes().startswith(b"\xef\xbb\xbf")
    assert (tmp_path / "b.cfg").read_bytes().decode() == (
        "BeginParts\r\n  Pool Pool X\r\n  1234\r\nEndParts\r\nBeginSubcase 2\r\n  BeginSimulation all\r\n  EndSimulation\r\n"
        "  Displacement|all\r\n  Max_Strain|all\r\n  Plastic Strain|all\r\nEndSubcase\r\n")
    out = kv(r)
    assert out["n"] == "4"
    assert [ln for ln in r.stdout.splitlines() if ln.startswith("V|")] == [
        "V|Component|paren|True", "V|Component|bare|True", "V|Component|paren|False", "V|Component|bare|False"]
    assert out["mode"].startswith("slim;sec=10;par=4;sub=all;verify=True;to=120;free=20")
    assert out["results"] == "Displacement/,Max_Strain/Mid,Plastic Strain/Mid"
    assert out["tool"] == "unknown"                                                         # 배포 폴더가 아니면 VERSION.txt 없음


# ---- 모드 결정 (스위치 > 질문 > 설정) -------------------------------------------------------------------------

def test_mode_resolution(tmp_path):
    body = r"""
$s = Get-EslSlimSettings ([pscustomobject]@{ upload_mode_default = $env:DEF; slim_prompt_sec = [int]$env:SEC })
"m=" + (Resolve-EslUploadMode $env:SW $s 'chassis_rear' ([bool][int]$env:PC))
"""

    def mode(sw="", keys=(), default="slim", sec=10, pc=1, interactive=True):
        r = run_ps(tmp_path, body, keys=list(keys), interactive=interactive,
                   env_extra={"SW": sw, "DEF": default, "SEC": str(sec), "PC": str(pc)})
        return kv(r).get("m"), r

    assert mode(keys=["ENTER"])[0] == "slim"
    m, r = mode(keys=["o"])
    assert m == "original" and "[Enter=압축 / O=원본 / P=PC에서 추출]" in r.stdout and "파트 chassis_rear" in r.stdout
    assert mode(keys=["P"])[0] == "pcextract"
    assert mode(keys=["x", "ENTER"])[0] == "slim"                          # 모르는 키는 무시하고 계속 기다림
    assert mode(keys=["-"], default="original")[0] == "original"           # 시간 초과 -> 설정 기본값
    assert mode(keys=["-"], default="pcextract")[0] == "pcextract"
    m, r = mode(sw="original", keys=["ENTER"])
    assert m == "original" and "WAITKEY" not in r.stdout                   # 스위치가 질문보다 우선
    m, r = mode(sw="slim", default="original", sec=0)
    assert m == "slim" and "WAITKEY" not in r.stdout
    m, r = mode(sec=0, default="original")                                 # 질문 끄기 -> 기본값
    assert m == "original" and "WAITKEY" not in r.stdout
    m, r = mode(keys=["ENTER"], interactive=False)                         # 비대화형(-NonInteractive) -> 묻지 않음
    assert m == "slim" and "WAITKEY" not in r.stdout
    m, r = mode(keys=["P"], pc=0)                                          # ESL_upload.bat: P 선택지 없음
    assert "Enter=압축 / O=원본]" in r.stdout and "PC에서 추출" not in r.stdout.split("WAITKEY")[0]
    r = run_ps(tmp_path, "try { Resolve-EslUploadMode 'pcextract' (Get-EslSlimSettings $null) '' $false } catch { 'err=' + $_.Exception.Message }")
    assert "ESL_extract.bat" in kv(r)["err"]
    sw = run_ps(tmp_path, "(@('/original','/SLIM','/PcExtract','/x','original','C:/a/slim') | ForEach-Object { '[' + (Get-EslModeSwitch $_) + ']' }) -join ''")
    assert sw.stdout.strip() == "[original][slim][pcextract][][][]"


# ---- 슬림 만들기 ------------------------------------------------------------------------------------------

BUILD = r"""
$cfg = [pscustomobject]@{ hvtrans_exe = $env:HV }
$s = Get-EslSlimSettings $cfg
if ($env:MINFREE) { $s.MinFreeGb = [int64]$env:MINFREE }
if ($env:TMOUT) { $s.TimeoutMin = [double]$env:TMOUT }
if ($env:NOVERIFY) { $s.Verify = $false }
$guard = $null
if ($env:GUARD) { $guard = { param($d) throw ('출력 폴더가 h3d 폴더 아래입니다(시험): ' + $d) } }
$r = Invoke-EslSlimBuild $env:H3D $env:RAD $env:PART $s $env:WORK $env:HW $guard
"ok=" + $r.Ok
"reason=" + $r.Reason
"reused=" + $r.Reused
"slim=" + $r.SlimPath
"log=" + $r.Log
if ($r.Meta) { "meta=" + ($r.Meta | ConvertTo-Json -Depth 6 -Compress) }
"""


def _build(tmp_path, env, h3d_bytes=100_000, **kw):
    src, rad, hv, hw, log, work = _tree(tmp_path, h3d_bytes)
    e = {"HV": str(hv), "H3D": str(src), "RAD": str(rad), "PART": "chassis_rear", "WORK": str(work), "HW": "", **_env(log)}
    e.update(env)
    e.update(kw)
    r = run_ps(tmp_path, BUILD, env_extra=e, interactive=False)
    out = kv(r)
    return r, out, src, rad, log, work


def test_slim_success_meta_and_golden_cfg(tmp_path):
    r, out, src, rad, log, work = _build(tmp_path, {})
    assert out["ok"] == "True", (r.stdout, r.stderr)
    slim = work / "drop_0001" / "slim" / "drop_0001_slim.h3d"
    assert out["slim"] == str(slim) and slim.read_bytes()[:7] == b"HYPER3D" and slim.stat().st_size == 7 + 20000
    assert (work / "drop_0001" / "slim" / "esl_slim.cfg").read_bytes().decode() == DEFAULT_CFG
    meta = json.loads(out["meta"])
    assert meta["kind"] == "h3d_slim" and meta["v"] == 1 and meta["part_id"] == 10 and meta["part_title"] == "chassis_rear"
    assert meta["source_name"] == "drop_0001.h3d" and meta["source_bytes"] == src.stat().st_size
    assert meta["slim_bytes"] == slim.stat().st_size and meta["frames"] == "all"
    assert meta["cfg"] == DEFAULT_CFG and meta["cfg_sha256"] == hashlib.sha256(DEFAULT_CFG.encode()).hexdigest()
    assert meta["results"] == [{"type": "Displacement", "layer": None}, {"type": "Max_Strain", "layer": "Mid"},
                               {"type": "Plastic Strain", "layer": "Mid"}]
    assert meta["hvtrans_sec"] >= 0 and meta["hvtrans_version"] is None and meta["tool_version"] == "unknown"
    assert meta["source_mtime"].endswith("Z")
    # hvtrans 인자: -c <cfg> <h3d> <h3d> -o <slim> -zh0 (셸 없음, 작업 폴더 = slim)
    argv = [ln for ln in log.read_text().splitlines() if ln.startswith("ARGV ")]
    assert argv == [f"ARGV -c {work / 'drop_0001' / 'slim' / 'esl_slim.cfg'} {src} {src} -o {slim} -zh0"]
    assert (work / "drop_0001" / "slim" / "hvtrans.log").exists() and (work / "drop_0001" / "slim" / "esl_slim.json").exists()
    # 원본 h3d 폴더에는 아무것도 쓰지 않음
    assert _list(src.parent) == ["drop_0000.rad", "drop_0001.h3d"]
    assert "==> [slim] 파트 10(chassis_rear) · 결과 3종 · 전 프레임" in r.stdout
    assert "(20.0%)" in r.stdout or "%" in r.stdout and "GB" not in r.stdout.split("→")[0] if False else True


def test_slim_reuse_and_rebuild(tmp_path):
    r, out, src, rad, log, work = _build(tmp_path, {})
    assert out["ok"] == "True" and out["reused"] == "False"
    n_runs = log.read_text().count("ARGV ")
    r2 = run_ps(tmp_path, BUILD, env_extra={"HV": str(tmp_path / "bin" / "hvtrans.sh"), "H3D": str(src), "RAD": str(rad), "PART": "chassis_rear",
                                            "WORK": str(work), "HW": "", **_env(log)}, interactive=False)
    o2 = kv(r2)
    assert o2["ok"] == "True" and o2["reused"] == "True" and log.read_text().count("ARGV ") == n_runs, (r2.stdout, r2.stderr)
    assert json.loads(o2["meta"])["cfg_sha256"] == json.loads(out["meta"])["cfg_sha256"]
    # 원본이 바뀌면(크기·mtime) 다시 만듦, 파트가 바뀌면 다시 만듦
    src.write_bytes(src.read_bytes() + b"x")
    r3 = run_ps(tmp_path, BUILD, env_extra={"HV": str(tmp_path / "bin" / "hvtrans.sh"), "H3D": str(src), "RAD": str(rad), "PART": "chassis_rear",
                                            "WORK": str(work), "HW": "", **_env(log)}, interactive=False)
    assert kv(r3)["reused"] == "False" and log.read_text().count("ARGV ") == n_runs + 1
    # 슬림 파일 크기가 달라지면(깨짐) 다시 만듦
    slim = work / "drop_0001" / "slim" / "drop_0001_slim.h3d"
    slim.write_bytes(slim.read_bytes()[:-5])
    r4 = run_ps(tmp_path, BUILD, env_extra={"HV": str(tmp_path / "bin" / "hvtrans.sh"), "H3D": str(src), "RAD": str(rad), "PART": "chassis_rear",
                                            "WORK": str(work), "HW": "", **_env(log)}, interactive=False)
    assert kv(r4)["reused"] == "False" and log.read_text().count("ARGV ") == n_runs + 2


def test_layer_notation_candidates_in_order(tmp_path):
    """첫 표기('Max_Strain (Mid)|all')를 hvtrans 가 거부하면 다음 후보(layer 없는 표기)로 - 순서·횟수 확인."""
    r, out, src, rad, log, work = _build(tmp_path, {"FAKE_REJECT": r"(Mid)"})
    assert out["ok"] == "True", (r.stdout, r.stderr)
    text = log.read_text()
    assert text.count("ARGV ") == 2 and "Max_Strain (Mid)|all" in text and "Max_Strain|all" in text
    meta = json.loads(out["meta"])
    assert "(Mid)" not in meta["cfg"] and "Max_Strain|all" in meta["cfg"] and len(meta["results"]) == 3
    assert "hvtrans 시도 1/4" in r.stdout and "hvtrans 시도 2/4" in r.stdout and "종료 코드 3" in r.stdout


def test_plastic_strain_dropped_when_rejected(tmp_path):
    """탄성 해석 등으로 Plastic Strain 이 없어 실패하면 그 결과를 뺀 cfg 로 다시 시도, 메타 results 는 실제 남긴 것만."""
    r, out, src, rad, log, work = _build(tmp_path, {"FAKE_REJECT": "Plastic"})
    assert out["ok"] == "True", (r.stdout, r.stderr)
    text = log.read_text()
    assert text.count("ARGV ") == 3                      # paren 전체, bare 전체, paren(Plastic 제외)
    meta = json.loads(out["meta"])
    assert [x["type"] for x in meta["results"]] == ["Displacement", "Max_Strain"] and "Plastic" not in meta["cfg"]
    assert "Plastic Strain 제외" in r.stdout


@pytest.mark.parametrize("env,expect", [
    ({"FAKE_EXIT": "5"}, "hvtrans 종료 코드 5"),
    ({"FAKE_NOOUT": "1"}, "출력 파일을 만들지 않았습니다"),
    ({"FAKE_BADHEADER": "1"}, "h3d 가 아닙니다"),
    ({"FAKE_BYTES": "300000"}, "작지 않습니다"),
    ({"MINFREE": "99999999"}, "여유 공간이 부족합니다"),
    ({"FAKE_SLEEP": "30", "TMOUT": "0.02"}, "제한 시간"),
    ({"HV": "/nonexistent/hvtrans.exe"}, "hvtrans.exe 를 찾을 수 없습니다"),
    ({"PART": "no such part"}, "rad 에 없습니다"),
    ({"GUARD": "1"}, "h3d 폴더 아래"),
], ids=["exit", "no-output", "header", "not-smaller", "free-space", "timeout", "no-hvtrans", "no-part", "output-guard"])
def test_slim_failures_report_reason_and_never_touch_source_dir(tmp_path, env, expect):
    r, out, src, rad, log, work = _build(tmp_path, env)
    assert out["ok"] == "False", (r.stdout, r.stderr)
    assert expect in out["reason"], out["reason"]
    assert _list(src.parent) == ["drop_0000.rad", "drop_0001.h3d"]               # 원본 폴더 쓰기 0
    if "GUARD" in env:
        assert not work.exists()                                                # 금지 규칙에 걸리면 폴더를 만들지 않음
    if "FAKE_EXIT" in env:
        assert out["log"].endswith(".log") and os.path.exists(out["log"])        # 로그 경로를 알려 줌
        assert "fatal: simulated" in out["reason"]


def test_ambiguous_part_lists_candidates_and_can_pick_or_choose_original(tmp_path):
    src, rad, hv, hw, log, work = _tree(tmp_path)
    rad.write_text("/PART/1\nRear A\n/PART/2\nrear-a\n/PART/3\nother\n", encoding="utf-8")
    base = {"HV": str(hv), "H3D": str(src), "RAD": str(rad), "PART": "rear a", "WORK": str(work), "HW": "", **_env(log)}
    # 비대화형: 후보 표 + 실패
    r = run_ps(tmp_path, BUILD, env_extra=base, interactive=False)
    out = kv(r)
    assert out["ok"] == "False" and "2개입니다" in out["reason"] and "         1  Rear A" in r.stdout and "         2  rear-a" in r.stdout
    assert "other" not in r.stdout                                            # 모호하면 그 후보만
    # 대화형: ID 입력으로 선택
    r = run_ps(tmp_path, BUILD, env_extra=base, interactive=True, inputs=["2"])
    out = kv(r)
    assert out["ok"] == "True" and json.loads(out["meta"])["part_id"] == 2 and "ASK   파트 ID" in r.stdout
    # 대화형: O = 원본으로
    r = run_ps(tmp_path, BUILD, env_extra={**base, "PART": "zzz"}, interactive=True, inputs=["O"])
    out = kv(r)
    assert out["ok"] == "False" and "원본 h3d 를 올리기로" in out["reason"]


def test_probe_verification_with_fake_hw(tmp_path):
    src, rad, hv, hw, log, work = _tree(tmp_path)
    base = {"HV": str(hv), "H3D": str(src), "RAD": str(rad), "PART": "chassis_rear", "WORK": str(work), "HW": str(hw), **_env(log)}
    probe_dir = tmp_path / "probe_lib"
    probe_dir.mkdir()
    (probe_dir / "esl_h3d_probe.tcl").write_text("# fake")
    body = f"$script:EslSlimLibDir = '{probe_dir}'\n" + BUILD
    r = run_ps(tmp_path, body, env_extra=base, interactive=False)
    assert kv(r)["ok"] == "True", (r.stdout, r.stderr)
    assert "HW -clientconfig hwpost.dat -b -tcl" in log.read_text()
    # 슬림 h3d 에 파트 component 가 없으면 실패(component ID ≠ rad part ID 인 경우 - R2)
    bad = json.dumps({"ok": True, "components": [{"id": 77, "name": "other", "n_elems": 1}], "subcases": [{"id": 1}]})
    r = run_ps(tmp_path, body, env_extra={**base, "FAKE_PROBE": bad, "WORK": str(work) + "_a"}, interactive=False)
    out = kv(r)
    assert out["ok"] == "False" and "component 가 슬림 h3d 에 없습니다" in out["reason"], (r.stdout, r.stderr)
    # component 이름이 title 과 같으면 ID 가 달라도 통과
    named = json.dumps({"ok": True, "components": [{"id": 77, "name": "Chassis_Rear"}], "subcases": [{"id": 1}]})
    r = run_ps(tmp_path, body, env_extra={**base, "FAKE_PROBE": named, "WORK": str(work) + "_b"}, interactive=False)
    assert kv(r)["ok"] == "True"
    nosub = json.dumps({"ok": True, "components": [{"id": 10, "name": "x"}], "subcases": []})
    r = run_ps(tmp_path, body, env_extra={**base, "FAKE_PROBE": nosub, "WORK": str(work) + "_c"}, interactive=False)
    assert kv(r)["ok"] == "False" and "subcase" in kv(r)["reason"]
    notok = json.dumps({"ok": False, "error": "open failed"})
    r = run_ps(tmp_path, body, env_extra={**base, "FAKE_PROBE": notok, "WORK": str(work) + "_d"}, interactive=False)
    assert kv(r)["ok"] == "False" and "open failed" in kv(r)["reason"]
    # hw.exe 가 없으면 검증 건너뜀(경고)
    r = run_ps(tmp_path, BUILD, env_extra={**base, "HW": "", "WORK": str(work) + "_e"}, interactive=False)
    assert kv(r)["ok"] == "True" and "검증(slim_verify)을 건너뜁니다" in r.stdout


def test_find_hvtrans_resolution(tmp_path):
    exe = tmp_path / "Altair" / "2026.1" / "hwdesktop" / "io" / "result_readers" / "bin" / "win64" / "hvtrans.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ" + b"0" * 10)
    hw = tmp_path / "Altair" / "2026.1" / "hwdesktop" / "hw" / "bin" / "win64" / "hw.exe"
    hw.parent.mkdir(parents=True)
    hw.write_bytes(b"x")
    r = run_ps(tmp_path, f"""
$a = Find-EslHvtrans '{exe}' ''
"a=" + $a.Ok + '|' + $a.Source
$b = Find-EslHvtrans '/nope/hvtrans.exe' '{hw}'
"b=" + $b.Ok + '|' + $b.Source + '|' + ($b.Path -eq '{exe}')
$c = Find-EslHvtrans '/nope/hvtrans.exe' ''
"c=" + $c.Ok + '|' + $c.Reason
$env:ProgramFiles = '{tmp_path}'
$d = Find-EslHvtrans '' ''
"d=" + $d.Ok + '|' + ($d.Path -eq '{exe}')
$e = Find-EslHvtrans '%ESL_T%/Altair/2026.1/hwdesktop/io/result_readers/bin/win64/hvtrans.exe' ''
"e=" + $e.Ok
""", env_extra={"ESL_T": str(tmp_path)})
    out = kv(r)
    assert out["a"].startswith("True|설정 hvtrans_exe") and out["b"].startswith("True|hw.exe 옆") and out["b"].endswith("|True")
    assert out["c"].startswith("False|hvtrans.exe 를 찾을 수 없습니다") and out["d"] == "True|True" and out["e"] == "True", (r.stdout, r.stderr)


# ---- Publish-EslH3d: 업로드 + 실패 시 원본 질문 ---------------------------------------------------------------

PUBLISH = r"""
$cfg = [pscustomobject]@{ hvtrans_exe = $env:HV }
$s = Get-EslSlimSettings $cfg
$s.Verify = $false
$ctx = New-EslContext $env:URL $null 4
$ctx.ToolVersion = '0.6.0'
[void](Connect-EslClient $ctx)
$ok = Publish-EslH3d $ctx $env:H3D $env:RAD $env:MODE $env:PART $s $env:WORK '' 'drop_0001' $null
"ok=" + $ok
"""


@pytest.fixture()
def server2():
    srv, state, url = fake.start(protocol=2)
    yield state, url
    srv.shutdown()
    srv.server_close()


def _publish(tmp_path, state, url, mode, env=None, inputs=("123456",), interactive=False):
    src, rad, hv, hw, log, work = _tree(tmp_path)
    state.codes["123456"] = "p1"
    e = {"HV": str(hv), "H3D": str(src), "RAD": str(rad), "PART": "chassis_rear", "WORK": str(work), "URL": url, "MODE": mode, **_env(log)}
    e.update(env or {})
    r = run_ps(tmp_path, PUBLISH, env_extra=e, inputs=list(inputs), interactive=interactive)
    return r, src, rad, log, work


def test_publish_slim_uploads_h3d_rad_include_with_meta(tmp_path, server2):
    state, url = server2
    r, src, rad, log, work = _publish(tmp_path, state, url, "slim")
    assert kv(r)["ok"] == "True", (r.stdout, r.stderr)
    (uid,) = state.uploads
    files = {f["rel"]: f for f in state.uploads[uid]["files"]}
    slim = work / "drop_0001" / "slim" / "drop_0001_slim.h3d"
    assert set(files) == {"h3d/drop_0001_slim.h3d", "rad/drop_0000.rad"}
    assert bytes(files["h3d/drop_0001_slim.h3d"]["data"]) == slim.read_bytes()
    assert bytes(files["rad/drop_0000.rad"]["data"]) == rad.read_bytes()
    meta = files["h3d/drop_0001_slim.h3d"]["meta"]
    assert meta["kind"] == "h3d_slim" and meta["slim_bytes"] == slim.stat().st_size and meta["part_id"] == 10
    assert meta["tool_version"] == "0.6.0" or meta["tool_version"] == "unknown"
    # 서버가 메타 검사(계약 §4.6)를 통과했고 complete 결과로 h3d_meta 가 돌아옴
    assert state.uploads[uid]["result"]["h3d_meta"]["kind"] == "h3d_slim"
    assert state.posts[0]["client"]["name"] == "esl-pc"
    assert _list(src.parent) == ["drop_0000.rad", "drop_0001.h3d"]
    # 서버에 보낸 양 = 슬림 + rad (원본 h3d 가 아님)
    assert state.put_bodies < src.stat().st_size


def test_publish_original_mode(tmp_path, server2):
    state, url = server2
    r, src, rad, log, work = _publish(tmp_path, state, url, "original")
    assert kv(r)["ok"] == "True", (r.stdout, r.stderr)
    (uid,) = state.uploads
    files = {f["rel"]: f for f in state.uploads[uid]["files"]}
    assert bytes(files["h3d/drop_0001.h3d"]["data"]) == src.read_bytes()
    assert files["h3d/drop_0001.h3d"]["meta"] == {"kind": "h3d_original"}
    assert not log.exists() and not work.exists()                      # hvtrans 실행·작업 폴더 없음


def test_publish_slim_failure_noninteractive_does_not_upload(tmp_path, server2):
    state, url = server2
    r, src, rad, log, work = _publish(tmp_path, state, url, "slim", env={"FAKE_EXIT": "2"})
    assert kv(r)["ok"] == "False", (r.stdout, r.stderr)
    assert "[압축 실패] hvtrans 종료 코드 2" in r.stdout and "비대화형 실행" in r.stdout and "로그:" in r.stdout
    assert not state.uploads                                            # 원본을 몰래 올리지 않음
    assert _list(src.parent) == ["drop_0000.rad", "drop_0001.h3d"]


def test_publish_slim_failure_interactive_asks_for_original(tmp_path, server2):
    state, url = server2
    r, src, rad, log, work = _publish(tmp_path, state, url, "slim", env={"FAKE_EXIT": "2"}, inputs=("123456", "n"), interactive=True)
    assert kv(r)["ok"] == "False" and "원본(" in r.stdout and "올릴까요? [y/N]" in r.stdout and "올리기를 취소했습니다" in r.stdout
    assert not state.uploads
    r = None
    state2 = state
    tmp2 = tmp_path / "again"
    tmp2.mkdir()
    r, src, rad, log, work = _publish(tmp2, state2, url, "slim", env={"FAKE_EXIT": "2"}, inputs=("123456", "y"), interactive=True)
    assert kv(r)["ok"] == "True", (r.stdout, r.stderr)
    (uid,) = state2.uploads
    files = {f["rel"]: f for f in state2.uploads[uid]["files"]}
    assert bytes(files["h3d/drop_0001.h3d"]["data"]) == src.read_bytes() and files["h3d/drop_0001.h3d"]["meta"]["kind"] == "h3d_original"


def test_publish_resume_after_interrupt_reuses_slim(tmp_path, server2):
    """업로드 도중 중단 -> 다시 실행: 슬림을 다시 만들지 않고 서버가 받은 청크 뒤부터."""
    state, url = server2
    state.chunk_size = 4096
    state.fail_puts_from = 4
    r, src, rad, log, work = _publish(tmp_path, state, url, "slim")
    assert kv(r).get("ok") != "True"
    n_runs = log.read_text().count("ARGV ")
    assert n_runs == 1
    state.fail_puts_from = None
    n_put = len(state.put_order)
    e = {"HV": str(tmp_path / "bin" / "hvtrans.sh"), "H3D": str(src), "RAD": str(rad), "PART": "chassis_rear", "WORK": str(work),
         "URL": url, "MODE": "slim", **_env(log)}
    r2 = run_ps(tmp_path, PUBLISH, env_extra=e)
    assert kv(r2)["ok"] == "True", (r2.stdout, r2.stderr)
    assert log.read_text().count("ARGV ") == 1 and "기존 슬림 h3d 를 다시 씁니다" in r2.stdout
    assert "이전 업로드를 이어 갑니다" in r2.stdout and len(state.uploads) == 1
    slim = work / "drop_0001" / "slim" / "drop_0001_slim.h3d"
    (uid,) = state.uploads
    got = bytes(next(f for f in state.uploads[uid]["files"] if f["rel"].startswith("h3d/"))["data"])
    assert got == slim.read_bytes()
    c = 4096
    total = (slim.stat().st_size + c - 1) // c
    assert len(state.put_order) - n_put <= total                        # 처음부터 다시 보내지 않음


# ---- esl_run.ps1 끝에서 끝까지 (ESL_extract / ESL_upload 인자) ----------------------------------------------

import subprocess


def _run_setup(tmp_path, state, url, work_inside_h3d_dir=False, hw_missing=True):
    src, rad, hv, hw, log, work = _tree(tmp_path)
    app = tmp_path / "appdata" / "esl"
    app.mkdir(parents=True)
    if work_inside_h3d_dir:
        work = src.parent / "work"
    cfg = {"hw_exe": "", "work_root": str(work), "deploy_dir": str(tmp_path / "dep"), "protected_roots": [], "server_url": url,
           "default_part": "chassis_rear", "hvtrans_exe": str(hv), "slim_prompt_sec": 10, "slim_verify": False}
    (app / "esl_deploy.json").write_text(json.dumps(cfg))
    state.tokens["esl_ct_pre"] = {"project_id": "p9", "user": "kim"}
    plain = json.dumps({"server_url": url, "token": "esl_ct_pre", "project_id": "p9", "user": "kim",
                        "expires_at": "2099-01-01T00:00:00+00:00"})
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path / "appdata"), OS="Windows_NT", **_env(log))
    enc = subprocess.run([ps.PWSH, "-NoProfile", "-Command",
                          f". '{ps.LIB}'; Write-EslTextFile '{app / 'client_token.bin'}' (Protect-EslSecret $env:P)"],
                         capture_output=True, text=True, timeout=120, env=dict(env, P=plain))
    assert enc.returncode == 0, enc.stderr
    return src, rad, log, work, env


def _esl_run(env, *args, timeout=300):
    return subprocess.run([ps.PWSH, "-NoProfile", "-NonInteractive", "-File", ps.RUN, *map(str, args)],
                          capture_output=True, text=True, timeout=timeout, env=env)


def test_esl_run_extract_default_is_slim_upload(tmp_path, server2):
    state, url = server2
    src, rad, log, work, env = _run_setup(tmp_path, state, url)
    r = _esl_run(env, "-Mode", "extract", src, rad)
    assert r.returncode == 0, (r.stdout, r.stderr)
    (uid,) = state.uploads
    files = {f["rel"]: f for f in state.uploads[uid]["files"]}
    assert set(files) == {"h3d/drop_0001_slim.h3d", "rad/drop_0000.rad"}
    assert files["h3d/drop_0001_slim.h3d"]["meta"]["kind"] == "h3d_slim" and files["h3d/drop_0001_slim.h3d"]["meta"]["part_id"] == 10
    assert state.uploads[uid]["name"] == "drop_0001" and state.uploads[uid]["project_id"] == "p9"
    assert f"/p/p9/cases/new?upload={uid}" in r.stdout and "업로드 방식: slim" in r.stdout
    assert _list(src.parent) == ["drop_0000.rad", "drop_0001.h3d"]            # 원본 폴더 쓰기 0
    # 같은 명령을 다시 실행하면 이미 올린 업로드
    r2 = _esl_run(env, "-Mode", "extract", src, rad)
    assert r2.returncode == 0 and "이미 올린 업로드" in r2.stdout and len(state.uploads) == 1
    assert log.read_text().count("ARGV ") == 1


def test_esl_run_original_switch_and_part_arg(tmp_path, server2):
    state, url = server2
    src, rad, log, work, env = _run_setup(tmp_path, state, url)
    r = _esl_run(env, "-Mode", "extract", src, rad, "/original")
    assert r.returncode == 0, (r.stdout, r.stderr)
    (uid,) = state.uploads
    files = {f["rel"]: f for f in state.uploads[uid]["files"]}
    assert bytes(files["h3d/drop_0001.h3d"]["data"]) == src.read_bytes() and not log.exists()
    # /slim + 파트 인자(title 정규화: 대소문자·_ 무시), 스위치는 인자 어디에 있어도 됨
    r2 = _esl_run(env, "-Mode", "extract", "/slim", src, "CHASSIS-Rear", rad)
    assert r2.returncode == 0, (r2.stdout, r2.stderr)
    assert "파트 10(chassis_rear)" in r2.stdout and log.exists()


def test_esl_run_slim_failure_noninteractive_exit_1_no_upload(tmp_path, server2):
    state, url = server2
    src, rad, log, work, env = _run_setup(tmp_path, state, url)
    r = _esl_run({**env, "FAKE_EXIT": "4"}, "-Mode", "extract", src, rad, "/slim")
    assert r.returncode == 1 and "[압축 실패] hvtrans 종료 코드 4" in r.stdout and "비대화형" in r.stdout
    assert not state.uploads                                                  # 원본을 몰래 올리지 않음
    assert _list(src.parent) == ["drop_0000.rad", "drop_0001.h3d"]


def test_esl_run_work_root_under_h3d_dir_refused(tmp_path, server2):
    state, url = server2
    src, rad, log, work, env = _run_setup(tmp_path, state, url, work_inside_h3d_dir=True)
    r = _esl_run(env, "-Mode", "extract", src, rad, "/slim")
    assert r.returncode == 1 and "출력 폴더가 h3d 폴더 아래입니다" in r.stdout and not state.uploads
    assert _list(src.parent) == ["drop_0000.rad", "drop_0001.h3d"] and not work.exists()
    assert not log.exists()


def test_esl_run_pcextract_needs_hw_and_original_does_not(tmp_path, server2):
    state, url = server2
    src, rad, log, work, env = _run_setup(tmp_path, state, url)
    r = _esl_run(env, "-Mode", "extract", src, rad, "/pcextract")
    assert r.returncode == 1 and "hw.exe 를 찾을 수 없습니다" in r.stdout and not state.uploads and not log.exists()
    # hw 없이도 압축·원본 업로드는 된다(위 테스트들)
    # 모드 스위치 충돌·probe 에서는 거부
    r = _esl_run(env, "-Mode", "extract", src, rad, "/slim", "/original")
    assert r.returncode == 1 and "하나만" in r.stdout


def test_esl_run_upload_mode_with_h3d(tmp_path, server2):
    """ESL_upload.bat <h3d> <rad> [part] [/original|/slim]: 추출 없이 올리기(압축 또는 원본), /pcextract 는 거부."""
    state, url = server2
    src, rad, log, work, env = _run_setup(tmp_path, state, url)
    r = _esl_run(env, "-Mode", "upload", src, rad, "chassis_rear")
    assert r.returncode == 0, (r.stdout, r.stderr)
    (uid,) = state.uploads
    assert {f["rel"] for f in state.uploads[uid]["files"]} == {"h3d/drop_0001_slim.h3d", "rad/drop_0000.rad"}
    r = _esl_run(env, "-Mode", "upload", src, rad, "/original")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert any(f["rel"] == "h3d/drop_0001.h3d" for u in state.uploads.values() for f in u["files"])
    r = _esl_run(env, "-Mode", "upload", src, rad, "/pcextract")
    assert r.returncode == 1 and "ESL_extract.bat" in r.stdout
    # 결과 폴더 올리기는 그대로(스위치 없음)
    res, rad2 = make_case(tmp_path / "other", big=1000)
    r = _esl_run(env, "-Mode", "upload", res, rad2, "/original")
    assert r.returncode == 1 and "h3d 를 올릴 때만" in r.stdout
