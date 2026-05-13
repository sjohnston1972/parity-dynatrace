import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import { usePipelineEvents } from '../hooks/usePipelineEvents';
import { api } from '../api/client';
import Icon from '../components/Icon';
import StatusChip from '../components/StatusChip';

const MODEL_COLORS = {
  opus: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  sonnet: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  haiku: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  ollama: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
};

function modelChip(model) {
  if (!model) return null;
  const key = Object.keys(MODEL_COLORS).find((k) => model.toLowerCase().includes(k));
  const cls = MODEL_COLORS[key] || 'bg-surface-container-high text-on-surface-variant';
  const label = key ? key.charAt(0).toUpperCase() + key.slice(1) : model;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase border ${cls}`}>
      {label}
    </span>
  );
}

const SEVERITY_COLORS = {
  critical: 'text-red-400',
  high: 'text-orange-400',
  medium: 'text-amber-400',
  low: 'text-blue-400',
  info: 'text-on-surface-variant',
};

const SEVERITY_ICONS = {
  critical: 'error',
  high: 'warning',
  medium: 'info',
  low: 'check_circle',
  info: 'help',
};

function severityBadge(severity) {
  if (!severity) return null;
  const color = SEVERITY_COLORS[severity] || 'text-on-surface-variant';
  const icon = SEVERITY_ICONS[severity] || 'info';
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-semibold ${color}`}>
      <Icon name={icon} className="text-sm" />
      {severity.toUpperCase()}
    </span>
  );
}

const RISK_COLORS = {
  low: 'text-emerald-400',
  medium: 'text-amber-400',
  high: 'text-red-400',
};

function statusToChip(entry) {
  const status = entry.status?.toLowerCase();
  const result = entry.execution_result;
  const success = result && !result.error && result.success !== false;

  if (status === 'executed' || status === 'success') {
    if (result && !success) {
      return <StatusChip variant="error">FAILED</StatusChip>;
    }
    return <StatusChip variant="success">SUCCESS</StatusChip>;
  }
  if (status === 'failed') return <StatusChip variant="error">FAILED</StatusChip>;
  if (status === 'approved') return <StatusChip variant="info">APPROVED</StatusChip>;
  if (status === 'denied') return <StatusChip variant="neutral">DENIED</StatusChip>;
  return <StatusChip variant="neutral">{(status || 'UNKNOWN').toUpperCase()}</StatusChip>;
}

function formatTimestamp(ts) {
  if (!ts) return '\u2014';
  try {
    const date = new Date(ts);
    const now = new Date();
    const diffMs = now - date;
    const diffMin = Math.floor(diffMs / 60000);
    const diffHr = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHr / 24);

    if (diffMin < 1) return 'Just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHr < 24) return `${diffHr}h ago`;
    if (diffDay < 7) return `${diffDay}d ago`;
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return ts;
  }
}

