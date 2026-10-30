"""deploy/setup_config.py 순수 로직: 설정 생성·보충(사용자 값 보존), deploy.json 해석·병합, 대시보드 .env(웹 경로) 자동 채움,
server.frontend_root 채움, 대시보드 .env Vite 프록시 키(VITE_ESL_TARGET·SIMDASH_ESL_ENABLED) 추가·이미 있음·보존·백업, 경로 검사."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import setup_config as sc
import yaml
from conftest import ROOT


def _inputs(tmp_path: Path, **deploy) -> dict:
    rt = tmp_path / "rt"
    base = {"install_mode": "repo", "install_root": str(rt), "config_path": str(rt / "config" / "esl_platform.yaml"),
            "db_name": "esl", "db_role": "esl_app", "esl_root": str(tmp_path / "esl_root"),
            "input_roots": [str(tmp_path / "inputs")], "spdm_roots": [str(tmp_path / "spdm")]}
    base.update(deploy)
    (tmp_path / "inputs").mkdir(exist_ok=True)
    return {"mode": "repo", "source_root": str(ROOT), "code_root": str(ROOT), "runtime_dir": str(rt), "stamp": "T1",
            "deploy_defaults": base, "deploy_explicit": {}}


def _run(action: str, inputs: dict) -> dict:
    pl = sc.plan(inputs)
    if action == "write":
        pl["write"] = sc.write(inputs, pl)
    return pl


def test_new_install_creates_valid_config(tmp_path):
    inp = _inputs(tmp_path)
    r = _run("write", inp)
    cfg = Path(r["config_path"])
    d = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert d["profile"] == "prod" and d["server"]["port"] == 8110 and d["server"]["base_path"] == "/esl"
    assert d["storage"]["esl_root"] == sc.fwd(str(tmp_path / "esl_root"))
    assert d["storage"]["input_roots"] == [sc.fwd(str(tmp_path / "inputs"))]
    assert d["auth"]["dashboard_public_login_url"] == "/home/"         # 대시보드 .env 없음 → Vite 기본 /home/
    for n in ("esl.yaml", "library.yaml", "ista6.yaml"):
        assert (cfg.parent / n).is_file(), n
    assert (tmp_path / "esl_root").is_dir()
    assert r["write"]["validation"]["ok"] is True, r["write"]["validation"]
    dj = json.loads((tmp_path / "rt" / "deploy.json").read_text(encoding="utf-8"))
    assert list(dj)[:3] == ["install_mode", "install_root", "db_name"] or dj["install_mode"] == "repo"
    assert "password" not in json.dumps(dj).lower()
    assert cfg.read_text(encoding="utf-8").startswith("# ESL 플랫폼 설정")
    assert r["warnings"] == []


def test_rerun_is_idempotent_and_preserves_user_edits(tmp_path):
    inp = _inputs(tmp_path)
    r1 = _run("write", inp)
    cfg = Path(r1["config_path"])
    text = cfg.read_text(encoding="utf-8").replace("max_memory_gb: 128", "max_memory_gb: 96").replace("port: 8110", "port: 8120")
    cfg.write_text(text, encoding="utf-8")
    (cfg.parent / "esl.yaml").write_text((cfg.parent / "esl.yaml").read_text(encoding="utf-8") + "# 사용자 수정\n", encoding="utf-8")
    inp["deploy_defaults"]["esl_root"] = str(tmp_path / "other_root")    # 기존 deploy.json 값이 우선
    r2 = _run("write", inp)
    assert r2["config_changed"] is False and r2["deploy_changed"] is False and r2["write"]["written"] == []
    d = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert d["worker"]["max_memory_gb"] == 96 and d["server"]["port"] == 8120
    assert d["storage"]["esl_root"] == sc.fwd(str(tmp_path / "esl_root"))
    assert "# 사용자 수정" in (cfg.parent / "esl.yaml").read_text(encoding="utf-8")
    port_row = next(x for x in r2["config_rows"] if x["key"] == "server.port")
    assert port_row["action"].startswith("유지(설정 파일 값")


def test_explicit_argument_overrides_deploy_json(tmp_path):
    inp = _inputs(tmp_path)
    _run("write", inp)
    inp["deploy_explicit"] = {"run_mode": "Background"}
    r = _run("plan", inp)
    assert r["deploy"]["run_mode"] == "Background" and r["deploy_overridden"] == [] and "run_mode" in r["deploy_added"]
    _run("write", inp)
    inp["deploy_explicit"] = {"run_mode": "Interactive"}
    r = _run("plan", inp)
    assert r["deploy_overridden"] == ["run_mode"]


def test_existing_config_empty_storage_filled_and_backup(tmp_path):
    inp = _inputs(tmp_path)
    r1 = _run("write", inp)
    cfg = Path(r1["config_path"])
    t = cfg.read_text(encoding="utf-8")
    t = t.replace(f'["{sc.fwd(str(tmp_path / "inputs"))}"]', "[]")
    cfg.write_text(t, encoding="utf-8")
    r2 = _run("write", inp)
    assert "storage.input_roots" in r2["config_changed_keys"]
    row = next(x for x in r2["config_rows"] if x["key"] == "storage.input_roots")
    assert row["action"] == "빈 값 채움"
    assert r2["write"]["backups"] and Path(r2["write"]["backups"][0]).is_file()
    assert "_backup" in r2["write"]["backups"][0]


def test_old_config_without_library_gets_block(tmp_path):
    inp = _inputs(tmp_path)
    r1 = _run("write", inp)
    cfg = Path(r1["config_path"])
    lines = cfg.read_text(encoding="utf-8").splitlines()
    i = next(i for i, ln in enumerate(lines) if ln.startswith("library:"))
    cfg.write_text("\n".join(lines[:i]) + "\n", encoding="utf-8")
    (cfg.parent / "library.yaml").unlink()
    r2 = _run("write", inp)
    assert "library.config_path" in r2["config_changed_keys"]
    assert yaml.safe_load(cfg.read_text(encoding="utf-8"))["library"] == {"config_path": "library.yaml"}
    assert (cfg.parent / "library.yaml").is_file()
    assert r2["write"]["validation"]["ok"] is True


def test_old_config_gets_p3_keys(tmp_path):
    """P3-UX §6·§9.1: altair·worker.slots·client_token 이 없는 이전 설정 → 예시 값 보충, 사용자 값은 유지."""
    inp = _inputs(tmp_path)
    r1 = _run("write", inp)
    cfg = Path(r1["config_path"])
    text = cfg.read_text(encoding="utf-8")
    lines = text.splitlines()
    out, skip = [], False
    for ln in lines:
        if ln.startswith(("altair:", "commands:", "client_token:")):
            skip = True
            continue
        if skip and (ln.startswith((" ", "#")) or not ln.strip()):
            continue
        skip = False
        if ln.strip().startswith("slots:"):
            continue
        out.append(ln.replace("max_concurrent_hw", "x"))
    cfg.write_text("\n".join(out) + "\n", encoding="utf-8")
    d0 = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert "altair" not in d0 and "slots" not in d0["worker"]
    r2 = _run("write", inp)
    for k in ("altair.hw_exe_path", "altair.max_concurrent_hw", "worker.slots", "client_token.ttl_days"):
        assert k in r2["config_changed_keys"], k
    d = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert d["altair"]["hw_exe_path"] == "C:/Program Files/Altair/2026.1/hwdesktop/hw/bin/win64/hw.exe"
    assert d["altair"]["max_concurrent_hw"] == 2 and d["worker"]["slots"] == 2 and d["client_token"]["ttl_days"] == 30
    assert r2["write"]["validation"]["ok"] is True
    # 사용자가 바꾼 값은 유지
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("slots: 2", "slots: 3"), encoding="utf-8")
    r3 = _run("write", inp)
    assert "worker.slots" not in r3["config_changed_keys"]
    assert yaml.safe_load(cfg.read_text(encoding="utf-8"))["worker"]["slots"] == 3


def test_old_config_without_opt_run_hint_only(tmp_path):
    """v0.7.2: v0.6.0 설정(opt_run 섹션·altair.optistruct_path 없음) → 비활성 그대로(파일 자동 수정 없음) + 안내 경고 1줄."""
    inp = _inputs(tmp_path)
    r1 = _run("write", inp)
    assert sc.OPT_RUN_HINT not in r1["warnings"]                      # 새 설치(예시 = enabled + 경로) → 안내 없음
    cfg = Path(r1["config_path"])
    out, skip = [], False
    for ln in cfg.read_text(encoding="utf-8").splitlines():
        if ln.startswith("opt_run:"):
            skip = True
            continue
        if skip and (ln.startswith((" ", "#")) or not ln.strip()):
            continue
        skip = False
        if ln.strip().startswith("optistruct_path:"):
            continue
        out.append(ln)
    cfg.write_text("\n".join(out) + "\n", encoding="utf-8")
    before = cfg.read_text(encoding="utf-8")
    d0 = yaml.safe_load(before)
    assert "opt_run" not in d0 and "optistruct_path" not in d0["altair"]
    r2 = _run("write", inp)
    assert [w for w in r2["warnings"] if "opt_run" in w] == [sc.OPT_RUN_HINT]
    assert "opt_run.enabled" in sc.OPT_RUN_HINT and "altair.optistruct_path" in sc.OPT_RUN_HINT
    assert not [k for k in r2["config_changed_keys"] if k.startswith("opt_run") or "optistruct" in k]
    d = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert "opt_run" not in d and "optistruct_path" not in d["altair"]
    assert r2["write"]["validation"]["ok"] is True
    assert sc.opt_run_hint({"opt_run": {"enabled": False}, "altair": {"optistruct_path": "C:/x.bat"}}) == sc.OPT_RUN_HINT
    assert sc.opt_run_hint({"opt_run": {"enabled": True}, "altair": {"optistruct_path": "C:/x.bat"}}) is None


def test_flow_style_config_not_rewritten(tmp_path):
    """흐름 표기(예시 dev 설정 복사본)는 줄 편집으로 안전하게 고칠 수 없으면 바꾸지 않고 안내."""
    inp = _inputs(tmp_path)
    cfg = tmp_path / "rt" / "config" / "esl_platform.yaml"
    cfg.parent.mkdir(parents=True)
    t = (ROOT / "config" / "esl_platform.example.yaml").read_text(encoding="utf-8")
    t = t.replace('auth:\n  mode: dashboard', 'auth:\n  mode: dashboard').replace(
        'storage:\n  esl_root: "E:/shared/ESL_WORK"', 'storage: {esl_root: "", input_roots: [], spdm_roots: []}\nx_old:\n  esl_root: "E:/shared/ESL_WORK"')
    t = t.split("x_old:")[0] + "worker:" + t.split("worker:", 1)[1]
    cfg.write_text(t, encoding="utf-8")
    before = cfg.read_text(encoding="utf-8")
    r = _run("write", inp)
    assert cfg.read_text(encoding="utf-8") == before
    assert any("자동으로 보충하지 못했습니다" in w for w in r["warnings"])


def test_dashboard_env_login_url(tmp_path):
    dash = tmp_path / "dash"
    dash.mkdir()
    (dash / ".env").write_text('DATABASE_URL=postgresql://u:Zq9pwXY@127.0.0.1:5434/db\nWINDOWS_WEB_BASE_PATH="web"\n', encoding="utf-8")
    inp = _inputs(tmp_path, dashboard_root=str(dash))
    r = _run("write", inp)
    d = yaml.safe_load(Path(r["config_path"]).read_text(encoding="utf-8"))
    assert d["auth"]["dashboard_public_login_url"] == "/web/"
    assert "Zq9pwXY" not in json.dumps(r, ensure_ascii=False)
    # 사용자가 바꾼 값은 보존, 이전 기본값 "/" 는 대시보드 경로로
    cfg = Path(r["config_path"])
    cfg.write_text(cfg.read_text(encoding="utf-8").replace('"/web/"', '"/custom/"'), encoding="utf-8")
    _run("write", inp)
    assert yaml.safe_load(cfg.read_text(encoding="utf-8"))["auth"]["dashboard_public_login_url"] == "/custom/"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace('"/custom/"', '"/"'), encoding="utf-8")
    inp["dashboard_web_base_path"] = "/home"                    # setup.ps1 이 dashboard-env.ps1 로 읽어 넘긴 값 우선
    _run("write", inp)
    assert yaml.safe_load(cfg.read_text(encoding="utf-8"))["auth"]["dashboard_public_login_url"] == "/home/"


@pytest.mark.parametrize("raw,want,warn", [("", "/home/", False), ("/", "/", False), ("a/b", "/a/b/", False),
                                           ("../x", "", True), ("a b", "", True)])
def test_normalize_web_base(raw, want, warn):
    v, w = sc.normalize_web_base(raw)
    assert v == want and bool(w) == warn


def test_path_checks():
    w, ok = sc.check_paths("E:/shared/ESL_WORK", ["E:/shared/ESL_WORK/in"], [])
    assert not ok and any("겹칩니다" in x for x in w)
    w, ok = sc.check_paths("E:/SPDM/master/esl", [], ["e:/spdm/MASTER"])    # 대소문자 무시(Windows)
    assert not ok and any("spdm_roots" in x for x in w) and any("비어 있습니다" in x for x in w)
    w, ok = sc.check_paths("E:/my work/esl", [], [])
    assert not ok and any("공백" in x for x in w)
    w, ok = sc.check_paths("relative/esl", [], [])
    assert not ok and any("절대경로" in x for x in w)
    w, ok = sc.check_paths("", [], [])
    assert not ok and any("비어 있습니다" in x for x in w)
    w, ok = sc.check_paths("E:/ESL_WORK", ["E:/ESL_IN&OUT"], [])
    assert ok and any("특수문자" in x for x in w)
    assert sc.overlaps("E:/a/b", "e:\\A") and not sc.overlaps("E:/ab", "E:/a")


def test_unsafe_esl_root_not_created(tmp_path):
    inp = _inputs(tmp_path, esl_root=str(tmp_path / "bad dir"))
    r = _run("write", inp)
    assert not (tmp_path / "bad dir").exists() and r["esl_root_ok"] is False
    assert r["write"]["validation"]["ok"] is False                        # 플랫폼 설정 검증도 거부


def test_merge_deploy_lists_and_strings():
    d, added, _ = sc.merge_deploy({"input_roots": "E:/in", "pg_bin": ""}, {"pg_bin": "E:/pg/bin", "spdm_roots": []}, {})
    assert d["input_roots"] == ["E:/in"]                                  # PS 5.1 ConvertTo-Json 단일 원소 → 문자열
    assert d["pg_bin"] == "E:/pg/bin"                                     # 비어 있으면 기본값(대시보드 환경)으로
    assert d["spdm_roots"] == [] and "spdm_roots" in added
    assert sc.as_list(None) == [] and sc.as_list(["a\\b", " ", "c"]) == ["a/b", "c"]
    assert sc.as_list({"value": ["E:/x"], "Count": 1}) == ["E:/x"]          # PS 5.1 이 PSObject 배열을 감싼 형태


def test_bundle_mode_does_not_write_deploy_json(tmp_path):
    dj = tmp_path / "deploy.json"
    dj.write_text(json.dumps({"install_root": str(tmp_path / "rt"), "esl_root": str(tmp_path / "esl_root"),
                              "input_roots": [str(tmp_path / "inputs")], "pg_bin": ""}), encoding="utf-8")
    before = dj.read_text(encoding="utf-8")
    inp = _inputs(tmp_path)
    inp.update({"mode": "bundle", "deploy_path": str(dj)})
    inp["deploy_defaults"] = {"pg_bin": "E:/pg", "config_path": str(tmp_path / "rt" / "config" / "esl_platform.yaml")}
    r = _run("write", inp)
    assert dj.read_text(encoding="utf-8") == before and r["deploy_write"] is False
    assert r["deploy"]["pg_bin"] == "E:/pg"
    assert r["write"]["validation"]["ok"] is True


def test_cli_plan_out_file(tmp_path):
    inp = _inputs(tmp_path)
    f = tmp_path / "in.json"
    f.write_text(json.dumps(inp), encoding="utf-8")
    out = tmp_path / "out.json"
    assert sc.main(["plan", "--inputs", str(f), "--out", str(out)]) == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    assert "config_text" not in d and d["config_source"] == "example"
    assert not Path(d["config_path"]).exists()                           # plan 은 파일을 바꾸지 않음


# ---------------------------------------------------------------- 대시보드 Vite 프록시 + 백엔드 정적 서빙(기본 연결)
def test_frontend_root_filled_for_repo_install(tmp_path):
    """git 폴더 설치: server.frontend_root = <런타임>/frontend(deploy.json caddy_frontend_root). 키가 없을 때만 — 바꾼 값·null 은 유지."""
    inp = _inputs(tmp_path)
    r = _run("write", inp)
    cfg = Path(r["config_path"])
    assert yaml.safe_load(cfg.read_text(encoding="utf-8"))["server"]["frontend_root"] == sc.fwd(str(tmp_path / "rt" / "frontend"))
    assert r["write"]["validation"]["ok"] is True
    # 사용자 값 유지(null = Caddy 등 외부 서빙, 다른 경로)
    for user in ("null", '"D:/other/frontend"'):
        t = cfg.read_text(encoding="utf-8")
        t = "\n".join(("  frontend_root: " + user) if ln.startswith("  frontend_root:") else ln for ln in t.split("\n"))
        cfg.write_text(t, encoding="utf-8")
        r2 = _run("write", inp)
        assert "server.frontend_root" not in r2["config_changed_keys"]
        assert yaml.safe_load(cfg.read_text(encoding="utf-8"))["server"]["frontend_root"] == yaml.safe_load(user)
    # 이전 설정(키 없음) → 보충
    t = "\n".join(ln for ln in cfg.read_text(encoding="utf-8").split("\n") if not ln.startswith("  frontend_root:"))
    cfg.write_text(t, encoding="utf-8")
    r3 = _run("write", inp)
    assert "server.frontend_root" in r3["config_changed_keys"]
    assert yaml.safe_load(cfg.read_text(encoding="utf-8"))["server"]["frontend_root"] == sc.fwd(str(tmp_path / "rt" / "frontend"))
    row = next(x for x in r3["config_rows"] if x["key"] == "server.frontend_root")
    assert row["action"] == "보충"


def test_frontend_root_from_deploy_json(tmp_path):
    inp = _inputs(tmp_path, caddy_frontend_root=str(tmp_path / "fe"))
    r = _run("plan", inp)
    assert yaml.safe_load(r["config_text"])["server"]["frontend_root"] == sc.fwd(str(tmp_path / "fe"))


def test_bundle_mode_keeps_frontend_root_null_and_env_untouched(tmp_path):
    """묶음 설치는 Caddy 기준: server.frontend_root 는 예시 값(null), 대시보드 .env 는 건드리지 않는다."""
    dash = tmp_path / "dash"
    dash.mkdir()
    (dash / ".env").write_text("X=1\n", encoding="utf-8")
    inp = _inputs(tmp_path, dashboard_root=str(dash))
    inp["mode"] = "bundle"
    r = _run("write", inp)
    assert yaml.safe_load(Path(r["config_path"]).read_text(encoding="utf-8"))["server"]["frontend_root"] is None
    assert r["dashboard_env"] is None and (dash / ".env").read_text(encoding="utf-8") == "X=1\n"


def test_dashboard_env_keys_added_with_backup(tmp_path):
    """대시보드 .env: VITE_ESL_TARGET·SIMDASH_ESL_ENABLED 를 끝에 추가(BOM·CRLF·다른 줄 보존), 바꾸기 전 _backup 복사."""
    dash = tmp_path / "dash"
    dash.mkdir()
    orig = "\ufeffDATABASE_URL=postgresql://u:Zq9pwXY@127.0.0.1:5434/db\r\nWINDOWS_WEB_BASE_PATH=/home/\r\nVITE_PHYSICSAI_TARGET=http://127.0.0.1:8100"
    (dash / ".env").write_bytes(orig.encode("utf-8"))
    inp = _inputs(tmp_path, dashboard_root=str(dash))
    p = _run("plan", inp)
    assert [(x["key"], x["action"]) for x in p["dashboard_env"]["rows"]] == [("VITE_ESL_TARGET", "추가"), ("SIMDASH_ESL_ENABLED", "추가")]
    assert (dash / ".env").read_bytes() == orig.encode("utf-8")              # plan 은 바꾸지 않음
    r = _run("write", inp)
    raw = (dash / ".env").read_bytes()
    assert raw == (orig + "\r\nVITE_ESL_TARGET=http://127.0.0.1:8110\r\nSIMDASH_ESL_ENABLED=true\r\n").encode("utf-8")
    bk = tmp_path / "rt" / "_backup" / "T1" / "dashboard.env"
    assert bk.read_bytes() == orig.encode("utf-8") and str(bk) in r["write"]["backups"]
    assert r["write"]["dashboard_env"] == {"added": ["VITE_ESL_TARGET", "SIMDASH_ESL_ENABLED"], "backup": str(bk)}
    assert "Zq9pwXY" not in json.dumps(r, ensure_ascii=False)
    # 다시 실행: 이미 있음 → 쓰지 않고 백업도 없음
    inp["stamp"] = "T2"
    r2 = _run("write", inp)
    assert [x["action"] for x in r2["dashboard_env"]["rows"]] == ["이미 있음", "이미 있음"]
    assert (dash / ".env").read_bytes() == raw and r2["write"]["dashboard_env"]["added"] == []
    assert not (tmp_path / "rt" / "_backup" / "T2" / "dashboard.env").exists()


def test_dashboard_env_existing_values_preserved(tmp_path):
    """이미 있는 키는 값이 달라도 바꾸지 않는다(경고). 따옴표·끝 '/'·yes 등은 같은 값으로 본다. 포트는 설정 server.port."""
    dash = tmp_path / "dash"
    dash.mkdir()
    (dash / ".env").write_text('VITE_ESL_TARGET="http://127.0.0.1:8110/"\nSIMDASH_ESL_ENABLED=yes\n', encoding="utf-8")
    inp = _inputs(tmp_path, dashboard_root=str(dash))
    r = _run("write", inp)
    assert [x["action"] for x in r["dashboard_env"]["rows"]] == ["이미 있음", "이미 있음"] and r["warnings"] == []
    cfg = Path(r["config_path"])
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("port: 8110", "port: 8120"), encoding="utf-8")
    (dash / ".env").write_text("SIMDASH_ESL_ENABLED=false\nVITE_ESL_TARGET=http://127.0.0.1:8110\n", encoding="utf-8")
    before = (dash / ".env").read_bytes()
    r2 = _run("write", inp)
    rows = {x["key"]: x for x in r2["dashboard_env"]["rows"]}
    assert rows["VITE_ESL_TARGET"]["action"] == "유지(다른 값)" and rows["VITE_ESL_TARGET"]["want"] == "http://127.0.0.1:8120"
    assert rows["SIMDASH_ESL_ENABLED"]["action"] == "유지(다른 값)"
    assert (dash / ".env").read_bytes() == before
    assert sum("그대로 둡니다" in w for w in r2["warnings"]) == 2


def test_dashboard_env_partial_and_missing(tmp_path):
    dash = tmp_path / "dash"
    dash.mkdir()
    inp = _inputs(tmp_path, dashboard_root=str(dash))
    r = _run("write", inp)                                                  # .env 없음 → 만들지 않고 안내
    assert not (dash / ".env").exists() and r["dashboard_env"]["exists"] is False
    assert any("대시보드 .env가 없습니다" in w for w in r["warnings"])
    (dash / ".env").write_bytes(b"SIMDASH_ESL_ENABLED=true")              # 줄바꿈 없는 한 줄 → Windows 줄 끝(CRLF)
    r = _run("write", inp)
    assert (dash / ".env").read_bytes() == b"SIMDASH_ESL_ENABLED=true\r\nVITE_ESL_TARGET=http://127.0.0.1:8110\r\n"
    assert r["write"]["dashboard_env"]["added"] == ["VITE_ESL_TARGET"]
    (dash / ".env").write_bytes(b"A=1\n")                                   # LF 파일은 LF 로
    _run("write", inp)
    assert (dash / ".env").read_bytes() == b"A=1\nVITE_ESL_TARGET=http://127.0.0.1:8110\nSIMDASH_ESL_ENABLED=true\n"
    (tmp_path / "x").mkdir()
    assert _run("plan", _inputs(tmp_path / "x"))["dashboard_env"] is None   # dashboard_root 없음


def test_bundle_legacy_backend_serves_frontend_migrates_to_config(tmp_path):
    """이전 묶음 deploy.json "backend_serves_frontend": true(작업 인자 --frontend 방식) → server.frontend_root 로 이어받음."""
    inp = _inputs(tmp_path, backend_serves_frontend=True, caddy_frontend_root=str(tmp_path / "fe"))
    inp["mode"] = "bundle"
    r = _run("write", inp)
    assert yaml.safe_load(Path(r["config_path"]).read_text(encoding="utf-8"))["server"]["frontend_root"] == sc.fwd(str(tmp_path / "fe"))


# ---------------------------------------------------------------- P3-UX: 업로드 위치(storage.upload_root)
def test_upload_root_default_created_and_in_input_roots(tmp_path):
    inp = _inputs(tmp_path)
    r = _run("write", inp)
    want = sc.fwd(str(tmp_path / "esl-input"))                     # <esl_root 부모>/esl-input
    assert r["upload_root"] == want and r["upload_root_ok"] is True
    d = yaml.safe_load(Path(r["config_path"]).read_text(encoding="utf-8"))
    assert d["storage"]["upload_root"] == want and d["storage"]["browse_spdm"] is False
    assert (tmp_path / "esl-input").is_dir() and want in r["write"]["created"]
    dj = json.loads((tmp_path / "rt" / "deploy.json").read_text(encoding="utf-8"))
    assert dj["upload_root"] == want
    assert r["write"]["validation"]["ok"] is True
    from esl_platform.core.config import load_config

    lc = load_config(r["config_path"], environ={})
    assert any(sc.fwd(x) == want for x in lc.settings.storage.input_roots)       # input_roots 에 자동 포함
    r2 = _run("write", inp)                                                         # 다시 실행 = 변경 없음
    assert r2["config_changed"] is False and r2["deploy_changed"] is False


def test_upload_root_explicit_and_overlap_rejected(tmp_path):
    inp = _inputs(tmp_path, upload_root=str(tmp_path / "my_up"))
    r = _run("plan", inp)
    assert r["upload_root"] == sc.fwd(str(tmp_path / "my_up"))
    inp = _inputs(tmp_path, upload_root=str(tmp_path / "esl_root" / "up"))
    r = _run("write", inp)
    assert r["upload_root_ok"] is False and any("ESL 루트" in w and "겹칩니다" in w for w in r["warnings"])
    assert not (tmp_path / "esl_root" / "up").exists()
    d = yaml.safe_load(Path(r["config_path"]).read_text(encoding="utf-8"))
    assert d["storage"]["upload_root"] is None                       # 겹치는 값은 쓰지 않음(예시 null 유지)
    w, ok = sc.check_upload_root("E:/SPDM/master/up", "E:/esl-data", ["e:/spdm/MASTER"])
    assert not ok and any("SPDM" in x for x in w)
    assert sc.default_upload_root("E:/VD_SIMULATION_WEB/esl-data") == "E:/VD_SIMULATION_WEB/esl-input"
    assert sc.default_upload_root("") == "" and sc.default_upload_root("rel/x") == ""


def test_old_config_without_upload_root_gets_filled(tmp_path):
    inp = _inputs(tmp_path)
    r1 = _run("write", inp)
    cfg = Path(r1["config_path"])
    lines = [ln for ln in cfg.read_text(encoding="utf-8").splitlines(keepends=True) if "upload_root:" not in ln]
    cfg.write_text("".join(lines), encoding="utf-8")
    dj = tmp_path / "rt" / "deploy.json"
    d0 = json.loads(dj.read_text(encoding="utf-8"))
    d0.pop("upload_root")
    dj.write_text(json.dumps(d0), encoding="utf-8")
    r2 = _run("write", inp)                                          # 업데이트(update-repo)와 같은 경로
    assert "storage.upload_root" in r2["config_changed_keys"] and "upload_root" in r2["deploy_added"]
    assert yaml.safe_load(cfg.read_text(encoding="utf-8"))["storage"]["upload_root"] == sc.fwd(str(tmp_path / "esl-input"))


def test_scx_dashboard_root_autodetect(tmp_path):
    """v0.12.0: hpc.scx.secret_file "" + dashboard_root 비어 있음 → esl 설치 폴더의 형제 중 대시보드(backend/app/services/drive/
    config.py 가 있는 폴더)를 찾아 hpc.scx.dashboard_root 보충(1줄). 없으면 그대로, 설정 검증 통과."""
    (tmp_path / "a").mkdir()
    r0 = _run("write", _inputs(tmp_path / "a"))                       # 형제에 대시보드 없음 → 보충 안 함
    assert r0["scx_autodetect"] == {"added": {}, "candidate": None} and r0["write"]["scx_autodetect"]["line"] is None
    base = tmp_path / "b"
    dash = base / "simdashboard"
    (dash / "backend" / "app" / "services" / "drive").mkdir(parents=True)
    (dash / "backend" / "app" / "services" / "drive" / "config.py").write_text("# dashboard\n")
    (base / "other").mkdir()
    inp = _inputs(base)
    r = _run("write", inp)
    want = sc.fwd(str(dash))
    assert r["scx_autodetect"]["added"] == {"hpc.scx.dashboard_root": want}
    assert "hpc.scx.dashboard_root" in r["write"]["scx_autodetect"]["line"]
    d = yaml.safe_load(Path(r["config_path"]).read_text(encoding="utf-8"))
    assert d["hpc"]["scx"]["dashboard_root"] == want and d["hpc"]["scx"]["secret_file"] == ""
    assert r["write"]["validation"]["ok"] is True, r["write"]["validation"]
    # 다시 돌려도 이미 값이 있으면 바꾸지 않음
    assert _run("write", inp)["scx_autodetect"]["added"] == {}
