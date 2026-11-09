"""비드 최적화 코어(esl.opt) 백엔드 어댑터 — 플랫폼 백엔드가 코어를 import 하는 곳(워커 ``core_adapter`` 와 같은 규칙,
정적 시험 test_core_called_only_via_adapter 가 허용하는 두 번째 파일).

계약 esl_opt_run.md §15 경계: 백엔드는 수 초 이내의 가벼운 코어 함수만 쓴다 — ``esl.opt`` 의 settings·DEFAULTS·
load_method_sources, ``size``(S2 크기 규칙), ``identity``(topo_sha256), ``mesh_check``·``femread``(템플릿 검사),
``keepout``(금지 영역·평면도), ``modes``(변형 모드 지연 분류), 템플릿 메시 정렬 ``target.build_template``, 라이브러리 항목
읽기·``opt_meta``(``esl.library.entry``). 쉘 솔버·대형 rad 파싱·덱·후처리는 워커(O3) 몫이라 여기 없다.

v0.9.0 비드 DOE(esl_bead_doe.md §17 경계): ``esl.doe`` 의 settings·commands·메시지·방법·출처(``doe_*``),
``doe_matrix``(행렬 생성 — API 와 워커가 같은 함수), ``doe_paicad_io``(준비 결과 JSON 읽기·셀 상태 — 실행 없음),
``doe_scenario``(조립 폴더 크기·링크 검사, 물성·요소 크기 기본값). paicad·gmsh·쉘 솔버는 워커만.
v0.15.0 select: ``doe_bead_select``(선택 정규화·sha·사면/경계 derive·평면도 자료 — numpy·scipy 만, 외부 명령 없음).
v0.16.0 ④ 메시 입력: ``rad_deck``(``esl.rad.parser._Deck`` 1차 ``scan`` 만 — 파트·쉘 블록 행 수, check-inputs 파트 목록).
이슈 #53: ``fsutil``(``esl.fsutil`` — Windows 잠금 재시도 원자적 교체, 플랫폼은 ``esl_platform.core.atomic`` 으로 씀).

사용: ``from ...core.opt_core import EslError, keepout, modes`` (모듈은 처음 쓸 때 불러온다 — PEP 562).
"""

from __future__ import annotations

import importlib
from typing import Any

from esl.errors import EslError  # noqa: F401 - 서비스가 여기서 import

_MODULES = {
    "size": "esl.opt.size", "identity": "esl.opt.identity", "mesh_check": "esl.opt.mesh_check",
    "femread": "esl.opt.femread", "keepout": "esl.opt.keepout", "modes": "esl.opt.modes", "target": "esl.opt.target",
    "library_entry": "esl.library.entry",
    "doe_matrix": "esl.doe.matrix", "doe_paicad_io": "esl.doe.paicad_io", "doe_scenario": "esl.doe.scenario",
    # v0.15.0 select(esl_bead_select.md §17 경계): normalize·derive·plan_data 만(기저·모핑·품질·렌더는 워커)
    "doe_bead_select": "esl.doe.bead_select",
    # v0.16.2 자동 탐지 seed 읽기(esl_bead_auto.md AD-D-3 — read_auto_selection 만, 탐지·쓰기는 워커·코어)
    "doe_bead_auto": "esl.doe.bead_auto",
    # v0.17.0 BEADGRAPH(esl_beadgraph.md §8.6): schema 2 정규화·derive(normalize_v2·derive_v2) — 분류는 워커 DOE_PREP 코어 단계
    "doe_bead_graph": "esl.doe.bead_graph",
    # 이슈 #53: 원자적 교체 공통 함수(atomic_replace·FileLocked·configure) — esl_platform.core.atomic 이 재노출
    "fsutil": "esl.fsutil",
}
_OPT_ATTRS = ("settings", "load_method_sources", "sources_ref", "DEFAULTS", "MODES", "STRATEGIES", "OBJECTIVE_NORMS",
              "METHOD_SOURCES_PATH", "BEAD_POST_TCL")
_FUNCS = {"build_template": ("esl.opt.target", "build_template"),
          "doe_settings": ("esl.doe", "settings"), "doe_commands": ("esl.doe", "commands"),
          "doe_defaults": ("esl.doe", "DEFAULTS"), "doe_default_commands": ("esl.doe", "DEFAULT_COMMANDS"),
          "doe_load_messages": ("esl.doe", "load_messages"), "doe_message": ("esl.doe", "message"),
          "doe_load_method_sources": ("esl.doe", "load_method_sources"),
          "doe_sort_rows": ("esl.doe.rank", "sort_rows"),             # v0.10.0 §11.4 순위표 정렬 키
          # v0.16.0 ④ 메시 입력 파트 스캔(esl_compare_mesh_options.md §6 — 1차 스캔만, 숫자 블록은 위치·행 수만)
          "rad_deck": ("esl.rad.parser", "_Deck")}


def __getattr__(name: str) -> Any:
    if name in _MODULES:
        return importlib.import_module(_MODULES[name])
    if name in _OPT_ATTRS:
        return getattr(importlib.import_module("esl.opt"), name)
    if name in _FUNCS:
        mod, attr = _FUNCS[name]
        return getattr(importlib.import_module(mod), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["EslError", *_MODULES, *_OPT_ATTRS, *_FUNCS]
