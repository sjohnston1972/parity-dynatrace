import { useState, useEffect, useCallback } from 'react';

export function useApi(apiFn, deps = []) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = useCallback((silent) => {
    if (!silent) { setLoading(true); setError(null); }
    const result = apiFn();
    if (!result || typeof result.then !== 'function') {
      if (!silent) setLoading(false);
      return;
    }
    result
      .then(setData)
      .catch((e) => { if (!silent) setError(e); })
      .finally(() => { if (!silent) setLoading(false); });
  }, deps);

  const refetch = useCallback(() => fetchData(true), [fetchData]);

  useEffect(() => { fetchData(false); }, [fetchData]);

  return { data, loading, error, refetch };
}
