import { useEffect, useRef, useState } from 'react';

/**
 * Roll a displayed number from 0 up to `target` with an ease-out curve — purely
 * visual; the underlying value is never touched. `restartKey` re-runs the count
 * when it changes (e.g. switching sports whose scores happen to be equal).
 * Duration matches the chart's draw-in so both land on the same beat.
 */
export function useCountUp(
  target: number | null | undefined,
  duration = 900,
  restartKey: string | number = 0,
): number | null {
  const [val, setVal] = useState<number | null>(null);
  const raf = useRef<number | null>(null);

  useEffect(() => {
    if (target == null) {
      setVal(null);
      return;
    }
    const t0 = Date.now();
    const tick = () => {
      const p = Math.min(1, (Date.now() - t0) / duration);
      const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic — fast start, soft landing
      setVal(Math.round(target * eased));
      if (p < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current != null) cancelAnimationFrame(raf.current);
    };
  }, [target, duration, restartKey]);

  return val;
}
