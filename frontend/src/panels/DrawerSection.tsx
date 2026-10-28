import type { ReactNode } from "react";

/** 서랍 구획: 머리(제목 + 오른쪽 보조) + 본문. 우측 패널 때의 .panel 카드와 같은 모양. */
export function DrawerSection({ title, id, right, children }: { title: string; id: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel" id={id} aria-label={title}>
      <header className="panel-head">
        <h2>{title}</h2>
        {right}
      </header>
      {children}
    </section>
  );
}
