// 결과 받기(zip)(계약 esl_p3_ux.md §2): GET …/bundle 스트리밍 zip. 413(한도 초과)이면 폴더 경로 안내 + 복사.
import { useState } from "react";
import { ApiError, downloadFile, errorText } from "../api/client";
import { bytes } from "../lib/format";
import { CopyPath } from "./CopyPath";

export const BUNDLE_LABEL = "결과 받기(zip)";
export const BUNDLE_TOO_LARGE = "결과가 커서 zip 으로 받을 수 없습니다 — 아래 폴더 경로를 복사해 탐색기에서 여세요";

export function BundleButton({ url, filename, fallbackPath, small = true }: { url: string; filename: string; fallbackPath?: string | null; small?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [tooLarge, setTooLarge] = useState<{ path: string | null; size?: number; limit?: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <span className="bundle">
      <button
        type="button"
        className={small ? "btn small" : "btn"}
        disabled={busy}
        title="내보내기 파일·보고서·요약(json·csv)을 zip 하나로 내려받습니다. 대용량 원자료(npz)는 빠집니다."
        onClick={async () => {
          setBusy(true);
          setError(null);
          setTooLarge(null);
          try {
            await downloadFile(url, filename);
          } catch (x) {
            if (x instanceof ApiError && x.status === 413)
              setTooLarge({ path: (x.detail.path as string | undefined) ?? fallbackPath ?? null, size: x.detail.size, limit: x.detail.limit });
            else setError(errorText(x));
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "만드는 중…" : BUNDLE_LABEL}
      </button>
      {tooLarge && (
        <div className="bundle-pop too-large" role="status" data-testid="bundle-too-large">
          <div className="small warn-text">
            {BUNDLE_TOO_LARGE}
            {tooLarge.size && tooLarge.limit ? ` (${bytes(tooLarge.size)} > 한도 ${bytes(tooLarge.limit)})` : ""}
          </div>
          {tooLarge.path && <CopyPath path={tooLarge.path} />}
        </div>
      )}
      {error && <div className="small error-text bundle-pop">{error}</div>}
    </span>
  );
}
