import { useCallback, useEffect, useMemo, useState } from 'react';
import { useApi } from '../hooks/useApi';
import { api } from '../api/client';
import Icon from '../components/Icon';
import StatusChip from '../components/StatusChip';
import { useDialog } from '../components/Dialog';

const ALL_FEATURES = [
  'interface', 'ospf', 'bgp', 'arp', 'vlan',
  'spanning_tree', 'routing', 'platform', 'hsrp', 'vrf',
];

const CRON_PRESETS = [
  { label: 'Every 15 minutes',   value: '*/15 * * * *' },
  { label: 'Every hour',         value: '0 * * * *' },
  { label: 'Every 6 hours',      value: '0 */6 * * *' },
  { label: 'Daily at 03:00 UTC', value: '0 3 * * *' },
  { label: 'Mon–Fri at 09:00',   value: '0 9 * * 1-5' },
  { label: 'Custom',             value: '__custom__' },
];

function DepStatus({ name, status }) {
  const ok = status === 'healthy' || status === 'connected' || status === true || status === 'ok';
  return (
    <div className="flex items-center justify-between py-4">
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${ok ? 'bg-secondary/10' : 'bg-error/10'}`}>
          <Icon name={ok ? 'check_circle' : 'error'} className={ok ? 'text-secondary' : 'text-error'} />
        </div>
        <div>
          <p className="font-bold text-on-surface">{name}</p>
          <p className="text-[11px] text-on-surface-variant">{typeof status === 'string' ? status : ok ? 'Connected' : 'Unreachable'}</p>
        </div>
      </div>
      <StatusChip variant={ok ? 'success' : 'error'} dot>{ok ? 'HEALTHY' : 'DOWN'}</StatusChip>
    </div>
  );
}

function formatNext(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleString();
}

function ResultChip({ result }) {
  if (!result) return <span className="text-[11px] text-on-surface-variant">never run</span>;
  const variant =
    result === 'ok' ? 'success'
      : result === 'partial' ? 'warning'
      : result === 'skipped' ? 'neutral'
      : result === 'running' ? 'info'
      : 'error';
  return <StatusChip variant={variant} dot>{result.toUpperCase()}</StatusChip>;
}

function ScheduleForm({ initial, devices, onCancel, onSubmit, submitting }) {
  const [name, setName]     = useState(initial?.name ?? '');
  const presetForCron = (cron) => CRON_PRESETS.find((p) => p.value === cron)?.value ?? '__custom__';
  const [preset, setPreset] = useState(presetForCron(initial?.cron_expr ?? '0 */6 * * *'));
  const [cron, setCron]     = useState(initial?.cron_expr ?? '0 */6 * * *');
  const [allDevices, setAllDevices]   = useState((initial?.device_ids ?? []).length === 0);
  const [deviceIds, setDeviceIds]     = useState(initial?.device_ids ?? []);
  const [defaultFeatures, setDefaultFeatures] = useState((initial?.features ?? []).length === 0);
  const [features, setFeatures]       = useState(initial?.features ?? []);
  const [enabled, setEnabled]         = useState(initial?.enabled ?? true);
  const [error, setError]             = useState(null);

  const toggleDevice = (id) => {
    setDeviceIds((prev) => prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]);
  };
  const toggleFeature = (f) => {
    setFeatures((prev) => prev.includes(f) ? prev.filter((x) => x !== f) : [...prev, f]);
  };

  const handlePreset = (v) => {
    setPreset(v);
    if (v !== '__custom__') setCron(v);
  };

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    if (!name.trim()) return setError('Name is required');
    if (!cron.trim()) return setError('Cron expression is required');
    try {
      await onSubmit({
        name: name.trim(),
        cron_expr: cron.trim(),
        device_ids: allDevices ? [] : deviceIds,
        features: defaultFeatures ? [] : features,
        enabled,
      });
    } catch (err) {
      setError(err.message || 'Save failed');
    }
  };

  return (
    <form onSubmit={submit} className="space-y-5">
      <div>
        <label className="block text-[11px] font-bold uppercase tracking-wider text-on-surface-variant mb-1.5">Name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full px-3 py-2 rounded-lg border border-outline/20 bg-surface text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          placeholder="Nightly full snapshot"
        />
      </div>

      <div>
        <label className="block text-[11px] font-bold uppercase tracking-wider text-on-surface-variant mb-1.5">Schedule</label>
        <div className="flex gap-2">
          <select
            value={preset}
            onChange={(e) => handlePreset(e.target.value)}
            className="px-3 py-2 rounded-lg border border-outline/20 bg-surface text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 min-w-[180px]"
          >
            {CRON_PRESETS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
          <input
            type="text"
            value={cron}
            onChange={(e) => { setCron(e.target.value); setPreset('__custom__'); }}
            className="flex-1 px-3 py-2 rounded-lg border border-outline/20 bg-surface text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/30"
            placeholder="0 */6 * * *"
          />
        </div>
        <p className="text-[10px] text-on-surface-variant mt-1.5">5-field cron, UTC. Edit directly for anything outside the presets.</p>
      </div>

      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="block text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">Devices</label>
          <label className="flex items-center gap-1.5 text-xs cursor-pointer">
            <input type="checkbox" checked={allDevices} onChange={(e) => setAllDevices(e.target.checked)} className="accent-primary" />
            <span className="text-on-surface-variant">All devices</span>
          </label>
        </div>
        {!allDevices && (
          <div className="border border-outline/20 rounded-lg p-2 max-h-48 overflow-y-auto">
            {(devices || []).length === 0 ? (
              <p className="text-xs text-on-surface-variant p-2">No devices available</p>
            ) : (
              devices.map((d) => (
                <label key={d.id} className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-surface-container-low cursor-pointer">
                  <input type="checkbox" checked={deviceIds.includes(d.id)} onChange={() => toggleDevice(d.id)} className="accent-primary" />
                  <span className="text-xs text-on-surface flex-1 truncate">{d.hostname}</span>
                  <span className="text-[10px] text-on-surface-variant">{d.management_ip}</span>
                </label>
              ))
            )}
          </div>
        )}
      </div>

      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="block text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">Features</label>
          <label className="flex items-center gap-1.5 text-xs cursor-pointer">
            <input type="checkbox" checked={defaultFeatures} onChange={(e) => setDefaultFeatures(e.target.checked)} className="accent-primary" />
            <span className="text-on-surface-variant">Use defaults per device type</span>
          </label>
        </div>
        {!defaultFeatures && (
          <div className="flex flex-wrap gap-2 border border-outline/20 rounded-lg p-3">
            {ALL_FEATURES.map((f) => {
              const on = features.includes(f);
              return (
                <button
                  key={f}
                  type="button"
                  onClick={() => toggleFeature(f)}
                  className={`px-2.5 py-1 rounded-full text-[11px] font-bold uppercase tracking-wider transition-colors ${
                    on ? 'bg-primary text-on-primary' : 'bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high'
                  }`}
                >
                  {f}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <label className="flex items-center gap-2 cursor-pointer">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="accent-primary w-4 h-4" />
        <span className="text-sm text-on-surface">Enabled</span>
      </label>

      {error && (
        <p className="text-xs text-error bg-error/5 border border-error/20 rounded-lg px-3 py-2">{error}</p>
      )}

      <div className="flex items-center justify-end gap-2 pt-2">
        <button type="button" onClick={onCancel} className="px-4 py-2 rounded-lg text-sm font-bold text-on-surface-variant hover:bg-surface-container-low transition-colors">
          Cancel
        </button>
        <button type="submit" disabled={submitting} className="px-4 py-2 rounded-lg text-sm font-bold bg-primary text-on-primary hover:bg-primary/90 disabled:opacity-50 transition-colors">
          {submitting ? 'Saving…' : initial ? 'Save changes' : 'Create schedule'}
        </button>
      </div>
    </form>
  );
}

function ScheduleRow({ schedule, devices, onToggle, onEdit, onDelete, onRunNow, busy }) {
  const deviceLabel = !schedule.device_ids?.length
    ? 'All devices'
    : `${schedule.device_ids.length} device${schedule.device_ids.length === 1 ? '' : 's'}`;
  const featureLabel = !schedule.features?.length
    ? 'Default features'
    : `${schedule.features.length} feature${schedule.features.length === 1 ? '' : 's'}`;
  return (
    <div className={`grid grid-cols-[1.4fr_1.2fr_1fr_1.4fr_1fr_180px] gap-3 px-4 py-3 items-center border-t border-outline/10 ${!schedule.enabled ? 'opacity-60' : ''}`}>
      <div className="min-w-0">
        <p className="text-sm font-bold text-on-surface truncate">{schedule.name}</p>
        <p className="text-[10px] text-on-surface-variant">{deviceLabel} · {featureLabel}</p>
      </div>
      <code className="text-[11px] font-mono text-on-surface-variant truncate">{schedule.cron_expr}</code>
      <span className="text-[11px] text-on-surface-variant">{formatNext(schedule.next_run_at)}</span>
      <div className="flex items-center gap-2">
        <ResultChip result={schedule.last_result} />
        {schedule.last_run_at && (
          <span className="text-[10px] text-on-surface-variant">
            {new Date(schedule.last_run_at).toLocaleString()}
          </span>
        )}
      </div>
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={schedule.enabled}
          onChange={(e) => onToggle(schedule, e.target.checked)}
          disabled={busy}
          className="accent-primary w-4 h-4"
        />
        <span className="text-xs font-bold text-on-surface-variant">{schedule.enabled ? 'On' : 'Off'}</span>
      </label>
      <div className="flex items-center justify-end gap-1">
        <button onClick={() => onRunNow(schedule)} disabled={busy} title="Run snapshot now"
          className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-bold uppercase tracking-wider text-primary border border-primary/30 hover:bg-primary/10 transition-colors disabled:opacity-50">
          <Icon name="play_arrow" className="text-sm" />
          Run now
        </button>
        <button onClick={() => onEdit(schedule)} disabled={busy} title="Edit"
          className="p-1.5 rounded-lg text-on-surface-variant hover:text-primary hover:bg-primary/10 transition-colors">
          <Icon name="edit" className="text-base" />
        </button>
        <button onClick={() => onDelete(schedule)} disabled={busy} title="Delete"
          className="p-1.5 rounded-lg text-on-surface-variant hover:text-error hover:bg-error/10 transition-colors">
          <Icon name="delete" className="text-base" />
        </button>
      </div>
    </div>
  );
}

function SnapshotSchedules() {
  const [schedules, setSchedules] = useState([]);
  const [devices, setDevices]     = useState([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);
  const [busy, setBusy]           = useState(false);
  const [showForm, setShowForm]   = useState(false);
  const [editing, setEditing]     = useState(null);
  const dialog = useDialog();

  const reload = useCallback(async () => {
    try {
      const [s, d] = await Promise.all([api.schedules(), api.devices()]);
      setSchedules(s);
      setDevices(d);
      setError(null);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const handleCreate = async (body) => {
    setBusy(true);
    try {
      await api.createSchedule(body);
      setShowForm(false);
      setEditing(null);
      await reload();
    } finally { setBusy(false); }
  };
  const handleUpdate = async (body) => {
    setBusy(true);
    try {
      await api.updateSchedule(editing.id, body);
      setShowForm(false);
      setEditing(null);
      await reload();
    } finally { setBusy(false); }
  };
  const handleToggle = async (sched, enabled) => {
    setBusy(true);
    try {
      await api.updateSchedule(sched.id, { enabled });
      await reload();
    } finally { setBusy(false); }
  };
  const handleDelete = async (sched) => {
    const ok = await dialog.confirm({
      title: 'Delete schedule?',
      message: `"${sched.name}" will be removed and its job unregistered. Snapshot data already taken is kept.`,
      confirmLabel: 'Delete',
      variant: 'danger',
    });
    if (!ok) return;
    setBusy(true);
    try {
      await api.deleteSchedule(sched.id);
      await reload();
    } finally { setBusy(false); }
  };
  const handleRunNow = async (sched) => {
    const ok = await dialog.confirm({
      title: `Run "${sched.name}" now?`,
      message: 'A snapshot will start immediately. If another snapshot is already running, this run will be skipped.',
      confirmLabel: 'Run now',
      variant: 'primary',
    });
    if (!ok) return;
    setBusy(true);
    try {
      await api.runScheduleNow(sched.id);
      // Don't await reload — schedule runs in the background
      setTimeout(reload, 500);
    } finally { setBusy(false); }
  };

  return (
    <section className="mb-8">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold text-on-surface">Snapshot Schedules</h2>
        {!showForm && (
          <button
            onClick={() => { setEditing(null); setShowForm(true); }}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-primary text-on-primary text-xs font-bold hover:bg-primary/90 transition-colors"
          >
            <Icon name="add" className="text-base" />
            New schedule
          </button>
        )}
      </div>

      {showForm && (
        <div className="bg-surface-container-lowest rounded-xl p-6 shadow-sm mb-4">
          <h3 className="text-sm font-bold text-on-surface mb-4">{editing ? 'Edit schedule' : 'Create schedule'}</h3>
          <ScheduleForm
            initial={editing}
            devices={devices}
            onCancel={() => { setShowForm(false); setEditing(null); }}
            onSubmit={editing ? handleUpdate : handleCreate}
            submitting={busy}
          />
        </div>
      )}

      <div className="bg-surface-container-lowest rounded-xl shadow-sm overflow-hidden">
        <div className="grid grid-cols-[1.4fr_1.2fr_1fr_1.4fr_1fr_180px] gap-3 px-4 py-2.5 bg-surface-container-low">
          {['Name', 'Cron', 'Next run', 'Last result', 'State', 'Actions'].map((h) => (
            <span key={h} className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">{h}</span>
          ))}
        </div>
        {loading ? (
          <p className="text-on-surface-variant py-8 text-center text-sm">Loading…</p>
        ) : error ? (
          <p className="text-error py-8 text-center text-sm">Failed to load: {error.message}</p>
        ) : schedules.length === 0 ? (
          <div className="flex flex-col items-center py-10 text-on-surface-variant">
            <Icon name="schedule" className="text-3xl mb-2 opacity-40" />
            <p className="text-sm font-semibold">No schedules yet</p>
            <p className="text-xs mt-1 opacity-60">Click "New schedule" to automate snapshots</p>
          </div>
        ) : (
          schedules.map((s) => (
            <ScheduleRow
              key={s.id}
              schedule={s}
              devices={devices}
              busy={busy}
              onToggle={handleToggle}
              onEdit={(sch) => { setEditing(sch); setShowForm(true); }}
              onDelete={handleDelete}
              onRunNow={handleRunNow}
            />
          ))
        )}
      </div>
    </section>
  );
}

export default function Settings() {
  const { data: health, loading } = useApi(api.healthDeps);
  const deps = health?.dependencies || health || {};

  return (
    <div className="max-w-5xl">
      <div className="mb-10">
        <div className="flex items-center gap-2 mb-2">
          <span className="w-2 h-2 rounded-full bg-primary" />
          <span className="text-[10px] font-bold tracking-widest text-on-surface-variant uppercase">Configuration</span>
        </div>
        <h1 className="text-4xl font-extrabold text-on-surface tracking-tight">Settings</h1>
      </div>

      <SnapshotSchedules />

      {/* Service Health */}
      <section className="mb-8">
        <h2 className="text-xl font-bold text-on-surface mb-4">Service Dependencies</h2>
        <div className="bg-surface-container-lowest rounded-xl p-6 shadow-sm">
          {loading ? (
            <p className="text-on-surface-variant py-8 text-center">Checking dependencies...</p>
          ) : deps && Object.keys(deps).length ? (
            <div className="divide-y divide-surface-container-low">
              {Object.entries(deps).map(([key, val]) => (
                <DepStatus key={key} name={key} status={typeof val === 'object' ? val.status : val} />
              ))}
            </div>
          ) : (
            <p className="text-on-surface-variant py-8 text-center">Unable to reach backend API</p>
          )}
        </div>
      </section>

      <section className="mb-8">
        <h2 className="text-xl font-bold text-on-surface mb-4">Integrations</h2>
        <div className="bg-surface-container-lowest rounded-xl shadow-sm divide-y divide-surface-container-low">
          {[
            { name: 'Grafana', desc: 'Device inventory source', icon: 'monitoring' },
            { name: 'Slack', desc: 'Approval notifications', icon: 'chat' },
            { name: 'Jira', desc: 'Ticket management', icon: 'confirmation_number' },
            { name: 'Dynatrace Davis', desc: 'Findings mirrored via Events API · DQL read-back via Grail', icon: 'hexagon' },
            { name: 'Dynatrace MCP', desc: 'Davis problem source · stdio/HTTP transports', icon: 'monitor_heart' },
            { name: 'Vertex AI', desc: 'Gemini 2.5 on Google Cloud', icon: 'smart_toy' },
          ].map((item) => (
            <div key={item.name} className="flex items-center justify-between p-6">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                  <Icon name={item.icon} className="text-primary" />
                </div>
                <div>
                  <p className="font-bold text-on-surface">{item.name}</p>
                  <p className="text-[11px] text-on-surface-variant">{item.desc}</p>
                </div>
              </div>
              <button className="text-xs font-bold text-primary uppercase tracking-wider hover:underline">
                Configure
              </button>
            </div>
          ))}
        </div>
      </section>

      <section className="mb-8">
        <h2 className="text-xl font-bold text-on-surface mb-4">AI Model Tiers</h2>
        <div className="bg-surface-container-lowest rounded-xl shadow-sm divide-y divide-surface-container-low">
          {[
            { tier: 'Tier 0', model: 'Gemini 2.5 Flash-Lite', use: 'Data normalisation, fast probes', cost: 'Lowest' },
            { tier: 'Tier 1', model: 'Gemini 2.5 Flash', use: 'Classification, chat assistant tools', cost: 'Low' },
            { tier: 'Tier 2', model: 'Gemini 2.5 Pro', use: 'Remediation reasoning, escalation', cost: 'Higher' },
          ].map((item) => (
            <div key={item.tier} className="flex items-center justify-between p-6">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] font-bold bg-primary/10 text-primary px-2 py-0.5 rounded">{item.tier}</span>
                  <p className="font-bold text-on-surface">{item.model}</p>
                </div>
                <p className="text-[11px] text-on-surface-variant">{item.use} — {item.cost} cost</p>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
