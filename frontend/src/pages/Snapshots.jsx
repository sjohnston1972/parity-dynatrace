import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { api } from '../api/client';
import { useSnapshotStatus } from '../hooks/useSnapshotStatus';
import Icon from '../components/Icon';
import StatusChip from '../components/StatusChip';
import { useDialog } from '../components/Dialog';

function timeAgo(dateStr) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function formatDuration(seconds) {
  if (!seconds) return '--';
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(0);
  return `${m}m ${s}s`;
}

function GoldenBadge({ small = false }) {
  // Discreet baseline marker. Amber says "important / curated" without
  // shouting; soft fills keep it from competing with severity colours.
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full bg-amber-500/10 ring-1 ring-amber-500/25 text-amber-700 dark:text-amber-300 ${
        small ? 'px-1.5 py-0.5 text-[9px]' : 'px-2 py-0.5 text-[10px]'
      } font-bold uppercase tracking-widest`}
      title="This snapshot is the device's blessed baseline"
    >
      <Icon name="bookmark_star" className={small ? 'text-[10px]' : 'text-[12px]'} />
      Baseline
    </span>
  );
}


function SnapshotRow({ snapshot, devices, snapCount, isSelected, onSelect, isChecked, onToggleCheck }) {
  const device = devices.find((d) => d.id === snapshot.device_id);
  const hostname = device?.hostname || snapshot.device_id.slice(0, 8);
  const hasError = snapshot.features_learned?.length === 0;
  const isGolden = !!snapshot.is_golden;

  return (
    <div
      onClick={() => onSelect(snapshot)}
      className={`relative grid grid-cols-[32px_2fr_0.6fr_1.2fr_1fr_1fr_1fr_32px] gap-3 px-5 py-3.5 cursor-pointer transition-colors ${
        isSelected ? 'bg-primary/5' : isGolden ? 'hover:bg-amber-50/40' : 'hover:bg-blue-50/30'
      }`}
    >
      {/* Golden-baseline left edge accent — thin, subtle */}
      {isGolden && (
        <span
          aria-hidden="true"
          className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r-full bg-amber-400/60"
        />
      )}
      {/* Checkbox */}
      <div className="flex items-center" onClick={(e) => e.stopPropagation()}>
        <input
          type="checkbox"
          checked={isChecked}
          onChange={() => onToggleCheck(snapshot.id)}
          className="w-4 h-4 accent-primary cursor-pointer"
          aria-label={`Select snapshot ${snapshot.id.slice(0, 8)}`}
        />
      </div>

      {/* Device */}
      <div className="flex items-center gap-3 min-w-0">
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
          hasError ? 'bg-error/10' : 'bg-primary/10'
        }`}>
          <Icon
            name={device?.device_type === 'switch' ? 'lan' : device?.device_type === 'firewall' ? 'shield' : 'router'}
            className={`text-base ${hasError ? 'text-error' : 'text-primary'}`}
          />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className={`text-sm font-bold truncate ${isSelected ? 'text-primary' : 'text-on-surface'}`}>
              {hostname}
            </span>
            {isGolden && <GoldenBadge small />}
          </div>
          <span className="text-[10px] text-on-surface-variant">{device?.management_ip || '--'}</span>
        </div>
      </div>

      {/* Snap count */}
      <div className="flex items-center">
        <span className="inline-flex items-center gap-1 text-xs font-bold text-on-surface-variant bg-surface-container-high rounded-full px-2 py-0.5">
          <Icon name="camera" className="text-[12px]" />
          {snapCount}
        </span>
      </div>

      {/* Time */}
      <div className="flex flex-col justify-center">
        <span className="text-xs text-on-surface">{timeAgo(snapshot.created_at)}</span>
        <span className="text-[10px] text-on-surface-variant">
          {new Date(snapshot.created_at).toLocaleString()}
        </span>
      </div>

      {/* Features */}
      <div className="flex items-center">
        <span className="text-xs text-on-surface font-mono">
          {snapshot.features_learned?.length || 0} features
        </span>
      </div>

      {/* Duration */}
      <div className="flex items-center">
        <span className="text-xs text-on-surface">{formatDuration(snapshot.duration_seconds)}</span>
      </div>

      {/* Status */}
      <div className="flex items-center">
        <StatusChip variant={hasError ? 'error' : 'success'} dot>
          {hasError ? 'FAILED' : 'OK'}
        </StatusChip>
      </div>

      {/* Chevron */}
      <div className="flex items-center justify-end">
        <Icon name="chevron_right" className="text-base text-outline" />
      </div>
    </div>
  );
}

