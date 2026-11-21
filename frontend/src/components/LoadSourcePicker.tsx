// v0.24.4 P3 하위 작업(스터디·비드 최적화) 하중 출처 선택(esl_jig_case.md §9) — 타이틀 줄 안 드롭다운 1개 + 최악 ④ 판정 표식.
// 안 고르면(기본) 요청에 load_source 를 넣지 않는다 = 지금과 같은 요청. 항목 판정은 묶음 /library/entries/sources(실패하면 표식 없이 모두 선택 가능 — 서버가 최종 판정).
import { useEffect, useMemo, useState } from "react";
import { library } from "../api/library";
import type { EntrySourcesItem, LoadGrade } from "../api/types";
import { checkEntryMark, loadSourceOptions, type LoadSourceCtx, type UnconfirmedDetail } from "../view3d/loadSource";
import { sourceRow, type TabMark } from "../view3d/sources";

const TONE: Record<TabMark["tone"], string> = { ok: "var(--ok)", bad: "var(--bad)", warn: "var(--wait)", muted: "var(--muted)" };

export function LoadSourcePicker({
  entryIds, ctx, value, onChange, defaultKey, disabled,
}: {
  entryIds: readonly string[];
  ctx: LoadSourceCtx;
  /** "" = 기본(필드 생략) */
  value: string;
  onChange: (v: string) => void;
  /** 설정 load_source_default(기본 동작 안내용 — 스터디 null = 순위 지표 기준, 최적화 "full") */
  defaultKey?: string | null;
  disabled?: boolean;
}) {
  const [data, setData] = useState<EntrySourcesItem[] | null>(null);
  const idsKey = entryIds.join(",");
  useEffect(() => {
    setData(null);
    if (!entryIds.length) return;
    let alive = true;
    library
      .entriesSources([...entryIds])
      .then((r) => alive && setData(Array.isArray(r?.items) ? r.items : null))
      .catch(() => alive && setData(null));
    return () => {
      alive = false;
    };
  }, [idsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const opts = useMemo(() => loadSourceOptions(data, ctx), [data, ctx]);
  const cur = opts.find((o) => o.key === value) ?? null;
  // 고른 출처가 선택 불가가 되거나(항목 변경) 표에서 사라지면 기본으로
  useEffect(() => {
    if (value && (!cur || cur.disabled)) onChange("");
  }, [cur, value]); // eslint-disable-line react-hooks/exhaustive-deps

  const defLabel = defaultKey ? sourceRow(defaultKey)?.label ?? defaultKey : null;
  const defText = defLabel ? `기본 — ${defLabel}` : "기본 — 순위 지표 기준";
  return (
    <span className="ls-pick" data-testid="ls-pick">
      <label className="small muted" htmlFor="ls-select">
        하중 출처
      </label>
      <select id="ls-select" aria-label="하중 출처" data-testid="ls-select" value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)} title={cur?.title ?? "안 고르면 지금과 같이 만듭니다"}>
        <option value="">{defText}</option>
        {opts.map((o) => (
          <option key={o.key} value={o.key} disabled={o.disabled} title={o.title} data-testid={`ls-opt-${o.key}`} data-disabled={o.disabled ? "1" : undefined}>
            {o.text}
          </option>
        ))}
      </select>
      {cur?.mark && (
        <span className="small ls-mark" data-testid="ls-mark" data-tone={cur.mark.tone} style={{ color: TONE[cur.mark.tone] }} title={cur.title}>
          {cur.mark.text}
        </span>
      )}
    </span>
  );
}

/** 최악 등급(B3 worst = LoadGrade) 문구 */
const GRADE_TEXT: Record<LoadGrade, string> = { PASS: "PASS", caution: "주의", not_comparable: "비교용 아님", UNDETERMINED: "판정 불가", FAIL: "FAIL", NO_RESULT: "결과 없음" };

/** 서버 확인 요청(422 LOAD_SOURCE_UNCONFIRMED) 대화상자 — 항목별 판정·비교 여부를 보이고 [확인하고 계속] 으로 load_source_ack 재요청 */
export function LoadSourceConfirmDialog({
  sourceKey, detail, busy, onConfirm, onCancel,
}: {
  sourceKey: string;
  detail: UnconfirmedDetail;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const label = sourceRow(sourceKey)?.label ?? sourceKey;
  const worst = detail.worst ? GRADE_TEXT[detail.worst] ?? detail.worst : null;
  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && !busy && onCancel()}>
      <div className="modal" role="alertdialog" aria-modal="true" aria-labelledby="ls-confirm-title" data-testid="ls-confirm">
        <h2 id="ls-confirm-title" className="modal-title">
          하중 출처 확인 — {label}
        </h2>
        <div className="small">
          선택한 하중 출처가 검증을 통과하지 못했거나 비교용이 아닙니다{worst ? ` (최악 판정 ${worst})` : ""}. 결과 값의 뜻이 달라질 수 있으니 확인한 뒤에만 계속하세요.
        </div>
        <ul className="reasons small" aria-label="항목별 판정" data-testid="ls-confirm-list">
          {detail.entries.map((x) => {
            const m = checkEntryMark(x);
            return (
              <li key={x.entry_id}>
                <span className="mono">{x.entry_id}</span> — <span style={{ color: TONE[m.tone], fontWeight: 650 }}>{m.text}</span>
              </li>
            );
          })}
        </ul>
        <div className="actions modal-actions">
          <button type="button" className="btn ghost" onClick={onCancel} disabled={busy}>
            취소
          </button>
          <button type="button" className="btn primary" onClick={onConfirm} disabled={busy} data-testid="ls-confirm-ok">
            확인하고 계속
          </button>
        </div>
      </div>
    </div>
  );
}

/** 결과 화면 사용 출처 칩(스냅샷 load_source · load_source_check) */
export function LoadSourceChip({ chip, className = "doe-chip", short = false }: { short?: boolean; chip: { text: string; short: string; tone: TabMark["tone"] | "none"; title: string } | null; className?: string }) {
  if (!chip) return null;
  return (
    <span className={className} data-testid="ls-chip" data-tone={chip.tone} title={chip.title} style={chip.tone !== "none" && chip.tone !== "ok" ? { color: TONE[chip.tone] } : undefined}>
      {short ? chip.short : chip.text}
    </span>
  );
}
