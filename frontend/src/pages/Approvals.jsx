import { useState, useEffect, useRef, useCallback } from 'react';
import { useApi } from '../hooks/useApi';
import { usePipelineEvents } from '../hooks/usePipelineEvents';
import { api } from '../api/client';
import Icon from '../components/Icon';
import StatusChip from '../components/StatusChip';

const severityVariant = (severity) => {
  switch (severity?.toUpperCase()) {
    case 'CRITICAL':
    case 'HIGH':
      return 'error';
    case 'MEDIUM':
      return 'neutral';
    case 'LOW':
      return 'success';
    default:
      return 'neutral';
  }
};

const statusConfig = {
  pending: { label: 'Pending', variant: 'warning', icon: 'schedule' },
  approved: { label: 'Executing', variant: 'info', icon: 'sync', spin: true },
  executed: { label: 'Complete', variant: 'success', icon: 'check_circle' },
  failed: { label: 'Failed', variant: 'error', icon: 'error' },
  denied: { label: 'Denied', variant: 'neutral', icon: 'block' },
  expired: { label: 'Expired', variant: 'neutral', icon: 'timer_off' },
};

function ApprovalCard({ approval, onApprove, onDeny }) {
  const [notes, setNotes] = useState('');
  const [showNotes, setShowNotes] = useState(false);
  const [acting, setActing] = useState(false);

  const finding = approval.finding || {};
  const recommendation = approval.recommendation || {};
  const device = approval.device || {};
  const commands = recommendation.commands || [];
  const rollbackCommands = recommendation.rollback_commands || [];
  const status = approval.status || 'pending';
  const sc = statusConfig[status] || statusConfig.pending;
  const isPending = status === 'pending';
  const isExecuting = status === 'approved';

  const handleApprove = async () => {
    setActing(true);
    try {
      await onApprove(approval.id, { notes });
    } finally {
      setActing(false);
    }
  };

  const handleDeny = async () => {
    setActing(true);
    try {
      await onDeny(approval.id, { notes });
    } finally {
      setActing(false);
    }
  };

  return (
    <div className={`bg-surface-container-lowest rounded-xl p-6 space-y-4 border-l-4 ${
      isExecuting ? 'border-primary' : isPending ? 'border-tertiary' : 'border-transparent'
    }`}>
      {/* Status + finding title */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <StatusChip variant={sc.variant} dot={isExecuting}>
              <span className="flex items-center gap-1">
                {sc.spin && (
                  <span className="inline-block w-3 h-3 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
                )}
                {sc.label}
              </span>
            </StatusChip>
            <StatusChip variant={severityVariant(finding.severity)}>
              {(finding.severity || 'UNKNOWN').toUpperCase()}
            </StatusChip>
            {finding.agent_model && (
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wide ${
                finding.agent_model.toLowerCase().includes('opus')
                  ? 'bg-purple-500/15 text-purple-400 ring-1 ring-purple-500/30'
                  : finding.agent_model.toLowerCase().includes('sonnet')
                    ? 'bg-blue-500/15 text-blue-400 ring-1 ring-blue-500/30'
                    : finding.agent_model.toLowerCase().includes('haiku')
                      ? 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/30'
                      : 'bg-surface-container-high text-on-surface-variant'
              }`}>
                {finding.agent_model} — analysis
              </span>
            )}
            {recommendation.agent_model && (
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wide ${
                recommendation.agent_model.toLowerCase().includes('opus')
                  ? 'bg-purple-500/15 text-purple-400 ring-1 ring-purple-500/30'
                  : recommendation.agent_model.toLowerCase().includes('sonnet')
                    ? 'bg-blue-500/15 text-blue-400 ring-1 ring-blue-500/30'
                    : recommendation.agent_model.toLowerCase().includes('haiku')
                      ? 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/30'
                      : 'bg-surface-container-high text-on-surface-variant'
              }`}>
                {recommendation.agent_model} — remediation
              </span>
            )}
          </div>
          <h3 className="text-lg font-bold text-on-surface leading-tight">
            {finding.title || 'Untitled Finding'}
          </h3>
        </div>
      </div>

      {/* Device info */}
      <div className="flex items-center gap-4 text-sm text-on-surface-variant">
        <span className="inline-flex items-center gap-1.5">
          <Icon name="dns" className="text-[18px]" />
          {device.hostname || 'Unknown device'}
        </span>
        {finding.affected_entity && (
          <span className="inline-flex items-center gap-1.5">
            <Icon name="settings_ethernet" className="text-[18px]" />
            {finding.affected_entity}
          </span>
        )}
      </div>

      {/* Recommended action */}
      <p className="text-sm text-on-surface">
        {recommendation.action_description || recommendation.action || 'No action description'}
      </p>

      {/* Reasoning */}
      {recommendation.reasoning && (
        <div className="bg-surface-container-low rounded-lg px-4 py-3">
          <p className="text-xs text-on-surface-variant leading-relaxed">{recommendation.reasoning}</p>
        </div>
      )}

      {/* Commands block */}
      {commands.length > 0 && (
        <div className="bg-slate-900 rounded-lg p-4 overflow-x-auto">
          <pre className="font-mono text-[11px] text-slate-300 leading-relaxed whitespace-pre">
            {commands.map((cmd, i) => (
              <span key={i}>
                {isExecuting && <span className="text-primary mr-2">{'>'}</span>}
                {cmd}
                {i < commands.length - 1 ? '\n' : ''}
              </span>
            ))}
          </pre>
        </div>
      )}

      {/* Execution result */}
      {approval.execution_result && (
        <div className={`rounded-lg p-4 ${
          approval.execution_result.success ? 'bg-secondary/5 border border-secondary/20' : 'bg-error/5 border border-error/20'
        }`}>
          <div className="flex items-center gap-2 mb-2">
            <Icon
              name={approval.execution_result.success ? 'check_circle' : 'error'}
              className={`text-lg ${approval.execution_result.success ? 'text-secondary' : 'text-error'}`}
              fill
            />
            <span className={`text-sm font-bold ${approval.execution_result.success ? 'text-secondary' : 'text-error'}`}>
              {approval.execution_result.success ? 'Execution Successful' : 'Execution Failed'}
            </span>
            {approval.execution_result.duration_seconds && (
              <span className="text-xs text-on-surface-variant ml-auto">
                {approval.execution_result.duration_seconds}s
              </span>
            )}
          </div>
          {approval.execution_result.outputs && (
            <div className="bg-slate-900 rounded-lg p-3 overflow-x-auto mt-2">
              <pre className="font-mono text-[10px] text-slate-400 leading-relaxed whitespace-pre">
                {approval.execution_result.outputs.map((o, i) => (
                  <span key={i}>
                    <span className={o.success ? 'text-green-400' : 'text-red-400'}>
                      {o.success ? '✓' : '✗'}
                    </span>
                    {' '}{o.command}
                    {o.output ? `\n  ${o.output.slice(0, 200)}` : ''}
                    {i < approval.execution_result.outputs.length - 1 ? '\n' : ''}
                  </span>
                ))}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Risk + rollback info */}
      <div className="flex items-center gap-3 flex-wrap">
        {recommendation.risk_level && (
          <StatusChip
            variant={
              recommendation.risk_level === 'high'
                ? 'error'
                : recommendation.risk_level === 'medium'
                  ? 'warning'
                  : 'success'
            }
          >
            {recommendation.risk_level.toUpperCase()} RISK
          </StatusChip>
        )}
        {rollbackCommands.length > 0 && (
          <span className="text-xs text-on-surface-variant inline-flex items-center gap-1">
            <Icon name="undo" className="text-[14px]" />
            {rollbackCommands.length} rollback command{rollbackCommands.length !== 1 ? 's' : ''} available
          </span>
        )}
      </div>

      {/* Jira link */}
      {approval.jira_key && (
        <a
          href={approval.jira_url || '#'}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-xs text-primary hover:underline"
        >
          <Icon name="open_in_new" className="text-[14px]" />
          {approval.jira_key}
        </a>
      )}

      {/* Notes toggle */}
      {isPending && showNotes && (
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Optional notes..."
          rows={2}
          className="w-full rounded-lg border border-outline/30 bg-surface-container-low px-3 py-2 text-sm text-on-surface placeholder:text-on-surface-variant/50 focus:outline-none focus:ring-2 focus:ring-primary/40 resize-none"
        />
      )}

      {/* Action buttons — only for pending */}
      {isPending && (
        <div className="flex items-center gap-3 pt-2">
          <button
            onClick={handleDeny}
            disabled={acting}
            className="px-4 py-2 rounded-lg bg-error/10 text-error text-sm font-semibold hover:bg-error/20 transition-colors disabled:opacity-50"
          >
            Deny
          </button>
          <button
            onClick={handleApprove}
            disabled={acting}
            className="px-4 py-2 rounded-lg bg-gradient-to-br from-primary to-primary-container text-white text-sm font-semibold hover:shadow-lg hover:shadow-primary/20 transition-all disabled:opacity-50"
          >
            Approve & Execute
          </button>
          <button
            onClick={() => setShowNotes(!showNotes)}
            className="ml-auto text-xs text-on-surface-variant hover:text-on-surface transition-colors"
          >
            {showNotes ? 'Hide notes' : 'Add notes'}
          </button>
        </div>
      )}

      {/* Executing indicator */}
      {isExecuting && (
        <div className="flex items-center gap-3 pt-2 text-primary">
          <div className="w-4 h-4 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
          <span className="text-sm font-semibold">Executing commands on {device.hostname || 'device'}...</span>
        </div>
      )}
    </div>
  );
}

export default function Approvals() {
  const { data: approvals, loading, error, refetch } = useApi(() => api.approvals());
  usePipelineEvents(useCallback(() => refetch(), [refetch]));
  const [expiring, setExpiring] = useState(false);
  const pollRef = useRef(null);

  // Poll while any approval is in "approved" (executing) state
  const hasExecuting = (approvals || []).some((a) => a.status === 'approved');

  useEffect(() => {
    if (hasExecuting) {
      pollRef.current = setInterval(() => refetch(), 3000);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [hasExecuting, refetch]);

  const all = approvals || [];
  const pending = all.filter((a) => a.status === 'pending');
  const executing = all.filter((a) => a.status === 'approved');

  const handleApprove = async (id, body) => {
    await api.approve(id, body);
    refetch();
  };

  const handleDeny = async (id, body) => {
    await api.deny(id, body);
    refetch();
  };

  const handleExpire = async () => {
    setExpiring(true);
    try {
      await api.expireApprovals();
      refetch();
    } finally {
      setExpiring(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-4">
          <h1 className="text-4xl font-extrabold text-on-surface">Approval Queue</h1>
          <div className="flex items-center gap-2">
            {pending.length > 0 && (
              <>
                <span className="w-2 h-2 rounded-full bg-tertiary animate-pulse" />
                <span className="inline-flex items-center justify-center min-w-[24px] h-6 px-1.5 rounded-full bg-tertiary/10 text-tertiary text-xs font-bold">
                  {pending.length} pending
                </span>
              </>
            )}
            {executing.length > 0 && (
              <>
                <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                <span className="inline-flex items-center justify-center min-w-[24px] h-6 px-1.5 rounded-full bg-primary/10 text-primary text-xs font-bold">
                  {executing.length} executing
                </span>
              </>
            )}
            {pending.length === 0 && executing.length === 0 && !loading && (
              <span className="text-sm font-medium text-on-surface-variant">Queue clear</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleExpire}
            disabled={expiring}
            className="px-4 py-2 rounded-lg border border-outline/30 text-sm font-semibold text-on-surface-variant hover:bg-surface-container-high transition-colors disabled:opacity-50"
          >
            Expire Stale
          </button>
          <a
            href="/executions"
            className="px-4 py-2 rounded-lg border border-outline/30 text-sm font-semibold text-on-surface-variant hover:bg-surface-container-high transition-colors"
          >
            View History
          </a>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="bg-error/10 text-error rounded-xl px-4 py-3 text-sm">
          Failed to load approvals: {error.message}
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="flex items-center justify-center py-20 text-on-surface-variant">
          <Icon name="progress_activity" className="text-3xl animate-spin" />
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && all.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <Icon name="check_circle" className="text-5xl text-secondary" fill />
          <p className="text-lg font-semibold text-on-surface">All clear</p>
          <p className="text-sm text-on-surface-variant">No pending approvals</p>
        </div>
      )}

      {/* Approvals list */}
      {!loading && all.length > 0 && (
        <div className="space-y-4">
          {all.map((approval) => (
            <ApprovalCard
              key={approval.id}
              approval={approval}
              onApprove={handleApprove}
              onDeny={handleDeny}
            />
          ))}
        </div>
      )}
    </div>
  );
}