function CommandOutputBlock({ outputs }) {
  if (!outputs || outputs.length === 0) return null;
  return (
    <div className="space-y-2">
      {outputs.map((o, i) => (
        <div key={i} className="rounded-lg overflow-hidden border border-surface-container-high">
          <div className={`flex items-center gap-2 px-3 py-1.5 text-xs font-mono ${o.success !== false ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
            <Icon name={o.success !== false ? 'check_circle' : 'cancel'} className="text-sm" />
            <span>{o.command || '?'}</span>
          </div>
          {o.output && (
            <pre className="px-3 py-2 text-xs text-on-surface-variant bg-surface-container-lowest font-mono whitespace-pre-wrap max-h-40 overflow-y-auto">
              {o.output}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}

function ExecutionCard({ entry, expanded, onToggle }) {
  const rec = entry.recommendation || {};
  const finding = entry.finding || {};
  const device = entry.device || {};
  const result = entry.execution_result || {};
  const hasExecution = entry.status === 'executed' || entry.status === 'failed';

  return (
    <div className="bg-surface-container-lowest rounded-xl overflow-hidden border border-surface-container-high/50">
      {/* Summary row — always visible */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-4 px-5 py-4 text-left hover:bg-surface-container-low/50 transition-colors"
      >
        <Icon
          name={expanded ? 'expand_less' : 'expand_more'}
          className="text-xl text-on-surface-variant shrink-0"
        />

        {/* Finding title + severity */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-on-surface truncate">
              {finding.title || rec.action_description || rec.action || 'Remediation'}
            </span>
            {severityBadge(finding.severity)}
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-xs text-on-surface-variant">{device.hostname || '\u2014'}</span>
            {finding.affected_entity && (
              <>
                <span className="text-xs text-outline">/</span>
                <span className="text-xs text-on-surface-variant font-mono">{finding.affected_entity}</span>
              </>
            )}
          </div>
        </div>

        {/* Model chips */}
        <div className="hidden sm:flex items-center gap-1.5 shrink-0">
          {modelChip(finding.agent_model)}
          {modelChip(rec.agent_model)}
        </div>

        {/* Status */}
        <div className="shrink-0">{statusToChip(entry)}</div>

        {/* Timestamp */}
        <span className="text-xs text-on-surface-variant whitespace-nowrap shrink-0 w-16 text-right">
          {formatTimestamp(entry.executed_at || entry.approved_at)}
        </span>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-surface-container-high px-5 py-4 space-y-5">
          {/* Model tags for mobile */}
          <div className="flex sm:hidden items-center gap-1.5 flex-wrap">
            {finding.agent_model && <>{modelChip(finding.agent_model)} <span className="text-[10px] text-on-surface-variant">analysis</span></>}
            {rec.agent_model && <>{modelChip(rec.agent_model)} <span className="text-[10px] text-on-surface-variant">remediation</span></>}
          </div>

          {/* AI Reasoning */}
          {rec.reasoning && (
            <div>
              <h4 className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant mb-1.5">
                AI Reasoning
              </h4>
              <p className="text-sm text-on-surface leading-relaxed">{rec.reasoning}</p>
            </div>
          )}

          {/* Risk level */}
          {rec.risk_level && (
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">Risk:</span>
              <span className={`text-sm font-semibold ${RISK_COLORS[rec.risk_level] || 'text-on-surface-variant'}`}>
                {rec.risk_level.toUpperCase()}
              </span>
            </div>
          )}

          {/* Commands executed with outputs */}
          {hasExecution && result.outputs && (
            <div>
              <h4 className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant mb-1.5">
                Commands Executed
                {result.duration_seconds != null && (
                  <span className="ml-2 font-normal normal-case tracking-normal text-outline">
                    ({result.duration_seconds}s)
                  </span>
                )}
              </h4>
              <CommandOutputBlock outputs={result.outputs} />
            </div>
          )}

          {/* Commands planned (not yet executed) */}
          {!hasExecution && rec.commands && rec.commands.length > 0 && (
            <div>
              <h4 className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant mb-1.5">
                Planned Commands
              </h4>
              <div className="bg-surface-container-lowest rounded-lg border border-surface-container-high p-3">
                <pre className="text-xs font-mono text-on-surface-variant whitespace-pre-wrap">
                  {rec.commands.map((c) => typeof c === 'string' ? c : c.command || JSON.stringify(c)).join('\n')}
                </pre>
              </div>
            </div>
          )}

          {/* Rollback commands */}
          {rec.rollback_commands && rec.rollback_commands.length > 0 && (
            <div>
              <h4 className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant mb-1.5">
                Rollback Commands
              </h4>
              <div className="bg-surface-container-lowest rounded-lg border border-amber-500/20 p-3">
                <pre className="text-xs font-mono text-amber-400/80 whitespace-pre-wrap">
                  {rec.rollback_commands.map((c) => typeof c === 'string' ? c : c.command || JSON.stringify(c)).join('\n')}
                </pre>
              </div>
            </div>
          )}

          {/* Approval metadata + Jira link */}
          <div className="flex items-center gap-4 flex-wrap text-xs text-on-surface-variant">
            {entry.approved_by && (
              <span>
                <Icon name="person" className="text-sm align-middle mr-0.5" />
                {entry.approved_by}
              </span>
            )}
            {entry.approved_via && (
              <span>
                via {entry.approved_via}
              </span>
            )}
            {entry.notes && (
              <span className="italic">"{entry.notes}"</span>
            )}
            {entry.jira_url && (
              <a
                href={entry.jira_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-blue-400 hover:text-blue-300 transition-colors"
              >
                <Icon name="link" className="text-sm" />
                {entry.jira_key || 'Jira'}
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Executions() {
  const { data: history, loading, error, refetch } = useApi(() => api.approvalHistory());
  const [expandedId, setExpandedId] = useState(null);

  usePipelineEvents(() => refetch());

  const entries = history || [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-4xl font-extrabold text-on-surface">Execution Log</h1>
        <p className="mt-1 text-sm text-on-surface-variant">
          History of approved remediations — commands, reasoning, and outcomes
        </p>
      </div>

      {/* Error state */}
      {error && (
        <div className="bg-error/10 text-error rounded-xl px-4 py-3 text-sm">
          Failed to load execution history: {error.message}
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="flex items-center justify-center py-20 text-on-surface-variant">
          <Icon name="progress_activity" className="text-3xl animate-spin" />
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && entries.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <Icon name="history" className="text-5xl text-outline" />
          <p className="text-lg font-semibold text-on-surface">No execution history</p>
          <p className="text-sm text-on-surface-variant">
            Approved remediations will appear here after execution
          </p>
        </div>
      )}

      {/* Entry cards */}
      {!loading && entries.length > 0 && (
        <div className="space-y-3">
          {entries.map((entry) => (
            <ExecutionCard
              key={entry.id}
              entry={entry}
              expanded={expandedId === entry.id}
              onToggle={() => setExpandedId(expandedId === entry.id ? null : entry.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
