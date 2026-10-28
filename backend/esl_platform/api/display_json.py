"""API 응답 경로 표기 통일(이슈 #24): JSON 응답의 경로 필드를 ``esl.display.display_path`` 로 정규화.

응답 경계에서만 적용한다(DB 저장값·내부 비교는 그대로). 라우터마다 고치지 않도록 기본 응답 클래스에서
키 이름으로 처리한다. 대상: 절대경로를 담는 키(``*_path``·``*_dir``·``folder_path``·``case_dir`` 등)와
``path``(파일 탐색 응답의 상대경로 ``path``·``parent`` 는 제외). ``*_rel``·``rel`` 은 '/' 구분 상대경로라 건드리지 않는다.
"""
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from esl_worker.core_adapter import display_path

PATH_KEYS = frozenset({
    "path", "case_dir", "folder_path", "rad_path", "results_dir", "h3d_path", "dir_path", "backup_path",
    "abs_path", "normalized_path", "out_dir", "result_path", "log_path", "scene_path", "export_dir",
    "snapshot_dir", "lib_root", "library_root", "env_dir", "config_path", "upload_root", "esl_root",
})
PATH_LIST_KEYS = frozenset({"input_roots", "spdm_roots", "paths"})


def display_paths(obj: Any) -> Any:
    """JSON 호환 객체를 복사하며 경로 필드를 표시용으로 정규화."""
    if isinstance(obj, dict):
        browse = "roots" in obj and "entries" in obj          # BrowseOut: path·parent 는 root 기준 상대경로
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and k in PATH_KEYS and not (browse and k == "path"):
                out[k] = display_path(v)
            elif isinstance(v, list) and k in PATH_LIST_KEYS and all(isinstance(x, str) for x in v):
                out[k] = [display_path(x) for x in v]
            else:
                out[k] = display_paths(v)
        return out
    if isinstance(obj, list):
        return [display_paths(x) for x in obj]
    return obj


class DisplayJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return super().render(display_paths(content))
