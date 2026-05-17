import { useState, useEffect, useRef, useCallback } from 'react';
import Icon from '../components/Icon';

// ──────────────────────────────────────────────────────────
//  Model tier palette
// ──────────────────────────────────────────────────────────
const MODEL_CONFIG = {
  pyats:        { label: 'Python',       tier: 'Engine',  color: 'cyan',    icon: 'terminal',     desc: 'Deterministic device capture + execution' },
  deterministic:{ label: 'Diff',         tier: 'Engine',  color: 'slate',   icon: 'difference',   desc: 'Python diff over snapshot JSON' },
  davis:        { label: 'Davis',        tier: 'Reason',  color: 'amber',   icon: 'auto_awesome', desc: 'Dynatrace Davis AI Copilot' },
  'flash-lite': { label: 'Flash-Lite',   tier: 'Tier 0',  color: 'amber',   icon: 'memory',       desc: 'Gemini 2.5 Flash-Lite' },
  flash:        { label: 'Flash',        tier: 'Tier 1',  color: 'emerald', icon: 'bolt',         desc: 'Gemini 2.5 Flash' },
  pro:          { label: 'Pro',          tier: 'Tier 2',  color: 'purple',  icon: 'neurology',    desc: 'Gemini 2.5 Pro' },
  human:        { label: 'Human',        tier: 'HITL',    color: 'blue',    icon: 'verified_user', desc: 'Operator approval gate' },
};

// activity_bus event.node → human label
const NODE_LABELS = {
  snapshot:        'Device Snapshot',
  diff:            'Diff',
  'davis-reasoning':'Davis Reasoning',
  remediation:     'Remediation Draft',
  approval:        'Approval',
  execution:       'Command Execution',
  verification:    'Verification Snapshot',
};

function resolveModelKey(model) {
  if (!model) return null;
  const m = model.toLowerCase();
  if (m.includes('davis')) return 'davis';
  if (m.includes('flash-lite')) return 'flash-lite';
  if (m.includes('pro')) return 'pro';
  if (m.includes('flash')) return 'flash';
  if (m.includes('pyats') || m === 'pyats') return 'pyats';
  return null;
}

const COLOR_MAP = {
  amber:   { bg: 'bg-amber-500/15', text: 'text-amber-400', ring: 'ring-amber-500/30', fill: 'bg-amber-400', glow: 'shadow-amber-500/30', border: 'border-amber-500/40' },
  cyan:    { bg: 'bg-cyan-500/15', text: 'text-cyan-400', ring: 'ring-cyan-500/30', fill: 'bg-cyan-400', glow: 'shadow-cyan-500/30', border: 'border-cyan-500/40' },
  emerald: { bg: 'bg-emerald-500/15', text: 'text-emerald-400', ring: 'ring-emerald-500/30', fill: 'bg-emerald-400', glow: 'shadow-emerald-500/30', border: 'border-emerald-500/40' },
  blue:    { bg: 'bg-blue-500/15', text: 'text-blue-400', ring: 'ring-blue-500/30', fill: 'bg-blue-400', glow: 'shadow-blue-500/30', border: 'border-blue-500/40' },
  purple:  { bg: 'bg-purple-500/15', text: 'text-purple-400', ring: 'ring-purple-500/30', fill: 'bg-purple-400', glow: 'shadow-purple-500/30', border: 'border-purple-500/40' },
  slate:   { bg: 'bg-slate-500/15', text: 'text-slate-400', ring: 'ring-slate-500/30', fill: 'bg-slate-400', glow: 'shadow-slate-500/30', border: 'border-slate-500/40' },
};

function colorClasses(color) {
  return COLOR_MAP[color] || COLOR_MAP.blue;
}

