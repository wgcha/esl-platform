// 보고서(자체 완결 HTML) 새 탭 열기. 실서버는 링크 그대로, mock 모드는 목 서버 응답을 blob 으로 연다.
import { useEffect, useState, type MouseEvent } from "react";

export function openReport(url: string) {
  if (__MOCK__) {
    void fetch(url)
      .then((r) => r.text())
      .then((html) => window.open(URL.createObjectURL(new Blob([html], { type: "text/html" })), "_blank", "noopener"));
    return;
  }
  window.open(url, "_blank", "noopener");
}

/** 보고서 유무: GET 응답 상태만 보고 본문은 끊는다(404 = 아직 없음). null = 확인 중 */
export function useReportAvailable(url: string, dep: unknown) {
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    setOk(null);
    fetch(url, { credentials: "same-origin", signal: ctl.signal })
      .then((r) => {
        setOk(r.ok);
        ctl.abort();
      })
      .catch(() => undefined);
    return () => ctl.abort();
  }, [url, dep]);
  return ok;
}

export const REPORT_MISSING = "보고서가 아직 없습니다 — 검증이 끝나면 자동으로 만들어집니다";

export function ReportLink({ url, label = "보고서 보기", dep }: { url: string; label?: string; dep?: unknown }) {
  const ok = useReportAvailable(url, dep);
  if (ok === false)
    return (
      <span className="primary-wrap" title={REPORT_MISSING}>
        <button type="button" className="btn small" disabled>
          {label}
        </button>
      </span>
    );
  return (
    <a
      className="btn small"
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e: MouseEvent) => {
        if (!__MOCK__) return;
        e.preventDefault();
        openReport(url);
      }}
    >
      {label}
    </a>
  );
}
