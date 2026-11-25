// v0.24.7 DM 깊이 단면 동작(esl_bead_depth_mode.md §7): 라디오 2개(새 스터디·복제 창 공용) · 스터디 머리 칩 · 복제 창(select 스터디만).
// 라벨·툴팁 상수는 api/doe.ts 한 곳, 안내 문구는 서버 text(settings.depth_section_notes) — 화면에 문구 거울 없음.
import { useEffect, useRef, useState } from "react";
import { DEPTH_SECTIONS, DEPTH_SECTION_LABEL, DEPTH_SECTION_TIP, DEPTH_SECTION_TITLE, cloneDepthNote, depthSectionChip } from "../api/doe";
import type { DoeDepthSection, DoeSettingsOut } from "../api/types";

/** "깊이 동작 ○ 입구 고정(깊이면 좁아짐) ● 깊이면 폭 유지(입구 넓어짐)" */
export function DepthSectionRadios({ value, onChange, disabled = false, name, inline = false }: { value: DoeDepthSection; onChange: (v: DoeDepthSection) => void; disabled?: boolean; name: string; inline?: boolean }) {
  return (
    <span className={inline ? "doe-ds" : "doe-sub doe-ds"} role="radiogroup" aria-label={DEPTH_SECTION_TITLE} title={DEPTH_SECTION_TIP} data-testid="ds-radios">
      <span className="small muted">{DEPTH_SECTION_TITLE}</span>
      {DEPTH_SECTIONS.map((k) => (
        <label key={k} className="check-field">
          <input type="radio" name={name} value={k} checked={value === k} disabled={disabled} onChange={() => onChange(k)} />
          <span>{DEPTH_SECTION_LABEL[k]}</span>
        </label>
      ))}
    </span>
  );
}

/** 스터디 머리 칩 1개: 깊이면 폭 유지 | 입구 고정 | 입구 고정(이전) */
export function DepthSectionChip({ value }: { value: DoeDepthSection | null | undefined }) {
  const c = depthSectionChip(value);
  return (
    <span className="doe-chip" data-testid="ds-chip" data-legacy={c.legacy || undefined} title={`${DEPTH_SECTION_TITLE}: ${value ? DEPTH_SECTION_LABEL[value] : DEPTH_SECTION_LABEL.entry_fixed}`}>
      {c.text}
    </span>
  );
}

/** 복제 창(≤ 3줄): 라디오 / 원 값과 다르면 안내 1줄 / [복제] [취소]. 가로 스크롤 없음 */
export function CloneDepthWindow({ from, notes, dropped, busy, onClone, onCancel }: {
  from: DoeDepthSection;
  notes: DoeSettingsOut["depth_section_notes"] | undefined;
  /** 입구 고정으로 복제하면 빠지는 한쪽 입구 W 변수 이름 */
  dropped: string[];
  busy: boolean;
  onClone: (v: DoeDepthSection) => void;
  onCancel: () => void;
}) {
  const [to, setTo] = useState<DoeDepthSection>(from);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => box.current?.focus(), []);
  const note = cloneDepthNote(notes, from, to, dropped);
  return (
    <div
      ref={box}
      className="doe-clone-pop"
      role="dialog"
      aria-label="복제"
      tabIndex={-1}
      data-testid="clone-window"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onCancel();
        }
      }}
    >
      <DepthSectionRadios value={to} onChange={setTo} disabled={busy} name="clone-depth-section" inline />
      {note && (
        <div className="small warn-text" data-testid="clone-note">
          {note}
        </div>
      )}
      <div className="doe-clone-btns">
        <button type="button" className="btn small" disabled={busy} onClick={() => onClone(to)}>
          복제
        </button>
        <button type="button" className="btn small ghost" disabled={busy} onClick={onCancel}>
          취소
        </button>
      </div>
    </div>
  );
}