const STATUS_STYLES = {
  added:   { icon: 'add_circle',    color: 'text-emerald-400', bg: 'bg-emerald-400/10', label: 'Added' },
  removed: { icon: 'remove_circle', color: 'text-red-400',     bg: 'bg-red-400/10',     label: 'Removed' },
  changed: { icon: 'change_circle', color: 'text-amber-400',   bg: 'bg-amber-400/10',   label: 'Changed' },
};

function DiffValue({ label, value, variant }) {
  const colors = variant === 'old'
    ? 'bg-red-500/10 border-red-500/20 text-red-300'
    : 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300';
  const formatted = typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
  return (
    <div className={`rounded-md border px-3 py-2 ${colors}`}>
      <span className="text-[9px] font-bold uppercase tracking-widest opacity-60 block mb-1">{label}</span>
      <pre className="font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-all">{formatted}</pre>
    </div>
  );
}

function DiffEntry({ path, change }) {
  const style = STATUS_STYLES[change.status] || STATUS_STYLES.changed;
  return (
    <details className="group rounded-lg bg-slate-900 overflow-hidden">
      <summary className="flex items-center gap-2.5 px-4 py-2.5 cursor-pointer hover:bg-slate-800/60 transition-colors">
        <Icon name={style.icon} className={`text-base ${style.color}`} />
        <span className="flex-1 font-mono text-[11px] text-slate-300 truncate">{path}</span>
        <span className={`text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${style.bg} ${style.color}`}>
          {style.label}
        </span>
        <Icon name="expand_more" className="text-sm text-slate-500 group-open:rotate-180 transition-transform" />
      </summary>
      <div className="px-4 pb-3 pt-1 space-y-2">
        {change.status === 'changed' && (
          <>
            <DiffValue label="Old" value={change.old} variant="old" />
            <DiffValue label="New" value={change.new} variant="new" />
          </>
        )}
        {change.status === 'added' && (
          <DiffValue label="Value" value={change.value} variant="new" />
        )}
        {change.status === 'removed' && (
          <DiffValue label="Value" value={change.value} variant="old" />
        )}
      </div>
    </details>
  );
}

function featureSummary(feature, data) {
  if (!data || typeof data !== 'object') return null;
  const stats = [];

  if (feature === 'interface') {
    const entries = Object.entries(data);
    const up = entries.filter(([, v]) => v?.oper_status === 'up').length;
    stats.push({ label: 'Interfaces', value: entries.length });
    stats.push({ label: 'Up', value: up });
    stats.push({ label: 'Down', value: entries.length - up });
  } else if (feature === 'bgp') {
    let neighbors = 0, established = 0;
    for (const inst of Object.values(data.instance || {})) {
      for (const vrf of Object.values(inst?.vrf || {})) {
        const n = Object.entries(vrf?.neighbor || {});
        neighbors += n.length;
        established += n.filter(([, v]) => v?.session_state === 'Established').length;
      }
    }
    stats.push({ label: 'Neighbors', value: neighbors });
    stats.push({ label: 'Established', value: established });
    if (neighbors - established > 0) stats.push({ label: 'Down', value: neighbors - established });
  } else if (feature === 'vlan') {
    const vlans = Object.keys(data.vlans || {});
    stats.push({ label: 'VLANs', value: vlans.length });
  } else if (feature === 'ospf') {
    let areas = 0, intfs = 0;
    const walk = (obj) => {
      if (!obj || typeof obj !== 'object') return;
      if (obj.areas) { areas += Object.keys(obj.areas).length; }
      if (obj.interfaces) { intfs += Object.keys(obj.interfaces).length; }
      Object.values(obj).forEach((v) => { if (typeof v === 'object') walk(v); });
    };
    walk(data);
    stats.push({ label: 'Areas', value: areas });
    stats.push({ label: 'Interfaces', value: intfs });
  } else if (feature === 'arp') {
    const entries = data.interfaces ? Object.values(data.interfaces).reduce(
      (sum, intf) => sum + Object.keys(intf?.ipv4?.neighbors || {}).length, 0
    ) : 0;
    const stats_data = data.statistics || {};
    stats.push({ label: 'ARP Entries', value: entries || '--' });
    if (stats_data.in_requests_pkts) stats.push({ label: 'Requests In', value: stats_data.in_requests_pkts });
  } else if (feature === 'routing') {
    let routes = 0;
    for (const vrf of Object.values(data.vrf || {})) {
      for (const af of Object.values(vrf?.address_family || {})) {
        routes += Object.keys(af?.routes || {}).length;
      }
    }
    stats.push({ label: 'Routes', value: routes });
  } else if (feature === 'platform') {
    if (data.chassis) stats.push({ label: 'Chassis', value: data.chassis });
    if (data.os) stats.push({ label: 'OS', value: data.os });
    if (data.version) stats.push({ label: 'Version', value: data.version });
  } else if (feature === 'hsrp') {
    let groups = 0;
    const walk = (obj) => {
      if (!obj || typeof obj !== 'object') return;
      if (obj.group_number !== undefined) { groups++; return; }
      Object.values(obj).forEach(walk);
    };
    walk(data);
    stats.push({ label: 'HSRP Groups', value: groups });
  } else if (feature === 'vrf') {
    stats.push({ label: 'VRFs', value: Object.keys(data.vrfs || data).length });
  }

  return stats.length > 0 ? stats : null;
}

