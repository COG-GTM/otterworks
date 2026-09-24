import { useCallback, useEffect, useRef, useState } from "react";

// Touch devices have no hover, so hover-revealed controls are unreachable there.
export const COARSE_POINTER_QUERY = "(hover: none), (pointer: coarse)";

function matchesCoarsePointer(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(COARSE_POINTER_QUERY).matches;
}

export function useCoarsePointer(): boolean {
  const [coarse, setCoarse] = useState(matchesCoarsePointer);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mql = window.matchMedia(COARSE_POINTER_QUERY);
    setCoarse(mql.matches);
    const onChange = (e: MediaQueryListEvent) => setCoarse(e.matches);
    if (typeof mql.addEventListener === "function") {
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    }
    mql.addListener?.(onChange);
    return () => mql.removeListener?.(onChange);
  }, []);

  return coarse;
}

// Reveal rules for a card action button: always visible on touch, hover- or
// focus-revealed on desktop.
export function actionRevealClass(coarse: boolean): string {
  return coarse
    ? "opacity-100"
    : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus:opacity-100 focus-visible:opacity-100";
}

// 44x44 minimum tap target on touch; desktop keeps its compact icon buttons.
export function tapTargetClass(coarse: boolean): string {
  return coarse ? "min-h-[44px] min-w-[44px] flex items-center justify-center" : "";
}

interface LongPressOptions {
  enabled?: boolean;
  delay?: number;
}

export interface LongPressResult {
  handlers: {
    onPointerDown: (e: React.PointerEvent) => void;
    onPointerUp: () => void;
    onPointerMove: (e: React.PointerEvent) => void;
    onPointerLeave: () => void;
    onPointerCancel: () => void;
    onContextMenu: (e: React.MouseEvent) => void;
  };
  consumeLongPress: () => boolean;
}

// Long-press (touch/pen only) to enter multi-select. `consumeLongPress` lets the
// card swallow the click that a long press would otherwise produce.
export function useLongPress(
  onLongPress: (() => void) | undefined,
  { enabled = true, delay = 500 }: LongPressOptions = {}
): LongPressResult {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const firedRef = useRef(false);
  const originRef = useRef<{ x: number; y: number } | null>(null);

  const clear = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => clear, [clear]);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (!enabled || !onLongPress || e.pointerType === "mouse") return;
      firedRef.current = false;
      originRef.current = { x: e.clientX, y: e.clientY };
      clear();
      timerRef.current = setTimeout(() => {
        firedRef.current = true;
        onLongPress();
      }, delay);
    },
    [clear, delay, enabled, onLongPress]
  );

  const consumeLongPress = useCallback(() => {
    const fired = firedRef.current;
    firedRef.current = false;
    return fired;
  }, []);

  // Ignore finger jitter; cancel only on a real drag/scroll.
  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      const origin = originRef.current;
      if (!origin) return;
      if (Math.hypot(e.clientX - origin.x, e.clientY - origin.y) > 10) clear();
    },
    [clear]
  );

  return {
    handlers: {
      onPointerDown,
      onPointerUp: clear,
      onPointerMove,
      onPointerLeave: clear,
      onPointerCancel: clear,
      onContextMenu: (e: React.MouseEvent) => {
        if (firedRef.current) e.preventDefault();
      },
    },
    consumeLongPress,
  };
}
