// v0.24.1 재현(목표·재현·오차) 3D 자료 훅(esl_view3d_sources.md §5.1·§6.1) + Case 출처 목록 훅.
// 응답 변위는 서버가 새로 풀지 않고 저장된 해로 파생 캐시를 만든다 — 첫 요청이 느릴 수 있어 응답·오차 보기를 열 때만 부른다.
import { useEffect, useState } from "react";
import { api } from "../api/endpoints";
import { API_PREFIX, errorText, request } from "../api/client";
import { doe } from "../api/doe";
import type { DoeReconFile, View3dReconOut, View3dSourcesOut } from "../api/types";
import { fetchBinary, resolveFileUrl } from "./fetchFiles";
import { decodeDisp, type DecodedDisp } from "./values";

export interface ReconState {
  recon: View3dReconOut | null;
  disp: DecodedDisp | null;
  loading: boolean;
  /** 실패 사유(한국어 한 줄) — 409 V3D_RECON_UNAVAILABLE 등 */
  error: string | null;
}

const EMPTY: ReconState = { recon: null, disp: null, loading: false, error: null };

/** `src` 출처의 재현 자료(recon.json + recon.bin). enabled 가 아니면 아무것도 안 부른다. src 없음 = legacy 행 */
export function useRecon(runId: string | null, src: string | null | undefined, enabled: boolean): ReconState {
  const [st, setSt] = useState<ReconState>(EMPTY);
  const [nonce, setNonce] = useState(0);
  const [retried, setRetried] = useState(false);
  useEffect(() => {
    setSt(EMPTY);
    if (!runId || !enabled) return;
    let alive = true;
    setSt({ ...EMPTY, loading: true });
    (async () => {
      try {
        const recon = await api.view3dRecon(runId, src ?? undefined);
        const buf = await fetchBinary(resolveFileUrl(runId, recon.values_url, recon.key));
        if (!alive) return;
        setSt({ recon, disp: decodeDisp(buf, recon), loading: false, error: null });
      } catch (e) {
        if (!alive) return;
        if ((e as { code?: string }).code === "VIEW3D_STALE" && !retried) {
          setRetried(true);
          setNonce((n) => n + 1);
          return;
        }
        setSt({ recon: null, disp: null, loading: false, error: errorText(e) });
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, src, enabled, nonce]);
  return st;
}

export interface SourcesState {
  sources: View3dSourcesOut | null;
  /** 아직 응답을 기다리는 중(탭을 그리기 전) */
  loading: boolean;
  /** 실패(옛 서버 404 등) — 화면은 출처 탭 없이 legacy 화면 그대로 */
  failed: boolean;
}

/** Case ③ 출처 목록(GET /esl-runs/{id}/view3d/sources) */
export function useCaseSources(runId: string | null, enabled: boolean): SourcesState {
  const [st, setSt] = useState<SourcesState>({ sources: null, loading: false, failed: false });
  useEffect(() => {
    setSt({ sources: null, loading: !!runId && enabled, failed: false });
    if (!runId || !enabled) return;
    let alive = true;
    api
      .view3dSources(runId)
      .then((s) => alive && setSt({ sources: s, loading: false, failed: false }))
      .catch(() => alive && setSt({ sources: null, loading: false, failed: true }));
    return () => {
      alive = false;
    };
  }, [runId, enabled]);
  return st;
}

export interface StudyReconState {
  recon: DoeReconFile | null;
  disp: DecodedDisp | null;
  error: string | null;
}

/** 스터디 폴더 `did` 의 재현 자료(recon.json + recon.bin — /doe/studies/{id}/view3d/{did}/…). did 없음 = 아무것도 안 부름 */
export function useStudyRecon(studyId: string, did: string | null): StudyReconState {
  const [st, setSt] = useState<StudyReconState>({ recon: null, disp: null, error: null });
  useEffect(() => {
    setSt({ recon: null, disp: null, error: null });
    if (!did) return;
    let alive = true;
    (async () => {
      try {
        const recon = await request<DoeReconFile>("GET", doe.view3dPath(studyId, did, "recon.json"));
        const buf = await fetchBinary(resolveFileUrl(studyId, `${API_PREFIX}${doe.view3dPath(studyId, did, "recon.bin")}`, recon.key));
        if (alive) setSt({ recon, disp: decodeDisp(buf, recon), error: null });
      } catch (e) {
        if (alive) setSt({ recon: null, disp: null, error: errorText(e) });
      }
    })();
    return () => {
      alive = false;
    };
  }, [studyId, did]);
  return st;
}
