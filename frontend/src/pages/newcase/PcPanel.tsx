// 새 Case — PC에서 추출해 올리기(계약 esl_p3_ux.md §9): PC 도구 설치 안내 + "PC 연결 코드 만들기"(power 이상, 6자리·15분·1회용,
// 현재 프로젝트에 묶임) + "연결된 PC" 목록(장치명·만료·폐기). PC 도구가 추출·업로드를 마치면 브라우저가
// …/cases/new?upload=<id> 로 열려 "내 PC에서 올리기" 탭이 채워진다(이 탭은 입력을 직접 고르지 않는다).
import { useCallback, useEffect, useState } from "react";
import { p3 } from "../../api/p3";
import { API_PREFIX, errorText } from "../../api/client";
import type { ClientCodeOut, ClientTokenOut, ClientTokenState } from "../../api/types";
import { Badge, Empty, ErrorLine } from "../../components/ui";
import { dt } from "../../lib/format";
import { readSlim, writeSlim } from "../../lib/slim";

const STATE_LABEL: Record<ClientTokenState, string> = { ACTIVE: "사용 중", EXPIRED: "만료", REVOKED: "폐기됨" };
const STATE_KIND: Record<ClientTokenState, "ok" | "warn" | "bad"> = { ACTIVE: "ok", EXPIRED: "warn", REVOKED: "bad" };
export const PC_CODE_BUTTON = "PC 연결 코드 만들기";

