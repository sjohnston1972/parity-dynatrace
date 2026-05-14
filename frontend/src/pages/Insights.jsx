import { useState, useCallback, useEffect } from 'react';
import { useApi } from '../hooks/useApi';
import { usePipelineEvents } from '../hooks/usePipelineEvents';
import { api } from '../api/client';
import Icon from '../components/Icon';
import StatusChip from '../components/StatusChip';
import { useDialog } from '../components/Dialog';
import { modelBadgeClass } from '../lib/modelBadge';

const severityColor = (severity) => {
  switch (severity?.toLowerCase()) {
    case 'critical':
    case 'high':
      return 'error';
    case 'medium':
      return 'tertiary';
    case 'low':
    case 'info':
    default:
      return 'secondary';
  }
};

const severityIcon = (severity) => {
  switch (severity?.toLowerCase()) {
    case 'critical':
      return 'crisis_alert';
    case 'high':
      return 'warning';
    case 'medium':
      return 'info';
    case 'low':
      return 'check_circle';
    default:
      return 'auto_awesome';
  }
};

const severityChipVariant = (severity) => {
  switch (severity?.toLowerCase()) {
    case 'critical':
    case 'high':
      return 'error';
    case 'medium':
      return 'neutral';
    case 'low':
    case 'info':
    default:
      return 'success';
  }
};

const severityLabel = (severity) => {
  switch (severity?.toLowerCase()) {
    case 'critical':
      return 'CRITICAL';
    case 'high':
      return 'HIGH';
    case 'medium':
      return 'ADVISORY';
    case 'low':
      return 'LOW';
    case 'info':
      return 'INFO';
    default:
      return severity?.toUpperCase() || 'UNKNOWN';
  }
};

const btnColor = (severity) => {
  const color = severityColor(severity);
  switch (color) {
    case 'error':
      return 'bg-error hover:bg-error/90 text-on-error';
    case 'tertiary':
      return 'bg-tertiary hover:bg-tertiary/90 text-on-tertiary';
    case 'secondary':
    default:
      return 'bg-secondary hover:bg-secondary/90 text-on-secondary';
  }
};

const iconCircleBg = (severity) => {
  const color = severityColor(severity);
  switch (color) {
    case 'error':
      return 'bg-error/10 text-error';
    case 'tertiary':
      return 'bg-tertiary/10 text-tertiary';
    case 'secondary':
    default:
      return 'bg-secondary/10 text-secondary';
  }
};

