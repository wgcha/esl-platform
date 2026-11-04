// 실행 취소(esl_bead_select.md §11.2): 칠하기 1획 = 패치 1개(바뀐 요소 번호와 앞·뒤 값), 최대 50단계. 새 패치를 넣으면 다시 실행 목록은 비운다.

export interface Patch<K extends string = string> {
  /** 바뀐 배열 이름 → 요소 번호·이전 값·새 값 */
  changes: { layer: K; idx: Uint32Array; before: Int32Array; after: Int32Array }[];
}

export const HISTORY_MAX = 50;

export class History<K extends string = string> {
  private done: Patch<K>[] = [];
  private undone: Patch<K>[] = [];
  constructor(private max = HISTORY_MAX) {}
  push(p: Patch<K>) {
    if (!p.changes.some((c) => c.idx.length)) return;
    this.done.push(p);
    if (this.done.length > this.max) this.done.shift();
    this.undone = [];
  }
  /** 되돌릴 패치(적용은 호출자 — before 값을 쓴다) */
  undo(): Patch<K> | null {
    const p = this.done.pop() ?? null;
    if (p) this.undone.push(p);
    return p;
  }
  /** 다시 실행할 패치(after 값을 쓴다) */
  redo(): Patch<K> | null {
    const p = this.undone.pop() ?? null;
    if (p) this.done.push(p);
    return p;
  }
  get canUndo() {
    return this.done.length > 0;
  }
  get canRedo() {
    return this.undone.length > 0;
  }
  get size() {
    return this.done.length;
  }
  clear() {
    this.done = [];
    this.undone = [];
  }
}