/** 남은 시간 mm:ss(0 이하 = "0:00") */
export function remainText(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** PC 도구가 처음에 묻는 서버 주소(esl_deploy.json server_url) */
export function serverUrl(origin = typeof window !== "undefined" ? window.location.origin : ""): string {
  return origin + API_PREFIX.replace(/\/api$/, "");
}

export function PcPanel({ projectId, projectName, allowed, reason }: { projectId: string; projectName?: string; allowed: boolean; reason: string }) {
  const [code, setCode] = useState<ClientCodeOut | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tokens, setTokens] = useState<ClientTokenOut[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  // 압축 모드: 이 브라우저의 안내 기본값(기본 ON, localStorage esl.slim.v1). PC 도구에는 전달되지 않는다(US-3)
  const [slim, setSlimState] = useState(readSlim);
  const setSlim = (on: boolean) => {
    setSlimState(on);
    writeSlim(on);
  };

  const load = useCallback(async () => {
    try {
      setTokens(await p3.clientTokens(projectId));
      setListError(null);
    } catch (e) {
      setListError(errorText(e));
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!code) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [code]);

  const left = code ? new Date(code.expires_at).getTime() - now : 0;
  const expired = !!code && left <= 0;

  async function makeCode() {
    setBusy(true);
    setError(null);
    try {
      const c = await p3.createClientCode(projectId);
      setNow(Date.now());
      setCode(c);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function revoke(t: ClientTokenOut) {
    setListError(null);
    try {
      await p3.revokeClientToken(t.id);
      await load();
    } catch (e) {
      setListError(errorText(e));
    }
  }

  return (
    <div className="pc-panel" data-testid="pc-panel">
      <p className="small muted">
        h3d가 아주 크거나 망이 느릴 때. 내 PC에서 필요한 부분만 남겨 rad·include와 함께 서버로 자동으로 올립니다(기본: 압축 모드). 올리기가 끝나면 이 새 Case 화면이 채워진 채로
        열리고 "Case 만들기"만 누르면 됩니다.
      </p>
      <div className="slim-box" data-testid="slim-box">
        <label className="slim-check" title="이 브라우저의 안내 기본값입니다. PC 도구는 실행할 때 묻습니다.">
          <input type="checkbox" data-testid="slim-check" checked={slim} onChange={(e) => setSlim(e.target.checked)} /> <b>압축 모드(권장)</b>
        </label>
        <div className="small muted" data-testid="slim-help">
          <div>대상 파트와 변위·최대 변형률(Mid)·소성 변형률(Mid)의 전 프레임만 남긴 h3d를 PC에서 만들어 올립니다(보통 원본의 수 %). 원본 h3d는 PC에 그대로 남습니다.</div>
          <div>다른 파트나 다른 결과로 다시 해석할 계획이면 해제하세요 — 그때는 원본 h3d가 필요합니다.</div>
        </div>
        <div className="small" data-testid="slim-usage">
          {slim ? (
            <>
              <code>ESL_extract.bat</code>에 h3d와 rad를 끌어다 놓으세요(실행 창에서 <b>Enter</b> = 압축).
            </>
          ) : (
            <>
              실행 창에서 <b>O</b>를 누르면 원본을 올립니다(스크립트: <code>ESL_extract.bat /original …</code>).
            </>
          )}{" "}
          <span className="muted">기존 PC 추출(HyperView로 CSV만 올리기)은 실행 창에서 <b>P</b>(<code>/pcextract</code>)로 그대로 쓸 수 있습니다. 이 체크는 서버·PC 도구에 전달되지 않고, PC 도구는 실행할 때 묻습니다.</span>
        </div>
      </div>
      <ol className="pc-steps">
        <li>
          <b>PC 도구 설치(처음 한 번)</b> — 저장소 클론 폴더 맨 위의 <code>update.bat</code>을 더블클릭하면 PC 도구(<code>ESL_extract.bat</code>)가 설치·갱신됩니다
          (서버용 <code>deploy\update.bat</code>과 다른 파일).
        </li>
        <li>
          <b>h3d·rad 끌어다 놓기</b> — h3d와 rad 파일을 함께 <code>ESL_extract.bat</code> 위로 끌어다 놓습니다(h3d만 놓으면 rad 고르는 창이 뜹니다). include는 rad를 따라
          자동으로 모읍니다.
        </li>
        <li>
          <b>처음 한 번 연결</b> — 도구가 서버 주소와 연결 코드를 묻습니다. 서버 주소 <code data-testid="pc-server-url">{serverUrl()}</code>, 연결 코드는 아래 버튼으로
          만듭니다. 이후에는 묻지 않습니다(토큰이 만료·폐기되면 다시 묻습니다).
        </li>
      </ol>

      <div className="pc-code-row">
        <button type="button" className="btn" onClick={makeCode} disabled={!allowed || busy} title={allowed ? undefined : reason}>
          {busy ? "만드는 중…" : code ? "새 코드 만들기" : PC_CODE_BUTTON}
        </button>
        {!allowed && <span className="small muted">{reason}</span>}
        {code && (
          <div className={`pc-code ${expired ? "expired" : ""}`} data-testid="pc-code" aria-live="polite">
            <span className="pc-code-digits mono" aria-label="연결 코드">
              {code.code.slice(0, 3)} {code.code.slice(3)}
            </span>
            <span className="small" data-testid="pc-code-left">
              {expired ? "만료됨 — 새 코드를 만드세요" : `남은 시간 ${remainText(left)} · 한 번만 쓸 수 있음`}
            </span>
            <span className="small muted">프로젝트 {projectName ?? code.project_id}에만 올릴 수 있습니다</span>
          </div>
        )}
      </div>
      <ErrorLine text={error} />

      <h3 className="pc-sub">연결된 PC</h3>
      {tokens === null ? (
        <div className="small muted">{listError ?? "불러오는 중…"}</div>
      ) : tokens.length === 0 ? (
        <Empty>아직 연결된 PC가 없습니다</Empty>
      ) : (
        <div className="table-wrap scroll">
        <table className="table compact" aria-label="연결된 PC">
          <thead>
            <tr>
              <th>장치</th>
              <th>상태</th>
              <th>마지막 사용</th>
              <th>만료</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {tokens.map((t) => (
              <tr key={t.id}>
                <td>
                  {t.device_name} <span className="muted small mono">{t.token_prefix}…</span>
                </td>
                <td>
                  <Badge kind={STATE_KIND[t.state]}>{STATE_LABEL[t.state]}</Badge>
                </td>
                <td className="small">{t.last_used_at ? dt(t.last_used_at) : "–"}</td>
                <td className="small">{t.state === "REVOKED" ? `폐기 ${dt(t.revoked_at)}` : dt(t.expires_at)}</td>
                <td>
                  {t.state === "ACTIVE" && (
                    <button type="button" className="btn small ghost" aria-label={`${t.device_name} 폐기`} onClick={() => revoke(t)}>
                      폐기
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
      {tokens !== null && <ErrorLine text={listError} />}
      <p className="small muted">PC를 잃어버렸거나 더 쓰지 않으면 "폐기"하세요 — 그 PC의 도구는 다음 올리기에서 연결 코드를 다시 묻습니다.</p>
    </div>
  );
}
