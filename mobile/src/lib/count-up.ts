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
      // Land on the real number exactly, never on whatever easeOutCubic rounds to at
      // p ~= 0.999. The roll-up is decoration; the value under it is the Pulse, and a
      // score that reads 70 on a screen whose data says 71 is a bug, not a flourish.
      const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic — fast start, soft landing
      setVal(p >= 1 ? target : Math.round(target * eased));
      if (p < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current != null) cancelAnimationFrame(raf.current);
      raf.current = null;
      // An animation cut short — the sheet closed, the sport switched, the screen
      // re-rendered mid-roll — must leave the true value on screen, not the frame it
      // happened to die on. This is the only way this hook can display a number that
      // isn't in the data, so it's the only way it can be blamed for one.
      setVal(target);
    };
  }, [target, duration, restartKey]);

  return val;
}
