import { useCallback, useEffect, useRef, useState } from "react";
import { errorText } from "../api/client";

/** fn을 즉시 1회, 그 뒤 intervalMs마다 호출. intervalMs=0이면 1회만. 화면이 숨겨지면 건너뜀. */
export function usePolling<T>(fn: () => Promise<T>, intervalMs: number, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const alive = useRef(true);

  const reload = useCallback(async () => {
    try {
      const d = await fnRef.current();
      if (alive.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (alive.current) setError(errorText(e));
    }
  }, []);

  // v0.15.1: 주기(intervalMs)만 바뀌면 자료를 비우지 않는다 — 비우면 화면 전체가 한 번 사라졌다 다시 그려져
  // (작업이 끝나 3초 → 0 으로 바뀔 때) 오류 줄·열어 둔 로그·자식 상태가 지워졌다("에러가 떴는데 창이 금방 사라짐")
  const prevDeps = useRef<unknown[] | null>(null);
  useEffect(() => {
    alive.current = true;
    const same = prevDeps.current !== null && prevDeps.current.length === deps.length && prevDeps.current.every((v, i) => Object.is(v, deps[i]));
    prevDeps.current = deps;
    if (!same) setData(null);
    void reload();
    if (!intervalMs) return () => {
      alive.current = false;
    };
    const t = setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      void reload();
    }, intervalMs);
    return () => {
      alive.current = false;
      clearInterval(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, ...deps]);

  return { data, error, reload, setData };
}
