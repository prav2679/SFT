// Submit a backend simulation and poll its status until it finishes. One submit per click:
// form edits never trigger runs. Duplicate requests are de-duplicated by the backend.
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, systemService } from '../services/apiClient';

export default function useSimulation(resultBase) {
  const [job, setJob] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef(null);

  const poll = useCallback((id, base) => {
    clearTimeout(timer.current);
    const tick = async () => {
      try {
        const st = await api(`/api/burst/${id}`);
        setJob((j) => ({ ...st, reused: j?.reused }));
        if (st.status === 'COMPLETED') {
          setResult(await api(`/api/${base}/${id}/results`));
          setBusy(false);
        } else if (['FAILED', 'CANCELLED', 'INTERRUPTED'].includes(st.status)) {
          setBusy(false);
        } else timer.current = setTimeout(tick, 1000);
      } catch (e) { setError(e); setBusy(false); }
    };
    tick();
  }, []);

  const submit = useCallback(async (fn, base = resultBase) => {
    setError(null); setResult(null); setBusy(true);
    try {
      const st = await fn();
      setJob(st);
      poll(st.simulation_id, base);
    } catch (e) { setError(e); setBusy(false); }
  }, [poll, resultBase]);

  const load = useCallback((id, base = resultBase) => { setResult(null); setBusy(true); poll(id, base); }, [poll, resultBase]);
  const cancel = useCallback(() => job && systemService.cancel(job.simulation_id).catch(setError), [job]);
  useEffect(() => () => clearTimeout(timer.current), []);
  return { job, result, error, busy, submit, cancel, load };
}
