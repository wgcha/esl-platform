"""자체 완결 HTML 보고서 응답(계약 esl_p2_library.md §11): CSP 로 외부 자원·네트워크 차단, ?download=1 이면 첨부."""

from __future__ import annotations

from urllib.parse import quote

from fastapi.responses import Response

REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:"


def html_report(path: str, filename: str, download: bool) -> Response:
    with open(path, "rb") as fh:
        body = fh.read()
    headers = {"Content-Security-Policy": REPORT_CSP, "X-Content-Type-Options": "nosniff",
               "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}
    if download:
        headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
    return Response(content=body, media_type="text/html; charset=utf-8", headers=headers)
