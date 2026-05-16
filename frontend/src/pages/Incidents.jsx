import { useMemo, useState } from 'react';
import { useApi } from '../hooks/useApi';
import { api } from '../api/client';
import Icon from '../components/Icon';
import DynatracePill from '../components/DynatracePill';
import dynatraceCube from '../assets/dynatrace-logo-cube.png';

function fmtAgo(dateStr) {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function sevClass(s) {
  return {
    critical: 'bg-error/10 text-error border-error/30',
    high:     'bg-error/10 text-error border-error/30',
    medium:   'bg-tertiary/10 text-tertiary border-tertiary/30',
    low:      'bg-primary/10 text-primary border-primary/30',
    info:     'bg-outline/10 text-on-surface-variant border-outline/30',
  }[(s || '').toLowerCase()] || 'bg-outline/10 text-on-surface-variant border-outline/30';
}

export default function Incidents() {
  const { data: incidents, loading: lIncidents } = useApi(api.incidents);
  const { data: findings } = useApi(() => api.findings({ limit: 200, include_resolved: true }));
  const { data: approvals } = useApi(() => api.approvals());
  const { data: history } = useApi(() => api.approvalHistory());
  const { data: dtEvents } = useApi(() => api.dtEvents('-24h', 500));
  const { data: dtStatus } = useApi(api.dtStatus);

  const [filter, setFilter] = useState('all');

  // Joins built from existing endpoints — keeps the page schema-free.
  const enriched = useMemo(() => {
    const findingsList = Array.isArray(findings) ? findings : findings?.items || [];
    const allApprovals = [
      ...(Array.isArray(approvals) ? approvals : []),
      ...(Array.isArray(history) ? history : []),
    ];
    const events = dtEvents?.records || [];
    const byIncident = {};
    for (const f of findingsList) {
      const k = f.incident_id || f.id;
      if (!byIncident[k]) byIncident[k] = [];
      byIncident[k].push(f);
    }
    const approvalsByFinding = {};
    for (const a of allApprovals) {
      const fid = a?.finding?.id;
      if (fid && !approvalsByFinding[fid]) approvalsByFinding[fid] = a;
    }
    const eventsByFinding = {};
    for (const e of events) {
      const fid = e.finding_id;
      if (!fid) continue;
      if (!eventsByFinding[fid]) eventsByFinding[fid] = [];
      eventsByFinding[fid].push(e);
    }

    return (incidents || []).map((inc) => {
      const fs = byIncident[inc.id] || [];
      const root = fs.find((f) => f.is_root_cause) || fs[0] || inc.root_cause || {};
      const apprs = fs.map((f) => approvalsByFinding[f.id]).filter(Boolean);
      const events = fs.flatMap((f) => eventsByFinding[f.id] || []);

      // Token accounting — sum across findings if their tokens_used is populated
      const tokens = { input: 0, output: 0, thoughts: 0 };
      for (const f of fs) {
        const t = f.tokens_used;
        if (t && typeof t === 'object') {
          tokens.input += Number(t.input || 0);
          tokens.output += Number(t.output || 0);
          tokens.thoughts += Number(t.thoughts || 0);
        }
      }
      const totalTokens = tokens.input + tokens.output + tokens.thoughts;

      // Resolved status
      const allResolved = fs.every(
        (f) => !f.requires_remediation || (f.evidence || {}).resolved
      );
      const anyEscalated = fs.some((f) => f.severity === 'critical');

      return {
        id: inc.id,
        title: root.title || inc.root_cause?.title || 'Untitled incident',
        severity: inc.max_severity || root.severity,
        category: root.category || inc.root_cause?.category,
        affected_devices: inc.affected_devices || [],
        finding_count: inc.finding_count || fs.length,
        created_at: inc.created_at,
        gemini_model: root.agent_model || inc.root_cause?.agent_model,
        gemini_reasoning: root.description || inc.root_cause?.description,
        davis_assessment: (root.evidence || {}).davis_assessment
          || (inc.root_cause?.evidence || {}).davis_assessment,
        recommendation_commands: (root.evidence || {}).remediation_commands || [],
        jira: apprs[0]?.jira_key
          ? { key: apprs[0].jira_key, url: apprs[0].jira_url, status: apprs[0].status }
          : null,
        davis_event_count: events.length,
        davis_event_breakdown: {
          created: events.filter((e) => e.action === 'created').length,
          resolved: events.filter((e) => e.action === 'resolved').length,
        },
        tokens, totalTokens,
        resolved: allResolved,
        escalated: anyEscalated,
        root,
      };
    }).sort((a, b) =>
      new Date(b.created_at || 0) - new Date(a.created_at || 0)
    );
  }, [incidents, findings, approvals, history, dtEvents]);

  const shown = enriched.filter((i) => {
    if (filter === 'all') return true;
    if (filter === 'active') return !i.resolved;
    if (filter === 'resolved') return i.resolved;
    return true;
  });

  return (
    <div className="p-8 max-w-[1440px] mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="w-2 h-2 rounded-full bg-primary" />
            <span className="text-xs font-medium text-on-surface-variant">
              Operations · Incident archive
            </span>
          </div>
          <h1 className="text-3xl font-bold text-on-surface">Incident Log</h1>
          <p className="text-sm text-on-surface-variant mt-1 max-w-2xl">
            Every incident Parity has opened, with the full audit trail:
            Gemini's reasoning, Davis Copilot's second opinion, Jira ticket,
            Dynatrace events emitted, token accounting, and execution status.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {[
            { key: 'all', label: 'All' },
            { key: 'active', label: 'Active' },
            { key: 'resolved', label: 'Resolved' },
          ].map((p) => (
            <button
              key={p.key}
              onClick={() => setFilter(p.key)}
              className={`px-3 py-1.5 rounded-md text-xs font-bold uppercase tracking-wider transition-colors ${
                filter === p.key
                  ? 'bg-primary text-white'
                  : 'bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Summary tile */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        <SummaryTile label="Incidents" value={enriched.length} />
        <SummaryTile label="Active" value={enriched.filter((i) => !i.resolved).length} accent="#9B2D2D" />
        <SummaryTile label="Resolved" value={enriched.filter((i) => i.resolved).length} accent="#4D7158" />
        <SummaryTile
          label="Davis events 24h"
          value={(dtEvents?.records || []).length}
          accent="#0066B7"
        />
        <SummaryTile
          label="Tokens used"
          value={enriched.reduce((s, i) => s + i.totalTokens, 0).toLocaleString()}
          accent="#4285F4"
        />
      </div>

      {/* Incident list */}
      {lIncidents && !incidents ? (
        <div className="flex items-center gap-3 py-8">
          <div className="w-4 h-4 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
          <span className="text-sm text-on-surface-variant">Loading…</span>
        </div>
      ) : shown.length === 0 ? (
        <div className="bg-surface-container-lowest rounded-xl shadow-sm p-10 text-center">
          <Icon name="check_circle" className="text-5xl text-secondary/40 mb-2" fill />
          <p className="text-sm font-medium text-on-surface">
            No {filter !== 'all' ? filter : ''} incidents.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {shown.map((inc) => (
            <IncidentRow key={inc.id} inc={inc} dtStatus={dtStatus} />
          ))}
        </div>
      )}
    </div>
  );
}

function SummaryTile({ label, value, accent = '#1F6FEB' }) {
  return (
    <div className="bg-surface-container-lowest rounded-xl shadow-sm px-5 py-4 flex flex-col gap-1 relative overflow-hidden">
      <span
        className="absolute left-0 top-0 bottom-0 w-1"
        style={{ background: accent }}
        aria-hidden
      />
      <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant pl-2">
        {label}
      </p>
      <p className="text-2xl font-bold tabular-nums text-on-surface pl-2">{value}</p>
    </div>
  );
}

function IncidentRow({ inc, dtStatus }) {
  const [expanded, setExpanded] = useState(false);
  const sev = (inc.severity || '').toLowerCase();
  const dtSearchUrl = dtStatus?.apps_url
    ? `${dtStatus.apps_url}/ui/apps/dynatrace.notebooks/notebook/parity-dynatrace-notebook-v1`
    : null;
  return (
    <div className="bg-surface-container-lowest rounded-xl shadow-sm overflow-hidden">
      {/* Compact row */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left flex items-center gap-4 p-5 hover:bg-surface-container-low/40 transition-colors"
      >
        <Icon name={expanded ? 'expand_less' : 'expand_more'} className="text-on-surface-variant" />
        <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md border ${sevClass(sev)}`}>
          {sev || '—'}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <h3 className="text-base font-bold text-on-surface truncate">{inc.title}</h3>
            <span className="text-[10px] font-mono text-on-surface-variant">
              {inc.affected_devices.join(', ')}
            </span>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {/* Gemini chip */}
            <span
              className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-md text-white"
              style={{ background: 'linear-gradient(135deg, #4285F4 0%, #34A853 50%, #FBBC04 100%)' }}
            >
              <Icon name="auto_awesome" className="text-[11px]" fill />
              {inc.gemini_model || 'Gemini'}
            </span>
            {/* Davis chip */}
            {inc.davis_assessment && (
              <span
                className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-md text-white"
                style={{ background: 'linear-gradient(135deg, #1496FF 0%, #0066B7 100%)' }}
              >
                <img src={dynatraceCube} alt="" className="w-4 h-4 object-contain" />
                Davis Copilot
              </span>
            )}
            {/* Jira chip */}
            {inc.jira && (
              <a
                href={inc.jira.url}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-md text-white hover:brightness-110"
                style={{ background: '#0052CC' }}
              >
                <Icon name="confirmation_number" className="text-[11px]" />
                {inc.jira.key} · {inc.jira.status || 'open'}
              </a>
            )}
            {/* Davis event count */}
            <span className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-md text-on-surface-variant bg-surface-container-high">
              {inc.davis_event_count} Davis events
            </span>
            {/* Status */}
            <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md ${
              inc.resolved
                ? 'bg-secondary/10 text-secondary'
                : 'bg-error/10 text-error'
            }`}>
              {inc.resolved ? 'Resolved' : 'Open'}
            </span>
            {inc.escalated && (
              <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md bg-error text-white">
                ESCALATED
              </span>
            )}
            <span className="text-[10px] text-on-surface-variant ml-auto">
              {fmtAgo(inc.created_at)}
            </span>
          </div>
        </div>
      </button>

      {/* Expanded panel */}
      {expanded && (
        <div className="border-t border-outline/20 px-5 py-5 bg-surface-container-low/30 space-y-4">
          {/* Gemini block */}
          <Block label="Gemini reasoning" accent="linear-gradient(135deg, #4285F4 0%, #34A853 50%, #FBBC04 100%)">
            <p className="text-sm text-on-surface leading-relaxed">
              {inc.gemini_reasoning || '(no reasoning recorded)'}
            </p>
          </Block>

          {/* Davis block */}
          {inc.davis_assessment ? (
            <Block label="Davis Copilot second opinion" accent="linear-gradient(135deg, #1496FF 0%, #0066B7 100%)">
              <blockquote className="text-sm italic text-on-surface">
                {inc.davis_assessment}
              </blockquote>
              <p className="text-[10px] font-mono text-on-surface-variant mt-2">
                via chat_with_davis_copilot · @dynatrace-oss/dynatrace-mcp-server
              </p>
            </Block>
          ) : (
            <p className="text-sm text-on-surface-variant italic">
              No Davis Copilot assessment attached to this incident.
            </p>
          )}

          {/* Remediation commands */}
          {inc.recommendation_commands.length > 0 && (
            <Block label="Remediation commands">
              <pre className="text-xs font-mono p-3 rounded bg-surface-container-low text-on-surface overflow-x-auto">
                {inc.recommendation_commands.join('\n')}
              </pre>
            </Block>
          )}

          {/* Bottom telemetry strip */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Telem label="Davis events" value={`${inc.davis_event_breakdown.created} raised · ${inc.davis_event_breakdown.resolved} resolved`} />
            <Telem label="MCP calls" value={inc.davis_assessment ? '≥ 1 (Davis second opinion)' : '0'} />
            <Telem label="Gemini calls" value="≥ 1 (primary verdict)" />
            <Telem
              label="Tokens"
              value={
                inc.totalTokens
                  ? `${inc.totalTokens.toLocaleString()} total · ${inc.tokens.input}/${inc.tokens.output}/${inc.tokens.thoughts}`
                  : '— (not tracked on this finding)'
              }
            />
          </div>

          {/* Footer actions */}
          <div className="flex items-center justify-between pt-3 border-t border-outline/15">
            <span className="text-[10px] font-mono text-on-surface-variant">
              incident {inc.id}
            </span>
            <div className="flex items-center gap-2">
              {inc.root?.id && (
                <DynatracePill finding={inc.root} />
              )}
              {dtSearchUrl && (
                <a
                  href={dtSearchUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-[11px] font-bold uppercase tracking-wider px-3 py-1.5 rounded-md text-white"
                  style={{ background: 'linear-gradient(135deg, #1496FF 0%, #0066B7 100%)' }}
                >
                  Open Notebook
                  <Icon name="open_in_new" className="text-[14px]" />
                </a>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Block({ label, accent, children }) {
  return (
    <div>
      <p
        className="inline-block text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-md text-white mb-2"
        style={{ background: accent || '#9097A0' }}
      >
        {label}
      </p>
      <div>{children}</div>
    </div>
  );
}

function Telem({ label, value }) {
  return (
    <div className="bg-surface-container-low rounded-md px-3 py-2">
      <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">{label}</p>
      <p className="text-xs font-mono text-on-surface mt-0.5">{value}</p>
    </div>
  );
}
