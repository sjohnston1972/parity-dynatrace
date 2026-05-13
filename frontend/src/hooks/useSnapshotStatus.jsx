import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../api/client';

const SnapshotContext = createContext(null);

export function SnapshotProvider({ children }) {
  const [status, setStatus] = useState({ running: false });
  const [lastSnapshot, setLastSnapshot] = useState(null);
  const pollRef = useRef(null);

  const fetchStatus = useCallback(async () => {
    try {
      const s = await api.snapshotStatus();
      setStatus(s);
      return s;
    } catch {
      return status;
    }
  }, []);

  const fetchLastSnapshot = useCallback(async () => {
    try {
      const snaps = await api.snapshots({ limit: 1 });
      if (snaps?.length) setLastSnapshot(snaps[0]);
    } catch {}
  }, []);

  // Initial fetch
  useEffect(() => {
    fetchStatus();
    fetchLastSnapshot();
  }, []);

  // Poll while running
  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (status.running) {
      pollRef.current = setInterval(async () => {
        const s = await fetchStatus();
        if (!s.running) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          fetchLastSnapshot();
        }
      }, 3000);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [status.running]);

  const triggerSnapshot = useCallback(async (deviceId) => {
    if (status.running) return;
    try {
      await api.triggerSnapshot(deviceId || undefined);
      setStatus({ running: true, started_at: new Date().toISOString(), device_id: deviceId || null });
    } catch (e) {
      if (e.message?.includes('409')) {
        setStatus((prev) => ({ ...prev, running: true }));
      }
      throw e;
    }
  }, [status.running]);

  return (
    <SnapshotContext.Provider value={{ status, lastSnapshot, triggerSnapshot, refresh: () => { fetchStatus(); fetchLastSnapshot(); } }}>
      {children}
    </SnapshotContext.Provider>
  );
}

export function useSnapshotStatus() {
  return useContext(SnapshotContext);
}