function formatDuration(ms) {
  if (!ms) return '--';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
function formatTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
function timeSince(ts) {
  if (!ts) return '';
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

// ──────────────────────────────────────────────────────────
//  Engine stages — THE Parity loop, top-to-bottom
//
//  Each stage:
//    key    : matches the activity_bus.node value emitted by the
//             backend, so the live SSE feed lights up the right tile.
//    model  : the tier executing this stage (see MODEL_CONFIG).
//    status : 'live' (wired today) or 'pending' (engine slot kept
//             visible so the demo viewer sees the whole shape).
// ──────────────────────────────────────────────────────────
const ENGINE_STAGES = [
  {
    key: 'snapshot',
    label: 'Snapshot',
    sub: 'Python captures device state',
    model: 'pyats',
    icon: 'photo_camera',
    status: 'live',
  },
  {
    key: 'diff',
    label: 'Diff',
    sub: 'Python compares to previous snapshot',
    model: 'deterministic',
    icon: 'difference',
    status: 'live',
  },
  {
    key: 'davis-reasoning',
    label: 'Reasoning',
    sub: 'Gemini Flash produces the verdict; Davis Copilot queried in parallel as a second opinion',
    model: 'davis',
    icon: 'auto_awesome',
    status: 'live',
  },
  {
    key: 'remediation',
    label: 'Remediation Draft',
    sub: 'Gemini Pro drafts commands + rollback',
    model: 'pro',
    icon: 'edit_note',
    status: 'pending',
  },
  {
    key: 'approval',
    label: 'Approval',
    sub: 'Operator approves in UI or Slack',
    model: 'human',
    icon: 'verified_user',
    status: 'live',
  },
  {
    key: 'execution',
    label: 'Execute',
    sub: 'Python pushes commands to the device',
    model: 'pyats',
    icon: 'play_arrow',
    status: 'live',
  },
  {
    key: 'verification',
    label: 'Verify',
    sub: 'Fresh snapshot + Davis confirms the fix',
    model: 'pyats',
    icon: 'fact_check',
    status: 'live',
  },
];

// ──────────────────────────────────────────────────────────
//  Engine graphic — Parity's loop, visible to demo viewers
// ──────────────────────────────────────────────────────────
function EngineFlow({ active }) {
  // event.node → boolean (is currently active)
  const activeNodes = new Set((active || []).map(a => a.node));

  return (
    <div className="overflow-x-auto py-4 px-1">
      <div className="flex items-stretch gap-0 min-w-[1100px]">
        {ENGINE_STAGES.map((stage, i) => {
          const cfg = MODEL_CONFIG[stage.model];
          const c = colorClasses(cfg.color);
          const isActive = activeNodes.has(stage.key);
          const isPending = stage.status === 'pending';

          return (
            <div key={stage.key} className="flex items-stretch flex-1 min-w-[150px]">
              <div className={`flex-1 rounded-xl border p-3 transition-all duration-500 ${
                isActive
                  ? `${c.bg} ${c.border} shadow-lg ${c.glow}`
                  : isPending
                    ? 'bg-surface-container-lowest border-outline-variant/30 border-dashed opacity-60'
                    : 'bg-surface-container-lowest border-outline-variant/30'
              }`}>
                <div className="flex items-start justify-between mb-2">
                  <div className={`w-9 h-9 rounded-lg flex items-center justify-center transition-all ${
                    isActive
                      ? `${c.fill} shadow-md ${c.glow}`
                      : `${c.bg}`
                  }`}>
                    <Icon
                      name={stage.icon}
                      className={`text-lg ${isActive ? 'text-white' : c.text}`}
                    />
                  </div>
                  {isActive && (
                    <span className={`w-2 h-2 rounded-full ${c.fill} animate-pulse mt-1`} />
                  )}
                  {isPending && !isActive && (
                    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-surface-container-high text-on-surface-variant/60 uppercase tracking-wider">
                      Pending
                    </span>
                  )}
                </div>
                <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1">
                  Step {i + 1}
                </div>
                <div className="text-sm font-bold text-on-surface mb-1">
                  {stage.label}
                </div>
                <div className="text-[11px] text-on-surface-variant leading-snug mb-2">
                  {stage.sub}
                </div>
                <div className="flex items-center gap-1">
                  <span className={`inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full ${c.bg} ${c.text} uppercase tracking-wide`}>
                    <Icon name={cfg.icon} className="text-[10px]" />
                    {cfg.label}
                  </span>
                </div>
              </div>
              {i < ENGINE_STAGES.length - 1 && (
                <div className="flex items-center px-1">
                  <Icon
                    name="chevron_right"
                    className={`text-2xl transition-colors ${
                      isActive ? c.text : 'text-on-surface-variant/30'
                    }`}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────
//  Model tier card (right-rail, one per LLM tier)
// ──────────────────────────────────────────────────────────
function ModelTierCard({ modelKey, active, lastEvent }) {
  const cfg = MODEL_CONFIG[modelKey];
  if (!cfg) return null;
  const c = colorClasses(cfg.color);
  const isActive = !!active;

  return (
    <div className={`relative rounded-xl border p-4 transition-all duration-500 ${
      isActive
        ? `${c.bg} ${c.border} shadow-lg ${c.glow}`
        : 'bg-surface-container-lowest border-outline-variant/30'
    }`}>
      {isActive && (
        <div className="absolute top-3 right-3">
          <span className={`inline-block w-2.5 h-2.5 rounded-full ${c.fill} animate-pulse`} />
        </div>
      )}
      <div className="flex items-center gap-3 mb-3">
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${c.bg}`}>
          <Icon name={cfg.icon} className={`text-xl ${c.text}`} />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-on-surface">{cfg.label}</span>
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${c.bg} ${c.text} uppercase tracking-wide`}>
              {cfg.tier}
            </span>
          </div>
          <p className="text-[11px] text-on-surface-variant">{cfg.desc}</p>
        </div>
      </div>

      {isActive ? (
        <div className={`rounded-lg ${c.bg} p-3`}>
          <div className="flex items-center gap-2 mb-1">
            <div className={`w-1.5 h-1.5 rounded-full ${c.fill} animate-pulse`} />
            <span className={`text-xs font-semibold ${c.text}`}>Working</span>
          </div>
          <p className="text-xs text-on-surface-variant leading-relaxed">{active.detail}</p>
          <p className="text-[10px] text-on-surface-variant/60 mt-1">{active.device} &middot; started {timeSince(active.started_at)}</p>
        </div>
      ) : lastEvent ? (
        <div className="rounded-lg bg-surface-container-high/50 p-3">
          <div className="flex items-center gap-2 mb-1">
            <Icon name={lastEvent.status === 'completed' ? 'check_circle' : 'error'} className={`text-sm ${lastEvent.status === 'completed' ? 'text-secondary' : 'text-error'}`} />
            <span className="text-xs font-medium text-on-surface-variant">
              {lastEvent.status === 'completed' ? 'Last run' : 'Failed'}
            </span>
          </div>
          <p className="text-xs text-on-surface-variant leading-relaxed">{lastEvent.detail}</p>
          <p className="text-[10px] text-on-surface-variant/60 mt-1">{formatDuration(lastEvent.duration_ms)} &middot; {timeSince(lastEvent.completed_at)}</p>
        </div>
      ) : (
        <div className="rounded-lg bg-surface-container-high/30 p-3">
          <p className="text-xs text-on-surface-variant/40 italic">Idle — no recent activity</p>
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────
//  Activity timeline row
// ──────────────────────────────────────────────────────────
function ActivityEntry({ event }) {
  const mk = resolveModelKey(event.model);
  const cfg = mk ? MODEL_CONFIG[mk] : null;
  const c = cfg ? colorClasses(cfg.color) : colorClasses('blue');
  const isCompleted = event.status === 'completed';
  const isActive = event.status === 'started' || event.status === 'thinking';

  return (
    <div className={`flex gap-3 py-3 px-4 rounded-lg transition-all ${
      isActive ? `${c.bg} ring-1 ${c.ring}` : 'hover:bg-surface-container-high/30'
    }`}>
      <div className="flex flex-col items-center mt-0.5">
        <div className={`w-7 h-7 rounded-full flex items-center justify-center ${
          isActive ? `${c.fill} animate-pulse` : isCompleted ? 'bg-secondary/20' : 'bg-error/20'
        }`}>
          <Icon
            name={isActive ? (cfg?.icon || 'sync') : isCompleted ? 'check' : 'close'}
            className={`text-sm ${
              isActive ? 'text-white' : isCompleted ? 'text-secondary' : 'text-error'
            }`}
          />
        </div>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-bold text-on-surface">
            {NODE_LABELS[event.node] || event.node}
          </span>
          {cfg && (
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${c.bg} ${c.text} ring-1 ${c.ring} uppercase tracking-wide`}>
              {cfg.label}
            </span>
          )}
          {isActive && (
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-400 ring-1 ring-amber-500/30 uppercase tracking-wide animate-pulse">
              Active
            </span>
          )}
          <span className="text-[10px] text-on-surface-variant/50 ml-auto tabular-nums">
            {formatTime(event.started_at)}
          </span>
        </div>
        <p className="text-xs text-on-surface-variant mt-0.5 leading-relaxed">{event.detail}</p>
        <div className="flex items-center gap-3 mt-1">
          <span className="text-[10px] text-on-surface-variant/50">{event.device}</span>
          {event.tokens > 0 && (
            <span className="text-[10px] text-on-surface-variant/50">{event.tokens.toLocaleString()} tokens</span>
          )}
          {event.duration_ms > 0 && (
            <span className="text-[10px] text-on-surface-variant/50">{formatDuration(event.duration_ms)}</span>
          )}
        </div>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────
//  Page
// ──────────────────────────────────────────────────────────
export default function Pipeline() {
  const [active, setActive] = useState([]);
  const [history, setHistory] = useState([]);
  const [connected, setConnected] = useState(false);
  const retryRef = useRef(0);
  const evtSourceRef = useRef(null);

  const connect = useCallback(() => {
    const eventSource = new EventSource('/api/v1/pipeline/activity/stream');
    evtSourceRef.current = eventSource;

    eventSource.addEventListener('snapshot', (e) => {
      const data = JSON.parse(e.data);
      setActive(data.active || []);
      setHistory(data.history || []);
      setConnected(true);
      retryRef.current = 0;
    });

    eventSource.addEventListener('activity', (e) => {
      const event = JSON.parse(e.data);
      setActive(prev => {
        if (event.status === 'started' || event.status === 'thinking') {
          const exists = prev.find(a => a.id === event.id);
          if (exists) return prev.map(a => a.id === event.id ? event : a);
          return [...prev, event];
        }
        return prev.filter(a => a.id !== event.id);
      });
      if (event.status === 'completed' || event.status === 'failed') {
        setHistory(prev => [event, ...prev].slice(0, 100));
      }
    });

    eventSource.onerror = () => {
      setConnected(false);
      eventSource.close();
      const delay = Math.min(2000 * (2 ** retryRef.current), 30000);
      retryRef.current++;
      setTimeout(connect, delay);
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (evtSourceRef.current) evtSourceRef.current.close();
    };
  }, [connect]);

  // Derive last event per model tier for the right rail cards.
  const lastByModel = {};
  for (const evt of history) {
    const mk = resolveModelKey(evt.model);
    if (mk && !lastByModel[mk]) lastByModel[mk] = evt;
  }
  const activeByModel = {};
  for (const evt of active) {
    const mk = resolveModelKey(evt.model);
    if (mk) activeByModel[mk] = evt;
  }

  // Tier cards to surface (skip 'human' + 'deterministic' — they don't run LLMs).
  const TIER_CARDS = ['pyats', 'davis', 'flash', 'pro'];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-on-surface">The Parity Engine</h1>
          <p className="text-sm text-on-surface-variant mt-1">
            Python captures. Gemini 2.5 reasons. You approve. Python acts. The verifier confirms — every step mirrored to Dynatrace Davis.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-secondary animate-pulse' : 'bg-error'}`} />
          <span className="text-xs text-on-surface-variant">
            {connected ? 'Live' : 'Reconnecting...'}
          </span>
        </div>
      </div>

      {/* Engine Flow — always visible */}
      <div className="bg-surface-container-lowest rounded-xl shadow-sm p-4">
        <div className="flex items-center justify-between mb-3 px-2">
          <h2 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
            Engine Flow
          </h2>
          <span className="text-[10px] text-on-surface-variant/60">
            Steps light up as events stream in. Dashed tiles are wired but not yet emitting.
          </span>
        </div>
        <EngineFlow active={active} />
      </div>

      {/* Model Tier Cards */}
      <div>
        <h2 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-3">
          Reasoner & Engine Status
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {TIER_CARDS.map(mk => (
            <ModelTierCard
              key={mk}
              modelKey={mk}
              active={activeByModel[mk]}
              lastEvent={lastByModel[mk]}
            />
          ))}
        </div>
      </div>

      {/* Activity Timeline */}
      <div className="bg-surface-container-lowest rounded-xl shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-outline-variant/20 flex items-center justify-between">
          <h2 className="text-sm font-bold text-on-surface">Activity Timeline</h2>
          <span className="text-xs text-on-surface-variant">
            {history.length} events
          </span>
        </div>
        <div className="max-h-[600px] overflow-y-auto divide-y divide-outline-variant/10">
          {active.map(evt => (
            <ActivityEntry key={evt.id} event={evt} />
          ))}
          {history.map(evt => (
            <ActivityEntry key={evt.id} event={evt} />
          ))}
          {active.length === 0 && history.length === 0 && (
            <div className="p-12 text-center">
              <Icon name="psychology" className="text-4xl text-on-surface-variant/20 mb-3" />
              <p className="text-sm text-on-surface-variant/40">No engine activity yet</p>
              <p className="text-xs text-on-surface-variant/30 mt-1">
                Trigger a snapshot or hit <code className="font-mono">/api/v1/dynatrace/analyze-snapshot/&lt;id&gt;</code> to watch the engine fire.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
