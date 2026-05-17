import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import Icon from './Icon';
import { api } from '../api/client';
import dynatraceCube from '../assets/dynatrace-logo-cube.png';

/**
 * Compact Dynatrace pill that fits inline next to a finding/insight/execution.
 * Clicking opens a styled modal showing exactly what Dynatrace did for that
 * particular item — the Davis Copilot assessment (if any), Davis events
 * Parity fired for the finding lifecycle, and deep links into the tenant.
 */
export default function DynatracePill({ finding, executionContext, className = '' }) {
  const [open, setOpen] = useState(false);
  if (!finding) return null;
  return (
    <>
      <button
        type="button"
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(true); }}
        title="See what Dynatrace did for this item"
        /* Same h-5 + leading-none + w-3 h-3 glyph-box pattern as
           components/AiSourceChips.jsx so the interactive pill is
           visually indistinguishable from the static DavisChip. */
        className={`inline-flex items-center gap-1 text-[10px] font-bold px-2 h-5 leading-none rounded-md text-white transition-all hover:brightness-110 active:scale-95 ${className}`}
        style={{
          background: 'linear-gradient(135deg, #1496FF 0%, #0066B7 100%)',
          boxShadow: '0 1px 4px rgba(0,102,183,0.22)',
        }}
      >
        <span className="inline-flex items-center justify-center w-3 h-3 shrink-0">
          <img src={dynatraceCube} alt="" className="w-3 h-3 object-contain" />
        </span>
        Davis
      </button>
      {open && (
        <DynatraceDetailsModal
          finding={finding}
          executionContext={executionContext}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

function DynatraceDetailsModal({ finding, executionContext, onClose }) {
  const [events, setEvents] = useState(null);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [eventsResp, statusResp] = await Promise.all([
          api.dtEvents('-24h', 200),
          api.dtStatus(),
        ]);
        if (cancelled) return;
        const mine = (eventsResp.records || []).filter(
          (r) => r.finding_id === finding.id
        );
        setEvents(mine);
        setStatus(statusResp);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [finding.id]);

  // Close on ESC
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const evidence = finding.evidence || {};
  const davisAssessment = evidence.davis_assessment;
  const created = (events || []).find((e) => e.action === 'created');
  const resolved = (events || []).find((e) => e.action === 'resolved');

  const deepLink = status?.dashboard_url
    ? `${status.dashboard_url}?finding=${encodeURIComponent(finding.id)}`
    : status?.apps_url;

  return createPortal(
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center p-6"
      onClick={onClose}
      style={{ backgroundColor: 'rgba(10,37,64,0.55)', backdropFilter: 'blur(4px)' }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="bg-white rounded-2xl shadow-2xl max-w-3xl w-full overflow-hidden flex flex-col"
        style={{ maxHeight: '85vh' }}
      >
        {/* Header */}
        <div
          className="px-7 py-5 relative overflow-hidden"
          style={{
            background: 'linear-gradient(135deg, #1496FF 0%, #0066B7 100%)',
            color: 'white',
          }}
        >
          <div
            aria-hidden
            className="absolute -right-10 -top-10 w-48 h-48 opacity-15 pointer-events-none"
            style={{
              background:
                'radial-gradient(circle at 35% 35%, rgba(255,255,255,0.95) 0%, rgba(255,255,255,0) 60%)',
            }}
          />
          <div className="flex items-start gap-4">
            <div className="w-16 h-16 rounded-lg bg-white/10 flex items-center justify-center backdrop-blur-sm shrink-0 p-2">
              <img src={dynatraceCube} alt="Dynatrace" className="w-full h-full object-contain" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-[0.22em] text-white/70 mb-0.5">
                Dynatrace activity · this finding
              </p>
              <h2 className="text-lg font-bold leading-tight truncate">
                {finding.title || 'Finding'}
              </h2>
              <p className="text-[11px] font-mono text-white/70 mt-1 truncate">
                {finding.id} · {finding.severity} · {finding.category}
              </p>
            </div>
            <button
              onClick={onClose}
              className="text-white/80 hover:text-white text-2xl leading-none transition-colors"
              aria-label="Close"
            >
              ×
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="px-7 py-6 overflow-y-auto" style={{ minHeight: 200 }}>
          {error && (
            <p className="text-sm text-error">Failed to load Davis activity: {error}</p>
          )}

          {events === null && !error && (
            <div className="flex items-center gap-3 text-on-surface-variant">
              <div className="w-4 h-4 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
              <span className="text-sm">Querying Grail via DQL…</span>
            </div>
          )}

          {events && (
            <div className="space-y-6">
              {/* Lifecycle bar */}
              <section>
                <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-2">
                  Davis lifecycle
                </p>
                {created || resolved ? (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <LifecycleCard
                      label="Finding raised"
                      ts={created?.timestamp}
                      eventId={created?.event_id}
                      action="created"
                    />
                    <LifecycleCard
                      label="Finding resolved"
                      ts={resolved?.timestamp}
                      eventId={resolved?.event_id}
                      action="resolved"
                    />
                  </div>
                ) : (
                  <p className="text-sm text-on-surface-variant">
                    No Davis events recorded for this finding yet. They normally appear within ~20 s of a finding being raised.
                  </p>
                )}
              </section>

              {/* Davis Copilot second opinion */}
              <section>
                <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-2">
                  Davis Copilot · second opinion on Gemini's verdict
                </p>
                {davisAssessment ? (
                  <blockquote
                    className="border-l-4 px-4 py-3 italic text-sm text-on-surface bg-surface-container-low/50 rounded-r"
                    style={{ borderLeftColor: '#0066B7' }}
                  >
                    {davisAssessment}
                  </blockquote>
                ) : (
                  <p className="text-sm text-on-surface-variant">
                    Davis Copilot did not return a usable assessment for this finding. This typically happens when the Dynatrace tenant has no monitored entities for the affected network device, leaving Davis without grounding data to reason from. Gemini's verdict above stands as the primary signal.
                  </p>
                )}
              </section>

              {/* Quick context: properties Parity emitted to Davis */}
              <section>
                <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-2">
                  Event properties emitted to Davis
                </p>
                <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs font-mono">
                  <PropertyRow k="parity.finding.id" v={finding.id} />
                  <PropertyRow k="parity.severity" v={finding.severity} />
                  <PropertyRow k="parity.category" v={finding.category} />
                  <PropertyRow k="parity.device" v={finding.affected_entity} />
                  <PropertyRow k="parity.confidence" v={String(finding.confidence ?? '')} />
                  <PropertyRow k="parity.incident.id" v={finding.incident_id || '-'} />
                  {evidence.correlation_key && (
                    <PropertyRow k="parity.correlation_key" v={evidence.correlation_key} />
                  )}
                  {executionContext?.phase && (
                    <PropertyRow k="parity.resolved.phase" v={executionContext.phase} />
                  )}
                </div>
              </section>

              {/* DQL link */}
              <section>
                <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-2">
                  DQL — re-run on the Notebooks app
                </p>
                <pre className="text-xs font-mono p-3 rounded bg-surface-container-low/70 text-on-surface overflow-x-auto">
{`fetch events, from:-24h
| filter source == "parity"
| filter parity.finding.id == "${finding.id}"
| sort timestamp desc`}
                </pre>
              </section>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-7 py-4 border-t border-outline/20 flex items-center justify-between bg-surface-container-low/30">
          <span className="text-[11px] text-on-surface-variant font-mono">
            Tenant: {status?.tenant || '—'}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="text-xs font-bold uppercase tracking-wider px-4 py-2 rounded-md text-on-surface-variant hover:bg-surface-container-high transition-colors"
            >
              Close
            </button>
            {deepLink && (
              <a
                href={deepLink}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs font-bold uppercase tracking-wider px-4 py-2 rounded-md text-white transition-all hover:brightness-110"
                style={{ background: 'linear-gradient(135deg, #1496FF 0%, #0066B7 100%)' }}
              >
                Open in Dynatrace
                <Icon name="open_in_new" className="text-[14px]" />
              </a>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}

function LifecycleCard({ label, ts, eventId, action }) {
  const present = !!ts;
  const colors = action === 'created'
    ? { dot: 'bg-error', text: 'text-error' }
    : { dot: 'bg-secondary', text: 'text-secondary' };
  return (
    <div className={`p-3 rounded-lg border ${present ? 'border-outline/30 bg-surface-container-low/40' : 'border-outline/15 bg-surface-container-low/15 opacity-60'}`}>
      <div className="flex items-center gap-2 mb-1">
        <span className={`w-2 h-2 rounded-full ${present ? colors.dot : 'bg-outline'}`} />
        <span className={`text-[10px] font-bold uppercase tracking-wider ${present ? colors.text : 'text-on-surface-variant'}`}>
          {label}
        </span>
      </div>
      <p className="text-xs font-mono text-on-surface">
        {present ? ts : 'not recorded'}
      </p>
      {present && (
        <p className="text-[10px] text-on-surface-variant font-mono mt-1">
          event {eventId?.slice(-12)}
        </p>
      )}
    </div>
  );
}

function PropertyRow({ k, v }) {
  return (
    <>
      <span className="text-on-surface-variant">{k}</span>
      <span className="text-on-surface truncate">{v}</span>
    </>
  );
}
