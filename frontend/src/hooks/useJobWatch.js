// Polls a background job (any simulation id) until it finishes. Used for telemetry-triggered re-forecasts.
import { useCallback, useEffect, useRef, useState } from 'react';
import { simService } from '../services/apiClient';

const FINAL = ['COMPLETED', 'FAILED', 'CANCELLED', 'INTERRUPTED'];

export default function useJobWatch(onFinal) {
  const [job, setJob] = useState(null);
  const timer = useRef(null);
  const cb = useRef(onFinal);
  cb.current = onFinal;
  useEffect(() => () => clearInterval(timer.current), []);
  const watch = useCallback((initial) => {
    clearInterval(timer.current);
    setJob(initial);
    timer.current = setInterval(async () => {
      try {
        const st = await simService.status(initial.simulation_id);
        setJob(st);
        if (FINAL.includes(st.status)) { clearInterval(timer.current); cb.current?.(st); }
      } catch { /* transient network error: keep polling */ }
    }, 1500);
  }, []);
  const reset = useCallback(() => { clearInterval(timer.current); setJob(null); }, []);
  return { job, watch, reset };
}