const FEATURE_ICONS = {
  interface: 'settings_ethernet',
  bgp: 'hub',
  ospf: 'swap_calls',
  vlan: 'layers',
  arp: 'dns',
  routing: 'alt_route',
  platform: 'memory',
  hsrp: 'sync',
  vrf: 'account_tree',
};

function SnapshotDetail({ snapshot, devices, onClose, onSelectSnapshot, onDelete, onBless, blessing }) {
  const [tab, setTab] = useState('DATA');
  const [detail, setDetail] = useState(null);
  const [diff, setDiff] = useState(null);
  const [deviceSnaps, setDeviceSnaps] = useState([]);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [loadingDiff, setLoadingDiff] = useState(false);
  const [loadingSnaps, setLoadingSnaps] = useState(false);

  const device = devices.find((d) => d.id === snapshot.device_id);

  useEffect(() => {
    setLoadingDetail(true);
    api.snapshot(snapshot.id)
      .then(setDetail)
      .catch(() => {})
      .finally(() => setLoadingDetail(false));
  }, [snapshot.id]);

  useEffect(() => {
    if (tab === 'DIFF') {
      setLoadingDiff(true);
      api.snapshotDiff(snapshot.id)
        .then(setDiff)
        .catch(() => setDiff(null))
        .finally(() => setLoadingDiff(false));
    }
  }, [tab, snapshot.id]);

  useEffect(() => {
    if (tab === 'SNAPSHOTS') {
      setLoadingSnaps(true);
      api.snapshots({ device_id: snapshot.device_id, limit: 50 })
        .then(setDeviceSnaps)
        .catch(() => setDeviceSnaps([]))
        .finally(() => setLoadingSnaps(false));
    }
  }, [tab, snapshot.device_id]);

  // Group diff changes by feature (first path segment)
  const groupedDiff = useMemo(() => {
    if (!diff?.changes) return {};
    const groups = {};
    for (const [path, change] of Object.entries(diff.changes)) {
      const feature = path.split('.')[0];
      if (!groups[feature]) groups[feature] = {};
      // Strip the feature prefix for display
      const subPath = path.split('.').slice(1).join('.');
      groups[feature][subPath] = change;
    }
    return groups;
  }, [diff]);

  const TABS = ['DATA', 'FEATURES', 'DIFF', 'SNAPSHOTS'];

  return (
    <div className="w-[480px] border-l border-outline/10 bg-surface-container-low shadow-[-4px_0_24px_rgba(0,0,0,0.04)] flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-5 pt-5 pb-4 border-b border-outline/10">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
            Snapshot Detail
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => onDelete && onDelete(snapshot.id)}
              className="p-1 rounded-lg hover:bg-error/10 transition-colors"
              title="Delete snapshot"
            >
              <Icon name="delete" className="text-lg text-error/60 hover:text-error" />
            </button>
            <button onClick={onClose} className="p-1 rounded-lg hover:bg-surface-container-high transition-colors">
              <Icon name="close" className="text-lg text-on-surface-variant" />
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="text-xl font-extrabold text-on-surface">{device?.hostname || 'Unknown'}</h2>
          {snapshot.is_golden && <GoldenBadge />}
        </div>
        <div className="flex items-center gap-3 mt-2">
          <span className="text-xs text-on-surface-variant">
            {new Date(snapshot.created_at).toLocaleString()}
          </span>
          <span className="text-xs text-on-surface-variant">&middot;</span>
          <span className="text-xs text-on-surface-variant">
            {formatDuration(snapshot.duration_seconds)}
          </span>
          <span className="text-xs text-on-surface-variant">&middot;</span>
          <span className="text-xs font-medium text-on-surface-variant capitalize">
            {snapshot.triggered_by}
          </span>
        </div>
        {/* Bless control — only show on non-golden snapshots */}
        {!snapshot.is_golden && onBless && (
          <button
            onClick={() => onBless(snapshot.id)}
            disabled={blessing}
            className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-bold border border-amber-500/30 text-amber-700 dark:text-amber-300 bg-amber-500/5 hover:bg-amber-500/10 transition-colors disabled:opacity-50"
            title="Promote this snapshot to be the device's baseline. Future diffs will compare against it."
          >
            <Icon name="bookmark_add" className="text-base" />
            {blessing ? 'Setting…' : 'Set as baseline'}
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex px-5 gap-5 border-b border-outline/10">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`py-3 text-xs font-bold transition-colors ${
              tab === t ? 'text-primary border-b-2 border-primary' : 'text-on-surface-variant hover:text-on-surface'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {tab === 'DATA' && (
          loadingDetail ? (
            <div className="flex items-center justify-center py-12">
              <div className="w-5 h-5 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
            </div>
          ) : detail?.snapshot_data ? (
            <div className="space-y-3">
              {Object.entries(detail.snapshot_data).map(([feature, data]) => {
                const isError = typeof data === 'object' && data?.error;
                const isString = typeof data === 'string';
                const size = JSON.stringify(data).length;
                return (
                  <details key={feature} className="group">
                    <summary className="flex items-center justify-between bg-surface-container-lowest rounded-lg px-4 py-3 cursor-pointer hover:bg-blue-50/30 transition-colors">
                      <div className="flex items-center gap-2.5">
                        <Icon
                          name={isError ? 'error_outline' : isString ? 'info' : 'check_circle'}
                          className={`text-base ${isError ? 'text-error' : isString ? 'text-on-surface-variant' : 'text-secondary'}`}
                        />
                        <span className="text-sm font-bold text-on-surface">{feature}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-on-surface-variant">
                          {isError ? 'error' : isString ? 'no data' : `${(size / 1024).toFixed(1)}KB`}
                        </span>
                        <Icon name="expand_more" className="text-base text-outline group-open:rotate-180 transition-transform" />
                      </div>
                    </summary>
                    <pre className="mt-2 bg-slate-900 rounded-lg p-3.5 font-mono text-[11px] text-slate-300 overflow-x-auto leading-relaxed max-h-64 overflow-y-auto">
                      {JSON.stringify(data, null, 2)}
                    </pre>
                  </details>
                );
              })}
            </div>
          ) : (
            <p className="text-sm text-on-surface-variant">No data available</p>
          )
        )}

        {tab === 'FEATURES' && (
          loadingDetail ? (
            <div className="flex items-center justify-center py-12">
              <div className="w-5 h-5 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
            </div>
          ) : detail?.snapshot_data ? (
            <div className="space-y-3">
              {Object.entries(detail.snapshot_data).map(([feature, data]) => {
                const isError = typeof data === 'object' && data?.error;
                const isString = typeof data === 'string';
                const stats = (!isError && !isString) ? featureSummary(feature, data) : null;
                const size = JSON.stringify(data).length;
                const icon = FEATURE_ICONS[feature] || 'data_object';

                return (
                  <div key={feature} className="bg-surface-container-lowest rounded-xl overflow-hidden">
                    <div className="flex items-center gap-3 px-4 py-3">
                      <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${
                        isError ? 'bg-error/10' : 'bg-primary/8'
                      }`}>
                        <Icon name={isError ? 'error_outline' : icon} className={`text-lg ${isError ? 'text-error' : 'text-primary'}`} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-bold text-on-surface capitalize">{feature}</span>
                          <span className="text-[10px] text-on-surface-variant">
                            {isError ? 'Error' : isString ? 'No data' : `${(size / 1024).toFixed(1)} KB`}
                          </span>
                        </div>
                      </div>
                      <StatusChip variant={isError ? 'error' : isString ? 'neutral' : 'success'} dot>
                        {isError ? 'FAILED' : isString ? 'EMPTY' : 'OK'}
                      </StatusChip>
                    </div>

                    {stats && (
                      <div className="px-4 pb-3 flex flex-wrap gap-x-5 gap-y-1.5 border-t border-outline/5 pt-2.5">
                        {stats.map((s) => (
                          <div key={s.label} className="flex items-center gap-1.5">
                            <span className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">{s.label}</span>
                            <span className="text-sm font-bold text-on-surface">{s.value}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="space-y-2">
              {(snapshot.features_learned || []).map((feat) => (
                <div key={feat} className="flex items-center gap-2.5 bg-surface-container-lowest rounded-lg px-4 py-3">
                  <Icon name="check_circle" className="text-base text-secondary" />
                  <span className="text-sm font-bold text-on-surface">{feat}</span>
                </div>
              ))}
            </div>
          )
        )}

        {tab === 'DIFF' && (
          loadingDiff ? (
            <div className="flex items-center justify-center py-12">
              <div className="w-5 h-5 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
            </div>
          ) : diff ? (
            diff.previous_snapshot_id ? (
              <div className="space-y-2">
                {(() => {
                  const entries = Object.values(diff.changes);
                  const added = entries.filter((c) => c.status === 'added').length;
                  const removed = entries.filter((c) => c.status === 'removed').length;
                  const changed = entries.filter((c) => c.status === 'changed').length;
                  return (
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <Icon name="compare_arrows" className="text-base text-primary" />
                        <span className="text-xs text-on-surface-variant">
                          vs {diff.previous_snapshot_id.slice(0, 8)}
                        </span>
                      </div>
                      <div className="flex items-center gap-3">
                        {added > 0 && <span className="text-[10px] font-bold text-emerald-400">+{added} added</span>}
                        {removed > 0 && <span className="text-[10px] font-bold text-red-400">-{removed} removed</span>}
                        {changed > 0 && <span className="text-[10px] font-bold text-amber-400">~{changed} changed</span>}
                      </div>
                    </div>
                  );
                })()}
                {Object.keys(groupedDiff).length === 0 ? (
                  <div className="flex flex-col items-center py-8 text-on-surface-variant">
                    <Icon name="check_circle" className="text-3xl mb-2 text-secondary opacity-60" />
                    <p className="text-xs font-semibold">No changes detected</p>
                  </div>
                ) : (
                  <div className="space-y-4 max-h-[calc(100vh-320px)] overflow-y-auto">
                    {Object.entries(groupedDiff).map(([feature, changes]) => {
                      const changeList = Object.entries(changes);
                      const addedCount = changeList.filter(([, c]) => c.status === 'added').length;
                      const removedCount = changeList.filter(([, c]) => c.status === 'removed').length;
                      const changedCount = changeList.filter(([, c]) => c.status === 'changed').length;
                      const icon = FEATURE_ICONS[feature] || 'data_object';

                      return (
                        <details key={feature} className="group">
                          <summary className="flex items-center gap-2.5 px-3 py-2.5 bg-surface-container-lowest rounded-lg cursor-pointer hover:bg-blue-50/30 transition-colors">
                            <Icon name={icon} className="text-base text-primary" />
                            <span className="text-sm font-bold text-on-surface capitalize flex-1">{feature}</span>
                            <div className="flex items-center gap-2">
                              {addedCount > 0 && <span className="text-[9px] font-bold text-emerald-400">+{addedCount}</span>}
                              {removedCount > 0 && <span className="text-[9px] font-bold text-red-400">-{removedCount}</span>}
                              {changedCount > 0 && <span className="text-[9px] font-bold text-amber-400">~{changedCount}</span>}
                              <Icon name="expand_more" className="text-sm text-outline group-open:rotate-180 transition-transform" />
                            </div>
                          </summary>
                          <div className="mt-1.5 space-y-1.5 pl-1">
                            {changeList.map(([path, change]) => (
                              <DiffEntry key={path} path={path} change={change} />
                            ))}
                          </div>
                        </details>
                      );
                    })}
                  </div>
                )}
              </div>
            ) : (
              <div className="flex flex-col items-center py-8 text-on-surface-variant">
                <Icon name="history" className="text-3xl mb-2 opacity-40" />
                <p className="text-xs font-semibold">No previous snapshot</p>
                <p className="text-[10px] mt-1 opacity-60">Take another snapshot to see changes</p>
              </div>
            )
          ) : (
            <p className="text-sm text-on-surface-variant">Failed to load diff</p>
          )
        )}

        {tab === 'SNAPSHOTS' && (
          loadingSnaps ? (
            <div className="flex items-center justify-center py-12">
              <div className="w-5 h-5 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
            </div>
          ) : deviceSnaps.length > 0 ? (
            <div className="space-y-2">
              <p className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant mb-3">
                {deviceSnaps.length} snapshot{deviceSnaps.length !== 1 ? 's' : ''} for {device?.hostname || 'this device'}
              </p>
              {deviceSnaps.map((s) => {
                const isCurrent = s.id === snapshot.id;
                const hasError = !s.features_learned?.length;
                return (
                  <button
                    key={s.id}
                    onClick={() => onSelectSnapshot && onSelectSnapshot(s)}
                    className={`w-full text-left flex items-center gap-3 rounded-lg px-4 py-3 transition-colors ${
                      isCurrent
                        ? 'bg-primary/8 border border-primary/20'
                        : 'bg-surface-container-lowest hover:bg-blue-50/30'
                    }`}
                  >
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
                      hasError ? 'bg-error/10' : isCurrent ? 'bg-primary/10' : 'bg-secondary/10'
                    }`}>
                      <Icon
                        name={hasError ? 'error_outline' : 'camera'}
                        className={`text-base ${hasError ? 'text-error' : isCurrent ? 'text-primary' : 'text-secondary'}`}
                      />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={`text-xs font-bold ${isCurrent ? 'text-primary' : 'text-on-surface'}`}>
                          {new Date(s.created_at).toLocaleString()}
                        </span>
                        {isCurrent && (
                          <span className="text-[9px] font-bold text-primary bg-primary/10 px-1.5 py-0.5 rounded-full">
                            CURRENT
                          </span>
                        )}
                        {s.is_golden && <GoldenBadge small />}
                      </div>
                      <div className="flex items-center gap-3 mt-0.5">
                        <span className="text-[10px] text-on-surface-variant">
                          {s.features_learned?.length || 0} features
                        </span>
                        <span className="text-[10px] text-on-surface-variant">
                          {formatDuration(s.duration_seconds)}
                        </span>
                        <span className="text-[10px] text-on-surface-variant capitalize">
                          {s.triggered_by}
                        </span>
                      </div>
                    </div>
                    <StatusChip variant={hasError ? 'error' : 'success'} dot>
                      {hasError ? 'FAIL' : 'OK'}
                    </StatusChip>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="flex flex-col items-center py-8 text-on-surface-variant">
              <Icon name="camera" className="text-3xl mb-2 opacity-40" />
              <p className="text-xs font-semibold">No snapshots found</p>
            </div>
          )
        )}
      </div>
    </div>
  );
}

export default function Snapshots() {
  const [snapshots, setSnapshots] = useState([]);
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [triggerDevice, setTriggerDevice] = useState('');
  const [filterDevice, setFilterDevice] = useState('');
  const { status: snapStatus, triggerSnapshot, refresh: refreshSnapStatus } = useSnapshotStatus();
  const wasRunning = useRef(false);
  const dialog = useDialog();

  const fetchData = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([api.snapshots(), api.devices()])
      .then(([snaps, devs]) => {
        setSnapshots(snaps);
        setDevices(devs);
      })
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Auto-refresh table when a snapshot run finishes
  useEffect(() => {
    if (snapStatus?.running) {
      wasRunning.current = true;
    } else if (wasRunning.current) {
      wasRunning.current = false;
      fetchData();
    }
  }, [snapStatus?.running]);

  // Snapshot count per device
  const snapCounts = useMemo(() => {
    const counts = {};
    for (const s of snapshots) {
      counts[s.device_id] = (counts[s.device_id] || 0) + 1;
    }
    return counts;
  }, [snapshots]);

  const [deleting, setDeleting] = useState(false);
  const [blessing, setBlessing] = useState(false);

  const handleBless = async (id) => {
    setBlessing(true);
    try {
      await api.blessSnapshot(id);
      // Re-fetch so the new baseline is reflected immediately; also
      // update the selected snapshot view in-place.
      const fresh = await api.snapshots();
      setSnapshots(fresh);
      const updated = fresh.find((s) => s.id === id);
      if (updated) setSelected(updated);
    } catch (e) {
      setError(e);
    } finally {
      setBlessing(false);
    }
  };

  const handleTrigger = async () => {
    try {
      await triggerSnapshot(triggerDevice || undefined);
      setTriggerDevice('');
    } catch (e) {
      setError(e);
    }
  };

  const handleDeleteSnapshot = async (id) => {
    setDeleting(true);
    try {
      await api.deleteSnapshot(id);
      if (selected?.id === id) setSelected(null);
      fetchData();
    } catch (e) {
      setError(e);
    } finally {
      setDeleting(false);
    }
  };

  const handleDeleteAll = async () => {
    const ok = await dialog.confirm({
      title: 'Delete all snapshots?',
      message: `${snapshots.length} snapshot${snapshots.length === 1 ? '' : 's'} and every linked finding, recommendation, and approval will be permanently removed. This cannot be undone.`,
      confirmLabel: 'Delete all',
      variant: 'danger',
    });
    if (!ok) return;
    setDeleting(true);
    try {
      await api.deleteAllSnapshots();
      setSelected(null);
      setSelectedIds(new Set());
      fetchData();
    } catch (e) {
      setError(e);
    } finally {
      setDeleting(false);
    }
  };

  const filtered = filterDevice
    ? snapshots.filter((s) => s.device_id === filterDevice)
    : snapshots;

  const toggleCheck = useCallback((id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const filteredIds = useMemo(() => filtered.map((s) => s.id), [filtered]);
  const allFilteredChecked = filteredIds.length > 0 && filteredIds.every((id) => selectedIds.has(id));
  const someFilteredChecked = filteredIds.some((id) => selectedIds.has(id));

  const toggleSelectAll = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allFilteredChecked) {
        filteredIds.forEach((id) => next.delete(id));
      } else {
        filteredIds.forEach((id) => next.add(id));
      }
      return next;
    });
  };

  const handleDeleteSelected = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    const ok = await dialog.confirm({
      title: `Delete ${ids.length} snapshot${ids.length === 1 ? '' : 's'}?`,
      message: 'Linked findings, recommendations, and approvals will also be removed. This cannot be undone.',
      confirmLabel: 'Delete',
      variant: 'danger',
    });
    if (!ok) return;
    setDeleting(true);
    try {
      await api.deleteSnapshots(ids);
      if (selected && ids.includes(selected.id)) setSelected(null);
      setSelectedIds(new Set());
      fetchData();
    } catch (e) {
      setError(e);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="flex h-full overflow-hidden">
      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 p-6 overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-extrabold text-on-surface">Snapshots</h1>
            <span className="flex items-center justify-center min-w-[28px] h-7 px-2 bg-surface-container-high rounded-full text-xs font-bold text-on-surface-variant">
              {filtered.length}
            </span>
          </div>

          <div className="flex items-center gap-3">
            {/* Device filter */}
            <select
              value={filterDevice}
              onChange={(e) => setFilterDevice(e.target.value)}
              className="px-3 py-2 rounded-lg border border-outline/20 text-xs font-bold text-on-surface-variant bg-surface-container-lowest focus:outline-none focus:ring-2 focus:ring-primary/30"
            >
              <option value="">All Devices</option>
              {devices.map((d) => (
                <option key={d.id} value={d.id}>{d.hostname} ({snapCounts[d.id] || 0})</option>
              ))}
            </select>

            {/* Trigger snapshot */}
            <div className="flex items-center gap-2">
              <select
                value={triggerDevice}
                onChange={(e) => setTriggerDevice(e.target.value)}
                className="px-3 py-2 rounded-lg border border-outline/20 text-xs font-bold text-on-surface-variant bg-surface-container-lowest focus:outline-none focus:ring-2 focus:ring-primary/30"
              >
                <option value="">All Devices</option>
                {devices.map((d) => (
                  <option key={d.id} value={d.id}>{d.hostname}</option>
                ))}
              </select>
              <button
                onClick={handleTrigger}
                disabled={snapStatus?.running}
                className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold transition-colors ${
                  snapStatus?.running
                    ? 'bg-tertiary/10 text-tertiary cursor-not-allowed'
                    : 'bg-primary text-white hover:bg-primary/90'
                }`}
              >
                {snapStatus?.running ? (
                  <>
                    <div className="w-3.5 h-3.5 border-2 border-tertiary/30 border-t-tertiary rounded-full animate-spin" />
                    {snapStatus.devices_done != null && snapStatus.devices_total
                      ? `${snapStatus.devices_done}/${snapStatus.devices_total} complete`
                      : 'Starting...'}
                  </>
                ) : (
                  <>
                    <Icon name="play_arrow" className="text-base" />
                    Take Snapshot
                  </>
                )}
              </button>
            </div>
            {snapshots.length > 0 && (
              <button
                onClick={handleDeleteAll}
                disabled={deleting}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold border border-error/30 text-error bg-error/5 hover:bg-error/10 transition-colors disabled:opacity-50"
              >
                <Icon name="delete_sweep" className="text-base" />
                Delete All
              </button>
            )}
          </div>
        </div>

        {/* Bulk-action bar */}
        {selectedIds.size > 0 && (
          <div className="flex items-center justify-between bg-primary/5 border border-primary/20 rounded-xl px-5 py-3 mb-4">
            <div className="flex items-center gap-3">
              <Icon name="check_box" className="text-primary" />
              <span className="text-sm font-bold text-primary">
                {selectedIds.size} snapshot{selectedIds.size === 1 ? '' : 's'} selected
              </span>
              <button
                onClick={() => setSelectedIds(new Set())}
                className="text-xs font-bold text-on-surface-variant hover:text-on-surface transition-colors"
              >
                Clear
              </button>
            </div>
            <button
              onClick={handleDeleteSelected}
              disabled={deleting}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold bg-error text-white hover:bg-error/90 transition-colors disabled:opacity-50"
            >
              <Icon name="delete" className="text-base" />
              Delete Selected
            </button>
          </div>
        )}

        {/* Running progress banner */}
        {snapStatus?.running && (
          <div className="flex items-center gap-3 rounded-xl px-5 py-3.5 bg-primary/5 border border-primary/20 mb-5">
            <div className="w-5 h-5 border-2 border-primary/30 border-t-primary rounded-full animate-spin shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-bold text-primary">
                {snapStatus.devices_done != null && snapStatus.devices_total
                  ? `${snapStatus.devices_done}/${snapStatus.devices_total} snapshots complete`
                  : 'Snapshot starting...'}
              </p>
              {snapStatus.current_device && (
                <p className="text-[10px] text-on-surface-variant">
                  Currently snapshotting {snapStatus.current_device}
                </p>
              )}
            </div>
          </div>
        )}

        {/* Stats cards */}
        {!loading && snapshots.length > 0 && (
          <div className="grid grid-cols-5 gap-4 mb-5">
            {[
              {
                label: 'Total Snapshots',
                value: snapshots.length,
                icon: 'camera',
                color: 'text-primary',
                bg: 'bg-primary/10',
              },
              {
                label: 'Devices Captured',
                value: new Set(snapshots.map((s) => s.device_id)).size,
                icon: 'router',
                color: 'text-secondary',
                bg: 'bg-secondary/10',
              },
              {
                label: 'Baselines',
                value: snapshots.filter((s) => s.is_golden).length,
                icon: 'bookmark_star',
                color: 'text-amber-700 dark:text-amber-300',
                bg: 'bg-amber-500/10',
              },
              {
                label: 'Latest',
                value: snapshots.length > 0 ? timeAgo(snapshots[0].created_at) : '--',
                icon: 'schedule',
                color: 'text-tertiary',
                bg: 'bg-tertiary/10',
              },
              {
                label: 'Failed',
                value: snapshots.filter((s) => !s.features_learned?.length).length,
                icon: 'error_outline',
                color: 'text-error',
                bg: 'bg-error/10',
              },
            ].map((stat) => (
              <div key={stat.label} className="bg-surface-container-lowest rounded-xl px-5 py-4 flex items-center gap-4">
                <div className={`w-10 h-10 rounded-lg ${stat.bg} flex items-center justify-center`}>
                  <Icon name={stat.icon} className={`text-xl ${stat.color}`} />
                </div>
                <div>
                  <div className="text-lg font-extrabold text-on-surface">{stat.value}</div>
                  <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">{stat.label}</div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="flex items-center gap-3 bg-error/5 border border-error/20 rounded-xl px-5 py-4 mb-4">
            <Icon name="error" className="text-xl text-error" />
            <div>
              <p className="text-sm font-bold text-error">Error</p>
              <p className="text-xs text-on-surface-variant mt-0.5">{error.message}</p>
            </div>
            <button onClick={fetchData} className="ml-auto px-3 py-1.5 rounded-lg bg-error/10 text-error text-xs font-bold hover:bg-error/15 transition-colors">
              Retry
            </button>
          </div>
        )}

        {/* Table */}
        {!loading && !error && (
          <div className="bg-surface-container-lowest rounded-xl overflow-hidden">
            {/* Header */}
            <div className="grid grid-cols-[32px_2fr_0.6fr_1.2fr_1fr_1fr_1fr_32px] gap-3 px-5 py-3 bg-surface-container-low border-b border-outline/10">
              <div className="flex items-center">
                <input
                  type="checkbox"
                  checked={allFilteredChecked}
                  ref={(el) => { if (el) el.indeterminate = !allFilteredChecked && someFilteredChecked; }}
                  onChange={toggleSelectAll}
                  disabled={filteredIds.length === 0}
                  className="w-4 h-4 accent-primary cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
                  aria-label="Select all visible snapshots"
                />
              </div>
              {['Device', 'Snaps', 'Taken', 'Features', 'Duration', 'Status'].map((h) => (
                <span key={h} className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
                  {h}
                </span>
              ))}
              <span />
            </div>

            {filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-on-surface-variant">
                <Icon name="camera" className="text-4xl mb-3 opacity-40" />
                <p className="text-sm font-semibold">No snapshots yet</p>
                <p className="text-xs mt-1 opacity-60">Take your first snapshot to see device state</p>
              </div>
            ) : (
              <div className="divide-y divide-outline/5">
                {filtered.map((snap) => (
                  <SnapshotRow
                    key={snap.id}
                    snapshot={snap}
                    devices={devices}
                    snapCount={snapCounts[snap.device_id] || 1}
                    isSelected={selected?.id === snap.id}
                    onSelect={setSelected}
                    isChecked={selectedIds.has(snap.id)}
                    onToggleCheck={toggleCheck}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Detail panel */}
      {selected && (
        <SnapshotDetail
          snapshot={selected}
          devices={devices}
          onClose={() => setSelected(null)}
          onSelectSnapshot={setSelected}
          onDelete={handleDeleteSnapshot}
          onBless={handleBless}
          blessing={blessing}
        />
      )}
    </div>
  );
}
