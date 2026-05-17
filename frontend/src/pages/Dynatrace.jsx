import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import { api } from '../api/client';
import Icon from '../components/Icon';
import dynatraceCube from '../assets/dynatrace-logo-cube.png';
import dynatraceFull from '../assets/dynatrace-logo-full.png';

function formatTimeAgo(dateStr) {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ── Header / tenant card ────────────────────────────────────

function TenantHeader({ data }) {
  return (
    <div
      className="rounded-xl shadow-sm px-8 py-7 relative overflow-hidden"
      style={{
        background: 'linear-gradient(135deg, #1496FF 0%, #0066B7 100%)',
        color: 'white',
      }}
    >
      <div
        aria-hidden
        className="absolute -right-16 -top-16 w-72 h-72 opacity-15 pointer-events-none"
        style={{
          background:
            'radial-gradient(circle at 35% 35%, rgba(255,255,255,0.95) 0%, rgba(255,255,255,0) 60%)',
        }}
      />
      <div className="flex items-center gap-5 mb-5">
        <div className="w-[72px] h-[72px] rounded-xl bg-white/10 flex items-center justify-center backdrop-blur-sm p-2">
          <img src={dynatraceCube} alt="Dynatrace" className="w-full h-full object-contain" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-[0.28em] text-white/70 mb-1">
            Dynatrace Davis · live tenant
          </p>
          <h1 className="text-2xl font-bold text-white">
            {data.tenant}.apps.dynatrace.com
          </h1>
          <p className="text-[11px] font-mono text-white/60 mt-1">
            {data.token_prefix || ''} · platform token
          </p>
        </div>
        <div className="flex items-center gap-2">
          {data.dashboard_url && (
            <a
              href={data.dashboard_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-[11px] font-bold uppercase tracking-wider px-3 py-2 rounded-md bg-white/15 hover:bg-white/25 transition-colors"
            >
              Dashboard
              <Icon name="open_in_new" className="text-[14px]" />
            </a>
          )}
          {data.notebook_url && (
            <a
              href={data.notebook_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-[11px] font-bold uppercase tracking-wider px-3 py-2 rounded-md bg-white/15 hover:bg-white/25 transition-colors"
            >
              Notebook
              <Icon name="open_in_new" className="text-[14px]" />
            </a>
          )}
          <a
            href={data.apps_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-[11px] font-bold uppercase tracking-wider px-3 py-2 rounded-md bg-white/15 hover:bg-white/25 transition-colors"
          >
            Tenant
            <Icon name="open_in_new" className="text-[14px]" />
          </a>
        </div>
      </div>
    </div>
  );
}

// ── KPI row ─────────────────────────────────────────────────

function KpiRow({ data }) {
  const tiles = [
    { label: 'Events · 1h', value: data.events_last_hour ?? 0, accent: '#0066B7' },
    { label: 'Raised', value: data.events_breakdown?.created ?? 0, accent: '#9B2D2D' },
    { label: 'Resolved', value: data.events_breakdown?.resolved ?? 0, accent: '#4D7158' },
  ];
  return (
    <div className="grid grid-cols-3 gap-4">
      {tiles.map((t) => (
        <div
          key={t.label}
          className="bg-surface-container-lowest rounded-xl shadow-sm px-6 py-5 flex flex-col gap-1 relative overflow-hidden"
        >
          <span
            className="absolute left-0 top-0 bottom-0 w-1"
            style={{ background: t.accent }}
            aria-hidden
          />
          <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant pl-2">
            {t.label}
          </p>
          <p className="text-3xl font-bold tabular-nums text-on-surface pl-2">{t.value}</p>
        </div>
      ))}
    </div>
  );
}

// ── Capability matrix ───────────────────────────────────────

function CapabilityCard({ data }) {
  const caps = data.capabilities || {};
  const meta = {
    events: { label: 'Events ingest', desc: 'CUSTOM_DEPLOYMENT writes per finding lifecycle' },
    logs: { label: 'Log ingest', desc: 'Structured Parity log lines into Grail `logs` table' },
    bizevents: { label: 'Bizevents ingest', desc: 'CloudEvents-shaped finding lifecycle' },
    metrics: { label: 'Metrics ingest', desc: 'Counter `parity.findings{action,severity}`' },
    entities: { label: 'Custom Devices', desc: 'Attach events to per-router Dynatrace entities' },
  };
  return (
    <div className="bg-surface-container-lowest rounded-xl shadow-sm p-6">
      <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1">
        Capability matrix
      </p>
      <h3 className="text-lg font-bold text-on-surface mb-4">Platform token scopes</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {Object.entries(meta).map(([k, m]) => {
          const granted = caps[k];
          return (
            <div
              key={k}
              className={`flex items-start gap-3 p-3 rounded-lg border ${
                granted
                  ? 'border-secondary/30 bg-secondary/5'
                  : 'border-outline/30 bg-surface-container-low/30'
              }`}
            >
              <Icon
                name={granted ? 'check_circle' : 'pending'}
                className={`text-[20px] mt-0.5 shrink-0 ${
                  granted ? 'text-secondary' : 'text-on-surface-variant/50'
                }`}
                fill={!!granted}
              />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-on-surface">{m.label}</p>
                <p className="text-[11px] text-on-surface-variant mt-0.5">{m.desc}</p>
                <p className="text-[10px] font-bold uppercase tracking-wider mt-1.5">
                  {granted ? (
                    <span className="text-secondary">Granted · active</span>
                  ) : (
                    <span className="text-on-surface-variant/60">
                      Awaiting scope · code wired
                    </span>
                  )}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Davis Event Timeline ────────────────────────────────────

function DavisTimeline() {
  // Source filter: 'both' includes finding-lifecycle (source==parity) AND
  // per-snapshot device-metric / rollup events (source==parity-self).
  // Users can narrow with the pill to focus on just one feed.
  const [filter, setFilter] = useState('both');
  const sourcesParam =
    filter === 'findings' ? 'parity'
      : filter === 'self' ? 'parity-self'
        : 'parity,parity-self';
  // Re-fetch when the pill changes by including sourcesParam in deps.
  const { data, loading, refetch } = useApi(
    () => api.dtEvents('-1h', 200, sourcesParam),
    [sourcesParam],
  );
  const [open, setOpen] = useState(true);
  const records = data?.records || [];
  // Only the ACTIVE filter knows its real count; the inactive ones
  // can't (we only fetched the matching source set). Previously we
  // tried to derive findingCount/selfCount from `records`, which
  // showed '0' for the inactive button until the user clicked it —
  // confusing. Now: count badge only on the active pill.
  const Pill = ({ value, label, title }) => (
    <button
      type="button"
      onClick={() => setFilter(value)}
      title={title}
      className={`text-[10px] font-bold uppercase tracking-wider px-2.5 py-1 rounded-full transition-colors ${
        filter === value
          ? 'bg-primary text-on-primary'
          : 'bg-surface-container-high text-on-surface-variant hover:bg-surface-container-highest'
      }`}
    >
      {label}
      {filter === value && (
        <span className="ml-1.5 opacity-80 font-mono">{records.length}</span>
      )}
    </button>
  );
  return (
    <div className="bg-surface-container-lowest rounded-xl shadow-sm p-6">
      <div className="flex items-center justify-between mb-4">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-3 text-left hover:opacity-90 transition-opacity"
          aria-expanded={open}
        >
          <div
            className="w-12 h-12 rounded-lg flex items-center justify-center shrink-0 p-1.5"
            style={{ background: 'linear-gradient(135deg, #1496FF 0%, #0066B7 100%)' }}
          >
            <img src={dynatraceCube} alt="Dynatrace" className="w-full h-full object-contain" />
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-0.5">
              Round-trip · last hour · DQL fetch events filter source in (parity, parity-self)
            </p>
            <h3 className="text-lg font-bold text-on-surface inline-flex items-center gap-2">
              Davis Event Timeline
              <span className="text-[10px] font-mono font-normal text-on-surface-variant px-1.5 py-0.5 rounded bg-surface-container-high">
                {records.length}
              </span>
              <Icon name={open ? 'expand_less' : 'expand_more'} className="text-on-surface-variant" />
            </h3>
          </div>
        </button>
        <div className="flex items-center gap-2">
          <Pill
            value="both"
            label="All"
            title="Both finding-lifecycle events (source=parity) and per-snapshot device-metric / rollup events (source=parity-self)"
          />
          <Pill
            value="findings"
            label="Findings only"
            title="Only finding lifecycle events Parity emits when raising or resolving findings (source=parity, CUSTOM_DEPLOYMENT type)"
          />
          <Pill
            value="self"
            label="Self / Device only"
            title="Per-snapshot device metrics + the 60s self-monitor rollups (source=parity-self, CUSTOM_INFO type)"
          />
          <button
            onClick={refetch}
            className="text-xs font-semibold text-primary hover:underline inline-flex items-center gap-1 ml-2"
          >
            <Icon name="refresh" className="text-[14px]" />
            Refresh
          </button>
        </div>
      </div>

      {!open ? null : loading && !data ? (
        <div className="flex items-center gap-3 py-8">
          <div className="w-4 h-4 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
          <span className="text-sm text-on-surface-variant">Querying Grail via DQL…</span>
        </div>
      ) : !data?.configured ? (
        <div className="flex flex-col items-center justify-center py-10 text-on-surface-variant">
          <Icon name="cloud_off" className="text-5xl mb-2 opacity-30" />
          <p className="text-sm">Dynatrace integration not configured.</p>
        </div>
      ) : records.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-on-surface-variant">
          <Icon name="hourglass_empty" className="text-5xl mb-2 opacity-30" />
          <p className="text-sm font-medium">No Parity events in Davis yet.</p>
          <p className="text-xs">A finding will appear here within ~20s of being raised.</p>
        </div>
      ) : (
        <div className="space-y-2 overflow-y-auto pr-2 -mr-2" style={{ maxHeight: 520 }}>
          {records.map((rec, i) => {
            const isFinding = rec.source === 'parity';
            const isCreated = rec.action === 'created';
            const sevColor = {
              critical: 'bg-error/10 text-error',
              high: 'bg-error/10 text-error',
              medium: 'bg-tertiary/10 text-tertiary',
              low: 'bg-primary/10 text-primary',
            }[(rec.severity || '').toLowerCase()] || 'bg-outline/10 text-on-surface-variant';
            // For self/device events, the operator-friendly summary is the
            // metric name + category, not severity/action.
            const subtitle = isFinding
              ? `${rec.device || '—'} · ${rec.category || '—'} · event ${(rec.event_id || '').slice(-10)}`
              : `${rec.device || '—'} · ${rec.self_category || '—'}${rec.metric_name ? ` · ${rec.metric_name}` : ''}`;
            return (
              <div
                key={rec.event_id || i}
                className="flex items-center gap-4 py-3 px-4 rounded-lg hover:bg-surface-container-low/50 transition-colors border border-outline-variant/20"
              >
                <div
                  className={`w-2.5 h-2.5 rounded-full shrink-0 ${
                    isFinding
                      ? (isCreated ? 'bg-error animate-pulse' : 'bg-secondary')
                      : 'bg-primary/60'
                  }`}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <p className="text-sm font-semibold text-on-surface truncate">
                      {rec.title || '(untitled)'}
                    </p>
                    <span
                      className={`text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded ${
                        isFinding ? 'bg-error/10 text-error' : 'bg-primary/10 text-primary'
                      }`}
                      title={`source=${rec.source}`}
                    >
                      {isFinding ? 'finding' : 'self'}
                    </span>
                    {isFinding && (
                      <>
                        <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${sevColor}`}>
                          {rec.severity || '—'}
                        </span>
                        <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-surface-container-high text-on-surface-variant">
                          {rec.action || '—'}
                        </span>
                      </>
                    )}
                  </div>
                  <p className="text-xs text-on-surface-variant truncate font-mono">
                    {subtitle}
                  </p>
                </div>
                <span className="text-xs text-on-surface-variant whitespace-nowrap shrink-0">
                  {formatTimeAgo(rec.timestamp)}
                </span>
              </div>
            );
          })}
          {data.tenant_url && (
            <a
              href={data.tenant_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-primary text-sm font-semibold mt-2 hover:underline"
            >
              Open in Dynatrace
              <Icon name="open_in_new" className="text-[14px]" />
            </a>
          )}
        </div>
      )}
    </div>
  );
}

// ── Davis Problems panel ────────────────────────────────────

function DavisProblems() {
  const { data, loading } = useApi(api.dtDavisProblems);
  const records = data?.records || [];
  return (
    <div className="bg-surface-container-lowest rounded-xl shadow-sm p-6">
      <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1">
        Davis problems · last 24h · DQL fetch dt.davis.problems
      </p>
      <h3 className="text-lg font-bold text-on-surface mb-4">Upstream Davis Problems</h3>
      {loading && !data ? (
        <div className="flex items-center gap-3 py-6">
          <div className="w-4 h-4 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
          <span className="text-sm text-on-surface-variant">Querying Davis…</span>
        </div>
      ) : !data?.configured ? (
        <p className="text-sm text-on-surface-variant py-4">Not configured.</p>
      ) : records.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-8 text-on-surface-variant">
          <Icon name="check_circle" className="text-5xl mb-2 text-secondary/40" fill />
          <p className="text-sm font-medium">No active Davis problems.</p>
          <p className="text-xs">
            Tenant is OneAgent-free; the Davis lifecycle here is fed by Parity-emitted events.
          </p>
        </div>
      ) : (
        <ul className="divide-y divide-outline-variant/30">
          {records.slice(0, 8).map((r, i) => (
            <li key={i} className="py-3 text-sm">
              <p className="font-semibold text-on-surface">{r['event.name'] || r.title || '(untitled)'}</p>
              <p className="text-xs text-on-surface-variant font-mono">
                {r.timestamp || r['event.start']}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Davis Copilot assessments — stacked, scrollable, Jira-tagged ──

function DavisAssessment() {
  // Pull more findings + the approval history so we can map each
  // davis-touched finding to its Jira PSR ticket.
  const { data: findings, loading: fLoad } = useApi(() =>
    api.findings({ limit: 100, include_resolved: true })
  );
  const { data: approvals } = useApi(() => api.approvals());
  const { data: history } = useApi(() => api.approvalHistory());

  const list = Array.isArray(findings) ? findings : findings?.items || [];
  const allApprovals = [
    ...(Array.isArray(approvals) ? approvals : []),
    ...(Array.isArray(history) ? history : []),
  ];
  // Build finding_id → first jira_key map
  const jiraByFinding = {};
  for (const a of allApprovals) {
    const fid = a?.finding?.id;
    if (fid && a.jira_key && !jiraByFinding[fid]) {
      jiraByFinding[fid] = { key: a.jira_key, url: a.jira_url };
    }
  }

  const withDavis = list
    .filter((f) => (f?.evidence || {}).davis_assessment)
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

  const [open, setOpen] = useState(true);

  return (
    <div className="bg-surface-container-lowest rounded-xl shadow-sm p-6 flex flex-col" style={{ maxHeight: open ? 640 : 100 }}>
      <div className="flex items-start justify-between mb-4">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex flex-col text-left hover:opacity-90 transition-opacity"
          aria-expanded={open}
        >
          <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1">
            Davis Copilot second opinions · via real MCP
          </p>
          <h3 className="text-lg font-bold text-on-surface inline-flex items-center gap-2">
            Davis on Gemini
            <Icon name={open ? 'expand_less' : 'expand_more'} className="text-on-surface-variant" />
          </h3>
        </button>
        <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-md text-on-surface-variant bg-surface-container-high">
          {withDavis.length} {withDavis.length === 1 ? 'assessment' : 'assessments'}
        </span>
      </div>

      {open && (fLoad && !findings ? (
        <div className="flex items-center gap-3 py-6">
          <div className="w-4 h-4 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
          <span className="text-sm text-on-surface-variant">Looking…</span>
        </div>
      ) : withDavis.length === 0 ? (
        <p className="text-sm text-on-surface-variant py-4">
          No findings carry a Davis assessment yet. Trigger a Parity scenario and watch this fill in.
        </p>
      ) : (
        <div className="overflow-y-auto pr-2 -mr-2 space-y-3 flex-1">
          {withDavis.map((f) => {
            const jira = jiraByFinding[f.id];
            const sev = (f.severity || '').toLowerCase();
            const sevColor = {
              critical: 'bg-error/10 text-error',
              high: 'bg-error/10 text-error',
              medium: 'bg-tertiary/10 text-tertiary',
              low: 'bg-primary/10 text-primary',
            }[sev] || 'bg-outline/10 text-on-surface-variant';
            return (
              <div
                key={f.id}
                className="rounded-lg border border-outline/20 bg-surface-container-low/30 p-4"
              >
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                  {jira ? (
                    <a
                      href={jira.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      title="Open in Jira"
                      className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md text-white hover:brightness-110 transition-all"
                      style={{ background: '#0052CC' }}
                    >
                      <Icon name="confirmation_number" className="text-[12px]" />
                      {jira.key}
                    </a>
                  ) : f.requires_remediation ? (
                    /* Actionable but no approval yet — chip explains
                       the transient state rather than a bald "no ticket". */
                    <span
                      className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md text-on-surface-variant bg-surface-container-high"
                      title="Recommendation queued — Jira ticket created when the Approval row is opened"
                    >
                      <Icon name="hourglass_empty" className="text-[12px]" />
                      ticket pending
                    </span>
                  ) : (
                    /* The most common case: the finding is advisory
                       (no remediation needed), so Parity intentionally
                       did not open a Jira ticket. Make that explicit. */
                    <span
                      className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md text-on-surface-variant bg-surface-container-high"
                      title="Advisory finding — Parity did not open a Jira ticket because no remediation is required"
                    >
                      <Icon name="info" className="text-[12px]" />
                      advisory · no jira
                    </span>
                  )}
                  <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${sevColor}`}>
                    {f.severity || '—'}
                  </span>
                  <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-surface-container-high text-on-surface-variant">
                    {f.category || '—'}
                  </span>
                  <span className="text-[10px] font-mono text-on-surface-variant ml-auto">
                    {f.created_at && new Date(f.created_at).toLocaleString()}
                  </span>
                </div>
                <p className="text-sm font-semibold text-on-surface mb-2 truncate">
                  {f.title}
                </p>
                <blockquote
                  className="border-l-4 px-3 py-2 italic text-sm text-on-surface bg-surface-container-low/60 rounded-r"
                  style={{ borderLeftColor: '#0066B7' }}
                >
                  {(f.evidence || {}).davis_assessment}
                </blockquote>
                <div className="flex items-center gap-3 mt-2 text-[10px] font-mono text-on-surface-variant">
                  <span>{f.affected_entity}</span>
                  <span>·</span>
                  <span>finding {f.id.slice(0, 8)}</span>
                </div>
              </div>
            );
          })}
        </div>
      ))}

      {open && (
        <p className="text-[11px] text-on-surface-variant mt-3 pt-3 border-t border-outline/10">
          Source: <code className="font-mono">chat_with_davis_copilot</code> via @dynatrace-oss/dynatrace-mcp-server v1.8.5
        </p>
      )}
    </div>
  );
}

// ── Page ────────────────────────────────────────────────────

export default function Dynatrace() {
  const { data, loading, error } = useApi(api.dtStatus);

  if (loading && !data) {
    return (
      <div className="p-8">
        <div className="flex items-center gap-3 text-on-surface-variant">
          <div className="w-4 h-4 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
          <span>Querying Dynatrace…</span>
        </div>
      </div>
    );
  }

  if (!data?.configured) {
    return (
      <div className="p-8 max-w-2xl">
        <div className="bg-surface-container-lowest rounded-xl shadow-sm p-8 border border-outline/30">
          <div className="flex items-center gap-3 mb-3">
            <Icon name="cloud_off" className="text-on-surface-variant text-[24px]" />
            <h1 className="text-xl font-bold text-on-surface">Dynatrace not configured</h1>
          </div>
          <p className="text-sm text-on-surface-variant">
            Set <code className="font-mono">DT_ENVIRONMENT</code> and <code className="font-mono">DT_PLATFORM_TOKEN</code> in <code className="font-mono">.env</code>, then restart the backend.
          </p>
          {error && (
            <pre className="mt-4 text-xs text-error font-mono">{String(error)}</pre>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-6">
      <TenantHeader data={data} />
      <KpiRow data={data} />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <DavisTimeline />
          <DavisAssessment />
        </div>
        <div className="space-y-6">
          <CapabilityCard data={data} />
          <DavisProblems />
        </div>
      </div>
    </div>
  );
}
