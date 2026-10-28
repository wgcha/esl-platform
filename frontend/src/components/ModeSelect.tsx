// 변형 모드 드롭다운(esl_opt_run.md §7.4): 자동 = 회색 글씨, 사용자 수정 = 굵게. 바꾸면 PATCH /library/entries/{id}(version 잠금).
// "자동(…)" 을 고르면 null(자동으로 되돌림).
import { useState } from "react";
import { api } from "../api/endpoints";
import { errorText } from "../api/client";
import { MODES, MODE_LABEL } from "../api/opt";
import type { DeformMode, EntryOut } from "../api/types";

/** 화면 이름(모델 버전 orient) — 같은 모델·orient 의 다른 버전도 구분 */
export const entryKey = (e: EntryOut) => [e.model.name ?? e.id, e.model.version, e.scene.orient].filter(Boolean).join(" ");

export function modeText(e: EntryOut): string {
  const m = e.deform_mode?.effective;
  return m ? MODE_LABEL[m] : "분류 불가";
}

export function ModeSelect({ e, allowed, onSaved }: { e: EntryOut; allowed: boolean; onSaved?: (e: EntryOut) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dm = e.deform_mode;
  const user = dm?.user ?? null;
  const auto = dm?.auto ?? null;
  const label = `${entryKey(e)} 모드`;
  async function change(v: string) {
    setBusy(true);
    setError(null);
    try {
      const out = await api.patchEntry(e.id, { version: e.version, deform_mode: v === "" ? null : (v as DeformMode) });
      onSaved?.(out);
    } catch (x) {
      setError(errorText(x));
    } finally {
      setBusy(false);
    }
  }
  return (
    <span className="mode-select">
      <select
        aria-label={label}
        className={user ? "mode-user" : "mode-auto"}
        value={user ?? ""}
        disabled={!allowed || busy}
        title={user ? `사용자 수정 (자동: ${auto ? MODE_LABEL[auto] : "분류 불가"})` : "자동 분류 — 바꾸면 저장됩니다"}
        onChange={(x) => void change(x.target.value)}
      >
        <option value="">{user ? `자동으로(${auto ? MODE_LABEL[auto] : "분류 불가"})` : auto ? MODE_LABEL[auto] : "분류 불가"}</option>
        {MODES.filter((m) => m !== auto || user).map((m) => (
          <option key={m} value={m}>
            {MODE_LABEL[m]}
            {m === auto ? " (자동과 같음)" : ""}
          </option>
        ))}
      </select>
      {error && (
        <span className="small error-text" role="alert">
          {error}
        </span>
      )}
    </span>
  );
}