function formatTimeAgo(dateStr) {
  if (!dateStr) return 'just now';
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function formatTimeShort(dateStr) {
  if (!dateStr) return '--:--';
  const d = new Date(dateStr);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/* ─── Finding Detail Modal ─── */
function FindingDetailModal({ findingId, onClose, onDismiss, onEscalate }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [acting, setActing] = useState(null);
  const dialog = useDialog();

  useEffect(() => {
    if (!findingId) { setDetail(null); return; }
    setLoading(true);
    setError(null);
    api.finding(findingId)
      .then(setDetail)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [findingId]);

  if (!findingId) return null;

  const handleDismiss = async () => {
    setActing('dismiss');
    try {
      await api.dismissFinding(findingId);
      onDismiss(findingId);
      onClose();
    } catch (e) {
      await dialog.alert({ title: 'Dismiss failed', message: e.message, variant: 'danger' });
    } finally {
      setActing(null);
    }
  };

  const handleEscalate = async () => {
    setActing('escalate');
    try {
      await api.escalateFinding(findingId);
      onEscalate(findingId);
      onClose();
    } catch (e) {
      await dialog.alert({ title: 'Escalate failed', message: e.message, variant: 'danger' });
    } finally {
      setActing(null);
    }
  };

  const f = detail || {};
  const device = f.device || {};
  const recs = f.recommendations || [];
  const evidence = f.evidence || {};

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-surface-container-lowest rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-surface-container-lowest z-10 px-6 pt-6 pb-4 border-b border-outline/10">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              {loading ? (
                <div className="h-6 w-48 bg-surface-container-high rounded animate-pulse" />
              ) : (
                <>
                  <div className="flex items-center gap-2 mb-2">
                    <StatusChip variant={severityChipVariant(f.severity)} dot>
                      {severityLabel(f.severity)}
                    </StatusChip>
                    {f.category && (
                      <span className="text-[10px] font-medium text-on-surface-variant bg-surface-container-high px-2 py-0.5 rounded-full uppercase">
                        {f.category}
                      </span>
                    )}
                    {f.agent_model && (
                      <span className="text-[10px] font-mono text-on-surface-variant/60">
                        {f.agent_model}
                      </span>
                    )}
                  </div>
                  <h2 className="text-xl font-bold text-on-surface">{f.title}</h2>
                </>
              )}
            </div>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-full flex items-center justify-center hover:bg-surface-container-high text-on-surface-variant"
            >
              <Icon name="close" className="text-xl" />
            </button>
          </div>
        </div>

        {error && (
          <div className="px-6 py-4 text-sm text-error">Failed to load details: {error.message}</div>
        )}

        {!loading && !error && detail && (
          <div className="px-6 py-5 space-y-5">
            {/* Device info */}
            {device.hostname && (
              <div className="flex items-center gap-4 text-sm">
                <span className="inline-flex items-center gap-1.5 text-on-surface-variant">
                  <Icon name="dns" className="text-[18px]" />
                  {device.hostname}
                </span>
                <span className="inline-flex items-center gap-1.5 text-on-surface-variant">
                  <Icon name="router" className="text-[18px]" />
                  {device.platform} / {device.device_type}
                </span>
                <span className="inline-flex items-center gap-1.5 text-on-surface-variant">
                  <Icon name="language" className="text-[18px]" />
                  {device.management_ip}
                </span>
              </div>
            )}

            {/* Description */}
            <div>
              <h4 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-2">
                Analysis
              </h4>
              <p className="text-sm text-on-surface leading-relaxed">{f.description}</p>
            </div>

            {/* Affected entity */}
            {f.affected_entity && (
              <div>
                <h4 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-2">
                  Affected Entity
                </h4>
                <p className="text-sm font-mono bg-surface-container-low rounded-lg px-3 py-2 text-on-surface">
                  {f.affected_entity}
                </p>
              </div>
            )}

            {/* Evidence */}
            {Object.keys(evidence).length > 0 && (
              <div>
                <h4 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-2">
                  Evidence
                </h4>
                <div className="bg-slate-900 rounded-lg p-4 overflow-x-auto">
                  <pre className="font-mono text-[11px] text-slate-300 leading-relaxed whitespace-pre-wrap">
                    {JSON.stringify(evidence, null, 2)}
                  </pre>
                </div>
              </div>
            )}

            {/* Confidence */}
            <div className="flex items-center gap-6">
              <div>
                <span className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
                  Confidence
                </span>
                <p className="text-lg font-bold text-on-surface">
                  {f.confidence != null ? `${Math.round(f.confidence * 100)}%` : '--'}
                </p>
              </div>
              <div>
                <span className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
                  Remediation
                </span>
                <p className="text-lg font-bold text-on-surface">
                  {f.requires_remediation ? 'Required' : 'Not required'}
                </p>
              </div>
              <div>
                <span className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
                  Detected
                </span>
                <p className="text-sm font-semibold text-on-surface">
                  {formatTimeAgo(f.created_at)}
                </p>
              </div>
            </div>

            {/* Recommendations */}
            {recs.length > 0 && (
              <div>
                <h4 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-3">
                  Recommendations
                </h4>
                <div className="space-y-3">
                  {recs.map((rec) => (
                    <div key={rec.id} className="border border-outline/10 rounded-xl p-4 space-y-3">
                      <p className="text-sm text-on-surface font-medium">{rec.action_description}</p>
                      {rec.reasoning && (
                        <p className="text-xs text-on-surface-variant">{rec.reasoning}</p>
                      )}
                      {rec.commands?.length > 0 && (
                        <div className="bg-slate-900 rounded-lg p-3 overflow-x-auto">
                          <pre className="font-mono text-[11px] text-slate-300 leading-relaxed">
                            {rec.commands.join('\n')}
                          </pre>
                        </div>
                      )}
                      <div className="flex items-center gap-3">
                        <StatusChip
                          variant={
                            rec.risk_level === 'high'
                              ? 'error'
                              : rec.risk_level === 'medium'
                                ? 'warning'
                                : 'success'
                          }
                        >
                          {(rec.risk_level || 'unknown').toUpperCase()} RISK
                        </StatusChip>
                        {rec.approval && (
                          <StatusChip
                            variant={
                              rec.approval.status === 'pending'
                                ? 'warning'
                                : rec.approval.status === 'approved'
                                  ? 'success'
                                  : 'neutral'
                            }
                          >
                            {rec.approval.status.toUpperCase()}
                          </StatusChip>
                        )}
                        {rec.approval?.status === 'pending' && (
                          <a
                            href="/approvals"
                            className="text-xs font-bold text-primary hover:underline"
                          >
                            Go to Approvals &rarr;
                          </a>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Action buttons */}
            <div className="flex items-center gap-3 pt-3 border-t border-outline/10">
              <button
                onClick={handleDismiss}
                disabled={acting !== null}
                className="px-4 py-2 rounded-lg bg-surface-container-high text-on-surface-variant text-sm font-semibold hover:bg-surface-container-highest transition-colors disabled:opacity-50"
              >
                {acting === 'dismiss' ? 'Dismissing...' : 'Dismiss Finding'}
              </button>
              <button
                onClick={handleEscalate}
                disabled={acting !== null}
                className="px-4 py-2 rounded-lg bg-error/10 text-error text-sm font-semibold hover:bg-error/20 transition-colors disabled:opacity-50"
              >
                {acting === 'escalate' ? 'Escalating...' : 'Escalate to Pro'}
              </button>
              {recs.some((r) => r.approval?.status === 'pending') && (
                <a
                  href="/approvals"
                  className="ml-auto px-4 py-2 rounded-lg bg-gradient-to-br from-primary to-primary-container text-white text-sm font-semibold hover:shadow-lg hover:shadow-primary/20 transition-all"
                >
                  Review Approvals
                </a>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Incident Card ─── */
function IncidentCard({ incident, onOpenFinding }) {
  const [expanded, setExpanded] = useState(false);
  const isCorrelated = incident.is_correlated;
  const rec = incident.recommendation;
  const approval = rec?.approval;
  return (
    <div className={`rounded-xl border p-4 ${
      isCorrelated
        ? 'bg-error/5 border-error/20'
        : 'bg-surface-container-lowest border-outline/10'
    }`}>
      <div className="flex items-start gap-3">
        <div className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 ${iconCircleBg(incident.max_severity)}`}>
          <Icon name={isCorrelated ? 'hub' : severityIcon(incident.max_severity)} className="text-lg" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <StatusChip variant={severityChipVariant(incident.max_severity)} dot>
              {severityLabel(incident.max_severity)}
            </StatusChip>
            {/* Always show INCIDENT badge: 1-finding solo incidents say "1 finding · 1 device"
                so the format is consistent and the count is always visible. */}
            <span className={`text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full ${
              isCorrelated
                ? 'bg-error/15 text-error'
                : 'bg-surface-container-high text-on-surface-variant'
            }`}>
              INCIDENT · {incident.finding_count} finding{incident.finding_count !== 1 ? 's' : ''} · {incident.affected_device_count} device{incident.affected_device_count !== 1 ? 's' : ''}
            </span>
            {incident.root_cause.agent_model && (
              <span className="text-[10px] font-mono text-on-surface-variant/60">
                {incident.root_cause.agent_model}
              </span>
            )}
            {approval?.jira_key && (
              <a href={approval.jira_url} target="_blank" rel="noreferrer"
                className="text-[10px] font-bold text-primary hover:underline">
                {approval.jira_key}
              </a>
            )}
          </div>
          <h3 className="text-base font-bold text-on-surface">
            {incident.root_cause.title}
          </h3>
          <p className="text-xs text-on-surface-variant mt-1">
            <Icon name="dns" className="text-sm align-middle" />{' '}
            <span className="font-mono">{incident.affected_devices.join(', ')}</span>
          </p>
          {/* AI reasoning — surfaced from the reasoner's recommendation. */}
          {rec?.reasoning && (
            <div className="mt-3 bg-surface-container-low rounded-lg px-3 py-2.5 border border-outline/10">
              <div className="flex items-center gap-1.5 mb-1">
                <Icon name="psychology" className="text-sm text-primary" />
                <span className="text-[10px] font-bold uppercase tracking-wide text-primary">AI Analysis</span>
                {rec.risk_level && (
                  <span className={`text-[10px] font-bold uppercase px-1.5 rounded-full ${
                    rec.risk_level === 'high' ? 'bg-error/15 text-error' :
                    rec.risk_level === 'medium' ? 'bg-tertiary/15 text-tertiary' :
                    'bg-secondary/15 text-secondary'
                  }`}>
                    {rec.risk_level} risk
                  </span>
                )}
                {approval?.status && (
                  <span className="text-[10px] font-bold uppercase px-1.5 rounded-full bg-surface-container-high text-on-surface-variant ml-auto">
                    {approval.status}
                  </span>
                )}
              </div>
              <p className="text-xs text-on-surface leading-relaxed line-clamp-3">{rec.reasoning}</p>
              {rec.action && (
                <p className="text-xs text-on-surface mt-1.5 font-medium">
                  <Icon name="bolt" className="text-sm align-middle text-primary" /> {rec.action}
                </p>
              )}
            </div>
          )}
        </div>
        <button
          onClick={() => onOpenFinding(incident.root_cause.id)}
          className={`shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-colors ${btnColor(incident.max_severity)}`}
        >
          <Icon name="open_in_new" className="text-sm" />
          Investigate
        </button>
      </div>
      {isCorrelated && incident.linked_findings.length > 0 && (
        <div className="mt-3 pl-12">
          <button
            onClick={() => setExpanded((e) => !e)}
            className="flex items-center gap-1 text-[11px] font-bold text-on-surface-variant hover:text-on-surface transition-colors"
          >
            <Icon name={expanded ? 'expand_less' : 'expand_more'} className="text-base" />
            {expanded ? 'Hide' : 'Show'} {incident.linked_findings.length} linked finding{incident.linked_findings.length === 1 ? '' : 's'}
          </button>
          {expanded && (
            <div className="mt-2 space-y-1.5">
              {incident.linked_findings.map((lf) => (
                <button
                  key={lf.id}
                  onClick={() => onOpenFinding(lf.id)}
                  className="w-full text-left flex items-center gap-2 px-3 py-2 bg-surface-container-low rounded-lg hover:bg-surface-container-high transition-colors"
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${
                    severityColor(lf.severity) === 'error' ? 'bg-error' :
                    severityColor(lf.severity) === 'tertiary' ? 'bg-tertiary' : 'bg-secondary'
                  }`} />
                  <span className="text-[11px] font-mono text-on-surface-variant">{lf.device_hostname}</span>
                  <span className="text-xs text-on-surface flex-1 truncate">{lf.title}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}


/* ─── Main Page ─── */
export default function Insights() {
  const { data: findings, loading, error, refetch } = useApi(() => api.findings(), []);
  const { data: incidents, refetch: refetchIncidents } = useApi(() => api.incidents(), []);
  usePipelineEvents(useCallback(() => { refetch(); refetchIncidents(); }, [refetch, refetchIncidents]));
  const [viewMode, setViewMode] = useState('incidents'); // 'incidents' | 'findings'
  const [openMenu, setOpenMenu] = useState(null);
  const [selectedFinding, setSelectedFinding] = useState(null);
  const [acting, setActing] = useState({}); // { [findingId]: 'dismiss'|'escalate' }
  const [severityFilter, setSeverityFilter] = useState(null); // null = all
  const [selectedIds, setSelectedIds] = useState(new Set()); // multi-select for bulk dismiss
  const [bulkDismissing, setBulkDismissing] = useState(false);
  const dialog = useDialog();

  const items = findings || [];
  const filteredItems = severityFilter
    ? items.filter((f) => {
        const s = f.severity?.toLowerCase();
        if (severityFilter === 'high') return s === 'critical' || s === 'high';
        return s === severityFilter;
      })
    : items;
  const remediationItems = items.filter((f) => f.requires_remediation);
  const criticalCount = items.filter(
    (f) => f.severity?.toLowerCase() === 'critical' || f.severity?.toLowerCase() === 'high',
  ).length;
  const nodesAnalyzed = new Set(items.map((f) => f.device_id)).size;
  const riskScore = items.length === 0
    ? 0
    : Math.min(
        100,
        Math.round(
          items.reduce((acc, f) => {
            const s = f.severity?.toLowerCase();
            if (s === 'critical') return acc + 25;
            if (s === 'high') return acc + 15;
            if (s === 'medium') return acc + 5;
            return acc + 1;
          }, 0),
        ),
      );
  const efficiency = items.length === 0 ? 99.8 : Math.max(85, 99.8 - criticalCount * 2.1).toFixed(1);
  const automationConfidence = items.length === 0 ? 94 : Math.max(60, 94 - criticalCount * 5);

  const handleRescan = () => {
    api.pipelineRun({}).then(() => refetch());
  };

  const openDetail = (findingId) => {
    setOpenMenu(null);
    setSelectedFinding(findingId);
  };

  const handleDismiss = useCallback(async (findingId) => {
    setActing((prev) => ({ ...prev, [findingId]: 'dismiss' }));
    setOpenMenu(null);
    try {
      await api.dismissFinding(findingId);
      refetch();
    } catch (e) {
      await dialog.alert({ title: 'Dismiss failed', message: e.message, variant: 'danger' });
    } finally {
      setActing((prev) => {
        const next = { ...prev };
        delete next[findingId];
        return next;
      });
    }
  }, [refetch, dialog]);

  const handleEscalate = useCallback(async (findingId) => {
    setActing((prev) => ({ ...prev, [findingId]: 'escalate' }));
    setOpenMenu(null);
    try {
      await api.escalateFinding(findingId);
      // New findings will appear after pipeline completes — show feedback
      setTimeout(() => refetch(), 3000);
    } catch (e) {
      await dialog.alert({ title: 'Escalate failed', message: e.message, variant: 'danger' });
    } finally {
      setActing((prev) => {
        const next = { ...prev };
        delete next[findingId];
        return next;
      });
    }
  }, [refetch, dialog]);

  const handleApply = useCallback((findingId) => {
    // Open detail modal which shows recommendation + approval link
    setSelectedFinding(findingId);
  }, []);

  const toggleSelect = useCallback((findingId) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(findingId)) next.delete(findingId);
      else next.add(findingId);
      return next;
    });
  }, []);

  const handleDismissSelected = useCallback(async () => {
    if (selectedIds.size === 0) return;
    setBulkDismissing(true);
    try {
      await Promise.all([...selectedIds].map((id) => api.dismissFinding(id)));
      setSelectedIds(new Set());
      refetch();
    } catch (e) {
      await dialog.alert({ title: 'Bulk dismiss failed', message: e.message, variant: 'danger' });
    } finally {
      setBulkDismissing(false);
    }
  }, [selectedIds, refetch, dialog]);

  const handleDismissAll = useCallback(async () => {
    const ids = filteredItems.map((f) => f.id);
    if (ids.length === 0) return;
    setBulkDismissing(true);
    try {
      await Promise.all(ids.map((id) => api.dismissFinding(id)));
      setSelectedIds(new Set());
      refetch();
    } catch (e) {
      await dialog.alert({ title: 'Dismiss all failed', message: e.message, variant: 'danger' });
    } finally {
      setBulkDismissing(false);
    }
  }, [filteredItems, refetch, dialog]);

  return (
    <div className="min-h-screen bg-surface p-6 lg:p-10">
      {/* Detail Modal */}
      <FindingDetailModal
        findingId={selectedFinding}
        onClose={() => setSelectedFinding(null)}
        onDismiss={() => refetch()}
        onEscalate={() => setTimeout(() => refetch(), 3000)}
      />

      {/* Page Header */}
      <header className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between mb-8">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="w-2.5 h-2.5 rounded-full bg-secondary animate-pulse" />
            <span className="text-sm font-semibold text-secondary">System Status: Optimal</span>
          </div>
          <h1 className="text-4xl font-extrabold tracking-tight text-on-surface">AI Insights Panel</h1>
          <p className="mt-1 text-on-surface-variant text-sm max-w-xl">
            Advanced neural analysis of your global infrastructure — real-time threat detection, anomaly
            classification, and autonomous remediation proposals.
          </p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <a
            href="/executions"
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg border border-outline/30 text-sm font-semibold text-on-surface-variant hover:bg-surface-container-high transition-colors"
          >
            <Icon name="history" className="text-lg" />
            Audit Log
          </a>
          <button
            onClick={handleRescan}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-gradient-to-br from-primary to-primary-container text-on-primary text-sm font-semibold shadow-lg shadow-primary/20 hover:shadow-primary/30 transition-all"
          >
            <Icon name="radar" className="text-lg" />
            Re-scan Network
          </button>
        </div>
      </header>

      {/* Loading / Error */}
      {loading && (
        <div className="flex items-center justify-center py-24">
          <div className="w-8 h-8 border-3 border-primary/20 border-t-primary rounded-full animate-spin" />
        </div>
      )}
      {error && (
        <div className="rounded-xl bg-error/5 border border-error/20 p-4 mb-6 flex items-center gap-3">
          <Icon name="error" className="text-error" />
          <span className="text-sm text-error font-medium">Failed to load findings: {error.message}</span>
          <button onClick={refetch} className="ml-auto text-sm font-semibold text-error underline">
            Retry
          </button>
        </div>
      )}

      {!loading && !error && (
        <div className="grid grid-cols-12 gap-6">
          {/* ===== LEFT COLUMN (col-span-8) ===== */}
          <div className="col-span-12 lg:col-span-8 flex flex-col gap-6">
            {/* Executive Summary */}
            <div className="bg-surface-container-lowest rounded-xl shadow-sm border border-outline/10 p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-full bg-secondary/10 flex items-center justify-center">
                  <Icon name="auto_awesome" className="text-secondary text-xl" fill />
                </div>
                <h2 className="text-lg font-bold text-on-surface">Executive Summary</h2>
              </div>
              <p className="text-sm text-on-surface-variant leading-relaxed mb-5">
                Network infrastructure is operating at{' '}
                <span className="font-bold text-secondary">{efficiency}% efficiency</span>. Analysis has identified{' '}
                <span className={`font-bold ${criticalCount > 0 ? 'text-error' : 'text-secondary'}`}>
                  {items.length} issue{items.length !== 1 ? 's' : ''}
                </span>{' '}
                across monitored nodes
                {criticalCount > 0 && (
                  <>
                    , including{' '}
                    <span className="font-bold text-error">
                      {criticalCount} critical/high severity finding{criticalCount !== 1 ? 's' : ''}
                    </span>
                  </>
                )}
                . {remediationItems.length} remediation{remediationItems.length !== 1 ? 's' : ''}{' '}
                {remediationItems.length === 1 ? 'is' : 'are'} queued for review.
              </p>
              <div className="grid grid-cols-3 gap-4">
                <div className="border-l-4 border-error rounded-lg bg-error/5 p-4">
                  <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-1">
                    Risk Score
                  </p>
                  <p className="text-2xl font-extrabold text-error">{riskScore}</p>
                  <p className="text-xs text-on-surface-variant">/ 100</p>
                </div>
                <div className="border-l-4 border-primary rounded-lg bg-primary/5 p-4">
                  <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-1">
                    Nodes Analyzed
                  </p>
                  <p className="text-2xl font-extrabold text-primary">{nodesAnalyzed}</p>
                  <p className="text-xs text-on-surface-variant">devices</p>
                </div>
                <div className="border-l-4 border-secondary rounded-lg bg-secondary/5 p-4">
                  <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-1">
                    Remediations Ready
                  </p>
                  <p className="text-2xl font-extrabold text-secondary">{remediationItems.length}</p>
                  <p className="text-xs text-on-surface-variant">pending approval</p>
                </div>
              </div>
            </div>

            {/* Incidents view (default) */}
            {viewMode === 'incidents' && (
              <div>
                <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
                  <h2 className="text-lg font-bold text-on-surface">Active Incidents</h2>
                  <div className="flex bg-surface-container-low rounded-lg p-0.5">
                    <button
                      onClick={() => setViewMode('incidents')}
                      className="px-3 py-1 rounded-md text-[11px] font-bold bg-white shadow-sm text-on-surface"
                    >
                      Incidents
                    </button>
                    <button
                      onClick={() => setViewMode('findings')}
                      className="px-3 py-1 rounded-md text-[11px] font-bold text-on-surface-variant hover:text-on-surface"
                    >
                      All findings
                    </button>
                  </div>
                </div>
                {!incidents || incidents.length === 0 ? (
                  <div className="bg-surface-container-lowest rounded-xl border border-outline/10 p-10 text-center">
                    <Icon name="verified" className="text-4xl text-secondary mb-2" />
                    <p className="text-sm text-on-surface-variant">No active incidents. Network looks clean.</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {incidents.map((inc) => (
                      <IncidentCard key={inc.root_cause.id} incident={inc} onOpenFinding={openDetail} />
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Risk Detection Grid (findings view) */}
            {viewMode === 'findings' && (
            <div>
              <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
                <div className="flex items-center gap-3">
                  <h2 className="text-lg font-bold text-on-surface">All Findings</h2>
                  <div className="flex bg-surface-container-low rounded-lg p-0.5">
                    <button
                      onClick={() => setViewMode('incidents')}
                      className="px-3 py-1 rounded-md text-[11px] font-bold text-on-surface-variant hover:text-on-surface"
                    >
                      Incidents
                    </button>
                    <button
                      onClick={() => setViewMode('findings')}
                      className="px-3 py-1 rounded-md text-[11px] font-bold bg-white shadow-sm text-on-surface"
                    >
                      All findings
                    </button>
                  </div>
                  {selectedIds.size > 0 && (
                    <span className="text-xs font-bold text-primary bg-primary/10 px-2 py-0.5 rounded-full">
                      {selectedIds.size} selected
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {/* Severity filters */}
                  {[
                    { key: null, label: 'All' },
                    { key: 'high', label: 'High', variant: 'bg-error/10 text-error border-error/30' },
                    { key: 'medium', label: 'Medium', variant: 'bg-tertiary/10 text-tertiary border-tertiary/30' },
                    { key: 'low', label: 'Low', variant: 'bg-secondary/10 text-secondary border-secondary/30' },
                  ].map((pill) => (
                    <button
                      key={pill.label}
                      onClick={() => setSeverityFilter(pill.key)}
                      className={`px-3 py-1 rounded-full text-xs font-bold border transition-colors ${
                        severityFilter === pill.key
                          ? pill.variant || 'bg-primary/10 text-primary border-primary/30'
                          : 'bg-surface-container-low text-on-surface-variant border-outline/20 hover:bg-surface-container-high'
                      }`}
                    >
                      {pill.label}
                    </button>
                  ))}
                  {/* Dismiss buttons */}
                  <span className="w-px h-5 bg-outline/20" />
                  {selectedIds.size > 0 && (
                    <button
                      onClick={handleDismissSelected}
                      disabled={bulkDismissing}
                      className="px-3 py-1 rounded-full text-xs font-bold border border-error/30 bg-error/10 text-error hover:bg-error/20 transition-colors disabled:opacity-50"
                    >
                      {bulkDismissing ? 'Dismissing...' : `Dismiss Selected (${selectedIds.size})`}
                    </button>
                  )}
                  <button
                    onClick={handleDismissAll}
                    disabled={bulkDismissing || filteredItems.length === 0}
                    className="px-3 py-1 rounded-full text-xs font-bold border border-outline/20 bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high transition-colors disabled:opacity-50"
                  >
                    Dismiss All
                  </button>
                </div>
              </div>
              {filteredItems.length === 0 ? (
                <div className="bg-surface-container-lowest rounded-xl border border-outline/10 p-10 text-center">
                  <Icon name="verified" className="text-4xl text-secondary mb-2" />
                  <p className="text-sm text-on-surface-variant">No findings detected. Infrastructure looks clean.</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {filteredItems.map((finding) => {
                    const isActing = acting[finding.id];
                    const isSelected = selectedIds.has(finding.id);
                    return (
                      <div
                        key={finding.id}
                        onClick={() => toggleSelect(finding.id)}
                        className={`rounded-xl border p-5 hover:shadow-md transition-all relative group cursor-pointer ${
                          isSelected
                            ? 'bg-primary/5 border-primary/30 ring-1 ring-primary/20'
                            : 'bg-surface-container-lowest border-outline/10'
                        } ${isActing ? 'opacity-60' : ''}`}
                      >
                        {/* Selection indicator */}
                        {isSelected && (
                          <div className="absolute top-3 right-3 w-5 h-5 rounded-full bg-primary flex items-center justify-center">
                            <Icon name="check" className="text-[14px] text-white" />
                          </div>
                        )}
                        <div className="flex items-start gap-3 mb-3">
                          <div
                            className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 ${iconCircleBg(finding.severity)}`}
                          >
                            <Icon name={severityIcon(finding.severity)} className="text-lg" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <StatusChip variant={severityChipVariant(finding.severity)} dot>
                                {severityLabel(finding.severity)}
                              </StatusChip>
                              {finding.category && (
                                <span className="text-[10px] font-medium text-on-surface-variant bg-surface-container-high px-2 py-0.5 rounded-full uppercase">
                                  {finding.category}
                                </span>
                              )}
                              {finding.agent_model && (
                                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wide ${modelBadgeClass(finding.agent_model)}`}>
                                  {finding.agent_model}
                                </span>
                              )}
                            </div>
                            <h3 className="text-lg font-bold text-on-surface truncate">{finding.title}</h3>
                          </div>
                        </div>
                        <p className="text-sm text-on-surface-variant leading-relaxed mb-4 line-clamp-2">
                          {finding.description}
                        </p>
                        <div className="flex items-center justify-between">
                          <button
                            onClick={(e) => { e.stopPropagation(); openDetail(finding.id); }}
                            className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold transition-colors ${btnColor(finding.severity)}`}
                          >
                            <Icon name="open_in_new" className="text-sm" />
                            Investigate
                          </button>
                          <div className="relative">
                            <button
                              onClick={(e) => { e.stopPropagation(); setOpenMenu(openMenu === finding.id ? null : finding.id); }}
                              className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-surface-container-high text-on-surface-variant transition-colors"
                            >
                              <Icon name="more_vert" className="text-lg" />
                            </button>
                            {openMenu === finding.id && (
                              <div onClick={(e) => e.stopPropagation()} className="absolute right-0 top-full mt-1 w-44 bg-surface-container-lowest rounded-lg shadow-lg border border-outline/10 py-1 z-10">
                                <button
                                  onClick={() => openDetail(finding.id)}
                                  className="w-full text-left px-3 py-2 text-sm text-on-surface hover:bg-surface-container-high transition-colors flex items-center gap-2"
                                >
                                  <Icon name="visibility" className="text-[16px]" />
                                  View Details
                                </button>
                                <button
                                  onClick={() => handleDismiss(finding.id)}
                                  className="w-full text-left px-3 py-2 text-sm text-on-surface hover:bg-surface-container-high transition-colors flex items-center gap-2"
                                >
                                  <Icon name="do_not_disturb_on" className="text-[16px]" />
                                  Dismiss
                                </button>
                                <button
                                  onClick={() => handleEscalate(finding.id)}
                                  className="w-full text-left px-3 py-2 text-sm text-error hover:bg-error/5 transition-colors flex items-center gap-2"
                                >
                                  <Icon name="priority_high" className="text-[16px]" />
                                  Escalate to Pro
                                </button>
                              </div>
                            )}
                          </div>
                        </div>
                        {finding.affected_entity && (
                          <p className="mt-3 text-[11px] text-on-surface-variant font-mono bg-surface-container-low rounded px-2 py-1 truncate">
                            {finding.affected_entity}
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
            )}
          </div>

          {/* ===== RIGHT SIDEBAR (col-span-4) ===== */}
          <div className="col-span-12 lg:col-span-4 flex flex-col gap-6">
            {/* Suggested Actions */}
            <div className="bg-surface-container-lowest rounded-xl shadow-sm border border-outline/10 p-5">
              <div className="flex items-center gap-2 mb-4">
                <Icon name="bolt" className="text-primary text-xl" fill />
                <h2 className="text-base font-bold text-on-surface">Suggested Actions</h2>
              </div>
              {remediationItems.length === 0 ? (
                <p className="text-sm text-on-surface-variant py-4 text-center">
                  No remediation actions pending.
                </p>
              ) : (
                <ul className="space-y-3">
                  {remediationItems.map((item) => (
                    <li
                      key={item.id}
                      className="flex items-start gap-3 p-3 rounded-lg hover:bg-surface-container-low transition-colors"
                    >
                      <div className="w-8 h-8 rounded-full bg-surface-container-lowest border border-outline/20 flex items-center justify-center shrink-0">
                        <Icon
                          name={severityIcon(item.severity)}
                          className={`text-sm ${
                            severityColor(item.severity) === 'error'
                              ? 'text-error'
                              : severityColor(item.severity) === 'tertiary'
                                ? 'text-tertiary'
                                : 'text-secondary'
                          }`}
                        />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-on-surface truncate">{item.title}</p>
                        <p className="text-xs text-on-surface-variant line-clamp-2 mt-0.5">{item.description}</p>
                        <button
                          onClick={() => handleApply(item.id)}
                          className="mt-1.5 text-xs font-bold text-primary hover:text-primary-container transition-colors"
                        >
                          Apply &rarr;
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}

              {/* Automation Confidence */}
              <div className="mt-5 pt-4 border-t border-outline/10">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide">
                    Automation Confidence
                  </span>
                  <span className="text-xs font-bold text-secondary">{automationConfidence}%</span>
                </div>
                <div className="w-full h-2 bg-surface-container-high rounded-full overflow-hidden">
                  <div
                    className="h-full bg-secondary rounded-full transition-all duration-700 ease-out"
                    style={{ width: `${automationConfidence}%` }}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* ===== ANOMALIES TIMELINE (full width) ===== */}
          <div className="col-span-12 mt-2">
            <div className="flex items-center gap-3 mb-4">
              <h2 className="text-lg font-bold text-on-surface whitespace-nowrap">Anomalies Timeline</h2>
              <hr className="flex-1 border-outline/20" />
            </div>

            {items.length === 0 ? (
              <p className="text-sm text-on-surface-variant text-center py-6">No anomalies to display.</p>
            ) : (
              <div className="space-y-3">
                {items.slice(0, 10).map((finding) => {
                  const color = severityColor(finding.severity);
                  const dotClass =
                    color === 'error'
                      ? 'bg-error'
                      : color === 'tertiary'
                        ? 'bg-tertiary'
                        : 'bg-secondary';
                  return (
                    <div
                      key={`tl-${finding.id}`}
                      className="grid grid-cols-12 gap-3 items-start cursor-pointer"
                      onClick={() => openDetail(finding.id)}
                    >
                      {/* Time */}
                      <div className="col-span-2 text-right">
                        <span className="text-xs font-mono text-on-surface-variant">
                          {formatTimeShort(finding.created_at)}
                        </span>
                        <span className="block text-[10px] text-outline">
                          {formatTimeAgo(finding.created_at)}
                        </span>
                      </div>
                      {/* Dot */}
                      <div className="col-span-1 flex justify-center pt-1.5">
                        <span className={`w-3 h-3 rounded-full ${dotClass} ring-4 ring-surface`} />
                      </div>
                      {/* Event Card */}
                      <div className="col-span-9 bg-surface-container-low rounded-lg p-4 hover:bg-surface-container-high transition-colors group">
                        <div className="flex items-center gap-2 mb-1">
                          <StatusChip variant={severityChipVariant(finding.severity)} dot>
                            {severityLabel(finding.severity)}
                          </StatusChip>
                          {finding.affected_entity && (
                            <span className="text-[10px] font-mono text-on-surface-variant">
                              {finding.affected_entity}
                            </span>
                          )}
                          {finding.agent_model && (
                            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full uppercase tracking-wide ${modelBadgeClass(finding.agent_model, 'light')}`}>
                              {finding.agent_model}
                            </span>
                          )}
                        </div>
                        <h4 className="text-sm font-semibold text-on-surface group-hover:text-primary transition-colors">
                          {finding.title}
                        </h4>
                        <p className="text-xs text-on-surface-variant mt-0.5 line-clamp-1">
                          {finding.description}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
