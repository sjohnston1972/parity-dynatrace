const API_BASE = '/api/v1';

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `API error: ${res.status}`);
  }
  return res.json();
}

export const api = {
  // Health & Dashboard
  health: () => request('/health'),
  healthDeps: () => request('/health/dependencies'),
  dashboardMetrics: () => request('/dashboard/metrics'),

  // Devices
  devices: () => request('/devices'),
  device: (id) => request(`/devices/${id}`),
  deviceSnapshot: (id) => request(`/devices/${id}/snapshot`),
  deviceUnmonitored: (id) => request(`/devices/${id}/unmonitored`),
  setDeviceUnmonitored: (id, interfaces) =>
    request(`/devices/${id}/unmonitored`, {
      method: 'PUT',
      body: JSON.stringify({ interfaces }),
    }),
  refreshDevices: () => request('/devices/refresh', { method: 'POST' }),

  // Snapshots
  snapshots: (params) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request(`/snapshots${qs}`);
  },
  snapshotStatus: () => request('/snapshots/status'),
  clearSnapshotStatus: () => request('/snapshots/status', { method: 'DELETE' }),

  // Snapshot schedules
  schedules: () => request('/schedules'),
  schedule: (id) => request(`/schedules/${id}`),
  createSchedule: (body) =>
    request('/schedules', { method: 'POST', body: JSON.stringify(body) }),
  updateSchedule: (id, body) =>
    request(`/schedules/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteSchedule: (id) =>
    request(`/schedules/${id}`, { method: 'DELETE' }),
  runScheduleNow: (id) =>
    request(`/schedules/${id}/run`, { method: 'POST' }),
  snapshot: (id) => request(`/snapshots/${id}`),
  snapshotDiff: (id) => request(`/snapshots/${id}/diff`),
  deleteSnapshot: (id) => request(`/snapshots/${id}`, { method: 'DELETE' }),
  deleteSnapshots: (ids) =>
    request('/snapshots/bulk-delete', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
  deleteAllSnapshots: () => request('/snapshots', { method: 'DELETE' }),
  triggerSnapshot: (deviceId) =>
    request('/snapshots', {
      method: 'POST',
      body: JSON.stringify(deviceId ? { device_id: deviceId } : {}),
    }),
  blessSnapshot: (id) =>
    request(`/snapshots/${id}/bless`, { method: 'POST' }),
  baselinesSummary: () => request('/snapshots/baselines/summary'),
  goldenSnapshots: () => request('/snapshots/goldens'),

  // Findings
  findings: (params) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request(`/findings${qs}`);
  },
  finding: (id) => request(`/findings/${id}`),
  dismissFinding: (id) => request(`/findings/${id}`, { method: 'DELETE' }),
  escalateFinding: (id) => request(`/findings/${id}/escalate`, { method: 'POST' }),
  incidents: (opts = {}) => {
    const params = new URLSearchParams();
    if (opts.include_recent_hours) params.set('include_recent_hours', opts.include_recent_hours);
    const qs = params.toString();
    return request(`/findings/incidents/list${qs ? `?${qs}` : ''}`);
  },
  recorrelateIncidents: () => request('/findings/incidents/recorrelate', { method: 'POST' }),

  // Approvals
  approvals: () => request('/approvals'),
  approve: (id, body = {}) => request(`/approvals/${id}/approve`, { method: 'POST', body: JSON.stringify(body) }),
  deny: (id, body = {}) => request(`/approvals/${id}/deny`, { method: 'POST', body: JSON.stringify(body) }),
  approvalHistory: () => request('/approvals/history'),
  expireApprovals: () => request('/approvals/expire', { method: 'POST' }),
  dismissStaleApprovals: () => request('/approvals/dismiss-stale', { method: 'POST' }),

  // Pipeline
  pipelineRun: (body) => request('/pipeline/run', { method: 'POST', body: JSON.stringify(body) }),
  pipelineStatus: () => request('/pipeline/status'),
  pipelineStats: () => request('/pipeline/stats'),
  pipelineActivity: () => request('/pipeline/activity'),
  pipelineActivityStream: () =>
    fetch(`${API_BASE}/pipeline/activity/stream`, {
      headers: { 'Accept': 'text/event-stream' },
    }),

  // Execution
  execute: (approvalId) => request(`/execute/${approvalId}`, { method: 'POST' }),

  // Chat (streaming — returns raw Response for SSE consumption)
  // page_context: { route, title, visible: [{type,id,title}] } — lets
  // the assistant resolve "this incident" / "these devices" without
  // the user pasting IDs. Each page sets window.parityPageContext.
  chatStream: (messages, model, page_context) =>
    fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages, model, page_context }),
    }),

  // Topology
  topology: () => request('/topology'),
  topologyLayout: (view = 'bgp') => request(`/topology/layout/${view}`),
  saveTopologyLayout: (view, data) => request(`/topology/layout/${view}`, { method: 'PUT', body: JSON.stringify(data) }),

  // Dynatrace
  dtStatus: () => request('/dynatrace/status'),
  dtEvents: (lookback = '-1h', limit = 50, sources = 'parity') =>
    request(`/dynatrace/events?lookback=${encodeURIComponent(lookback)}&limit=${limit}&sources=${encodeURIComponent(sources)}`),
  dtDavisProblems: (lookback = '-24h', limit = 50) =>
    request(`/dynatrace/davis-problems?lookback=${encodeURIComponent(lookback)}&limit=${limit}`),
};
