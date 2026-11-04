// 보고서(자체 완결 HTML) 화면 안 보기(v0.12.5): sandbox iframe + [보고서 받기](주 버튼, ?download=1) + [새 탭에서 열기](보조 링크).
// sandbox="allow-scripts" 만 — allow-same-origin 을 주지 않아 보고서 스크립트는 불투명 출처로 돌고 앱 쿠키·API 에 닿지 못한다.
// 실서버 = src(보고서 URL, 서버 CSP frame-ancestors 'self'), mock 모드 = 목 서버 응답을 srcdoc 으로.
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from "react";
import { downloadFile, errorText } from "../api/client";
import { Empty, PrimaryButton } from "./ui";
import { openReport } from "./ReportLink";

export const REPORT_DOWNLOAD = "보고서 받기";
export const REPORT_NEW_TAB = "새 탭에서 열기";
export const REPORT_NONE = "보고서가 아직 없습니다";
export const REPORT_SANDBOX = "allow-scripts";

type St = { s: "loading" } | { s: "missing" } | { s: "error"; msg: string } | { s: "ok"; html?: string };

export const downloadUrl = (url: string) => `${url}${url.includes("?") ? "&" : "?"}download=1`;

/** 보고서 유무 확인. 실서버는 상태만 보고 본문을 끊고(iframe 이 src 로 다시 받음), mock 은 본문을 srcdoc 으로 쓴다. */
function useReport(url: string, enabled: boolean, dep: unknown): St {
  const [st, setSt] = useState<St>({ s: "loading" });
  useEffect(() => {
    if (!enabled) return;
    const ctl = new AbortController();
    setSt({ s: "loading" });
    fetch(url, { credentials: "same-origin", signal: ctl.signal })
      .then(async (r) => {
        if (r.status === 404) return setSt({ s: "missing" });
        if (!r.ok) return setSt({ s: "error", msg: `보고서를 불러오지 못했습니다 (${r.status})` });
        if (__MOCK__) return setSt({ s: "ok", html: await r.text() });
        setSt({ s: "ok" });
        ctl.abort();
      })
      .catch((e) => {
        if (!ctl.signal.aborted) setSt({ s: "error", msg: errorText(e) });
      });
    return () => ctl.abort();
  }, [url, enabled, dep]);
  return enabled ? st : { s: "loading" };
}

/** iframe 높이 = 화면 아래까지 채움. 위 내용이 길어 남는 높이가 작으면 상단 바 아래 한 화면 높이(스크롤해 맞춤). */
function useFillHeight(dep: unknown) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [h, setH] = useState(560);
  const measure = useCallback(() => {
    const el = ref.current;
    if (!el || typeof window === "undefined") return;
    const vh = window.innerHeight;
    const top = el.getBoundingClientRect().top + window.scrollY;
    const bar = (document.querySelector(".topbar") as HTMLElement | null)?.offsetHeight ?? 52;
    const head = (el.closest(".report-viewer")?.querySelector(".card-head") as HTMLElement | null)?.offsetHeight ?? 48;
    const pad = 20;
    const fill = vh - top - pad;
    const full = vh - bar - head - pad;
    setH(Math.max(360, Math.round(fill >= 0.6 * full ? fill : full)));
  }, []);
  useLayoutEffect(() => {
    measure();
    window.addEventListener("resize", measure);
    document.addEventListener("toggle", measure, true); // 위 접힘 영역(details) 열고 닫기
    return () => {
      window.removeEventListener("resize", measure);
      document.removeEventListener("toggle", measure, true);
    };
  }, [measure, dep]);
  return { ref, h };
}

export function ReportViewer({
  url,
  filename,
  reason,
  title = "보고서",
  dep,
}: {
  /** GET 보고서 URL(?download 없이) */
  url: string;
  filename: string;
  /** 보고서를 아직 볼 수 없는 사유(생성 중 등). 있으면 iframe 대신 사유 표시 */
  reason?: string | null;
  title?: string;
  dep?: unknown;
}) {
  const st = useReport(url, !reason, dep);
  const ready = !reason && st.s === "ok";
  const { ref, h } = useFillHeight(`${ready}`);
  const [dlError, setDlError] = useState<string | null>(null);
  const why = reason ?? (st.s === "loading" ? "불러오는 중…" : st.s === "missing" ? REPORT_NONE : st.s === "error" ? st.msg : null);
  const dl = downloadUrl(url);

  return (
    <section className="card report-viewer" aria-label={title}>
      <header className="card-head">
        <h3>{title}</h3>
        {ready && (
          <a
            className="small report-newtab"
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e: MouseEvent) => {
              if (!__MOCK__) return;
              e.preventDefault();
              openReport(url);
            }}
          >
            {REPORT_NEW_TAB}
          </a>
        )}
        {ready ? (
          <a
            className="btn primary"
            data-primary="true"
            href={dl}
            download={filename}
            onClick={async (e: MouseEvent) => {
              if (!__MOCK__) return; // 실서버: Content-Disposition attachment 로 브라우저가 바로 받음
              e.preventDefault();
              setDlError(null);
              try {
                await downloadFile(dl, filename);
              } catch (x) {
                setDlError(errorText(x));
              }
            }}
          >
            {REPORT_DOWNLOAD}
          </a>
        ) : (
          <PrimaryButton label={REPORT_DOWNLOAD} onClick={() => undefined} disabledReason={why} />
        )}
      </header>
      {dlError && <div className="small error-text report-dl-error">{dlError}</div>}
      {ready ? (
        <iframe
          ref={ref}
          className="report-frame"
          title={title}
          sandbox={REPORT_SANDBOX}
          referrerPolicy="no-referrer"
          style={{ height: h }}
          {...(st.html != null ? { srcDoc: st.html } : { src: url })}
        />
      ) : (
        <div className="card-body">
          <Empty>
            <span data-testid="report-reason">{why}</span>
          </Empty>
        </div>
      )}
    </section>
  );
}
