import { useEffect, useRef } from 'react';

/**
 * Subscribe to pipeline SSE activity stream.
 * Calls `onPipelineComplete(event)` when a pipeline node that produces
 * visible results (topology, remediation, escalation) completes or fails.
 * Debounced at 2s so rapid completions don't trigger multiple refetches.
 */

const RELEVANT_NODES = new Set([
  'topology', 'remediation', 'escalation', 'escalation_remediation',
  'execution', 'verification', 'snapshot',
]);

export function usePipelineEvents(onPipelineComplete) {
  const cbRef = useRef(onPipelineComplete);
  cbRef.current = onPipelineComplete;

  useEffect(() => {
    let es;
    let retryDelay = 1000;
    let debounceTimer = null;

    function connect() {
      es = new EventSource('/api/v1/pipeline/activity/stream');

      es.addEventListener('activity', (e) => {
        try {
          const data = JSON.parse(e.data);
          if (
            (data.status === 'completed' || data.status === 'failed') &&
            RELEVANT_NODES.has(data.node)
          ) {
            // Debounce — wait 2s after last relevant event before firing
            if (debounceTimer) clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
              cbRef.current?.(data);
              debounceTimer = null;
            }, 2000);
          }
        } catch {}
      });

      es.onerror = () => {
        es.close();
        setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 30000);
      };

      es.onopen = () => {
        retryDelay = 1000;
      };
    }

    connect();
    return () => {
      es?.close();
      if (debounceTimer) clearTimeout(debounceTimer);
    };
  }, []);
}
