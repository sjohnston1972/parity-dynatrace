import { useState, useEffect, useCallback } from 'react';
import { useApi } from '../hooks/useApi';
import { api } from '../api/client';
import Icon from '../components/Icon';
import StatusChip from '../components/StatusChip';

const FILTERS = ['ALL', 'ACTIVE', 'ISSUES'];

const TABS = ['CONFIG', 'INTERFACES', 'HEALTH'];

function getComplianceInfo(device) {
  const tags = device.tags || {};
  if (tags.compliance === 'critical') {
    return { label: 'Critical', color: 'error', pct: 25 };
  }
  if (tags.compliance === 'vulnerable') {
    return { label: 'Vulnerable', color: 'tertiary-container', pct: 60 };
  }
  return { label: 'Compliant', color: 'secondary', pct: 100 };
}

function getDeviceStatus(device) {
  // last_seen reflects the most recent telemetry point Telegraf saw for this
  // specific device — that's real liveness. last_refreshed is just when we
  // last synced the inventory list, so it's a fallback only.
  const ts = device.last_seen || device.last_refreshed;
  if (!ts) return 'OFFLINE';
  const diff = Date.now() - new Date(ts).getTime();
  return diff < 24 * 60 * 60 * 1000 ? 'ONLINE' : 'OFFLINE';
}

function filterDevices(devices, filter) {
  if (filter === 'ALL') return devices;
  if (filter === 'ACTIVE') return devices.filter((d) => getDeviceStatus(d) === 'ONLINE');
  if (filter === 'ISSUES') {
    return devices.filter((d) => {
      const c = getComplianceInfo(d);
      return c.label === 'Critical' || c.label === 'Vulnerable';
    });
  }
  return devices;
}

function DeviceTable({ devices, selectedDevice, onSelect }) {
  return (
    <div className="bg-surface-container-lowest rounded-xl overflow-hidden">
      {/* Table header */}
      <div className="grid grid-cols-[2fr_1fr_1fr_1.2fr_1fr_1.2fr_32px] gap-3 px-5 py-3 bg-surface-container-low border-b border-outline/10">
        {['Hostname', 'Status', 'Role', 'IP Address', 'Software', 'Compliance'].map((h) => (
          <span key={h} className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
            {h}
          </span>
        ))}
        <span />
      </div>

      {/* Table rows */}
      {devices.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-on-surface-variant">
          <Icon name="dns" className="text-4xl mb-3 opacity-40" />
          <p className="text-sm font-semibold">No devices found</p>
          <p className="text-xs mt-1 opacity-60">Add a device or refresh inventory from Grafana</p>
        </div>
      ) : (
        <div className="divide-y divide-outline/5">
          {devices.map((device) => {
            const isSelected = selectedDevice?.id === device.id;
            const status = getDeviceStatus(device);
            const compliance = getComplianceInfo(device);
            return (
              <div
                key={device.id}
                onClick={() => onSelect(device)}
                className={`grid grid-cols-[2fr_1fr_1fr_1.2fr_1fr_1.2fr_32px] gap-3 px-5 py-3.5 cursor-pointer transition-colors ${
                  isSelected ? 'bg-primary/5' : 'hover:bg-blue-50/30'
                }`}
              >
                {/* Hostname */}
                <div className="flex flex-col justify-center min-w-0">
                  <span className={`text-sm font-bold truncate ${isSelected ? 'text-primary' : 'text-on-surface'}`}>
                    {device.hostname}
                  </span>
                  <span className="text-[11px] text-on-surface-variant truncate">
                    {device.tags?.model || device.platform || '--'}
                  </span>
                </div>

                {/* Status */}
                <div className="flex items-center">
                  <StatusChip
                    variant={status === 'ONLINE' ? 'success' : 'error'}
                    dot
                    pulse={status === 'ONLINE'}
                  >
                    {status}
                  </StatusChip>
                </div>

                {/* Role */}
                <div className="flex items-center">
                  <span className="text-xs text-on-surface capitalize">{device.device_type || '--'}</span>
                </div>

                {/* IP Address */}
                <div className="flex items-center">
                  <span className="text-xs text-on-surface font-mono">{device.management_ip || '--'}</span>
                </div>

                {/* Software */}
                <div className="flex items-center">
                  <span className="text-xs text-on-surface">{device.platform || '--'}</span>
                </div>

                {/* Compliance */}
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-1.5 bg-outline/10 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        compliance.color === 'secondary'
                          ? 'bg-secondary'
                          : compliance.color === 'error'
                          ? 'bg-error'
                          : 'bg-tertiary'
                      }`}
                      style={{ width: `${compliance.pct}%` }}
                    />
                  </div>
                  <span
                    className={`text-[10px] font-bold whitespace-nowrap ${
                      compliance.color === 'secondary'
                        ? 'text-secondary'
                        : compliance.color === 'error'
                        ? 'text-error'
                        : 'text-tertiary'
                    }`}
                  >
                    {compliance.label}
                  </span>
                </div>

                {/* Chevron */}
                <div className="flex items-center justify-end">
                  <Icon name="chevron_right" className="text-base text-outline" />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function extractPlatformMetrics(snapData) {
  if (!snapData) return [];
  const metrics = [];
  const platform = snapData.platform || {};
  if (platform.uptime) metrics.push({ label: 'Uptime', value: platform.uptime, icon: 'schedule' });
  if (platform.chassis) metrics.push({ label: 'Chassis', value: platform.chassis, icon: 'developer_board' });
  if (platform.os || platform.software_version)
    metrics.push({ label: 'Software', value: platform.os || platform.software_version, icon: 'system_update' });

  // Interface error totals
  const intfs = snapData.interface || {};
  let totalInErr = 0, totalOutErr = 0;
  for (const d of Object.values(intfs)) {
    if (!d || typeof d !== 'object') continue;
    const c = d.counters || {};
    totalInErr += c.in_errors || 0;
    totalOutErr += c.out_errors || 0;
  }
  metrics.push({ label: 'In Errors', value: String(totalInErr), icon: 'error_outline' });
  metrics.push({ label: 'Out Errors', value: String(totalOutErr), icon: 'warning' });

  return metrics;
}

function extractInterfaces(snapData) {
  if (!snapData?.interface) return [];
  const intfs = snapData.interface;
  return Object.entries(intfs)
    .filter(([, d]) => d && typeof d === 'object')
    .map(([name, d]) => {
      const ipv4 = d.ipv4 || {};
      const ips = typeof ipv4 === 'object' ? Object.keys(ipv4) : [];
      const counters = d.counters || {};
      return {
        name,
        oper_status: d.oper_status || 'unknown',
        admin_status: d.enabled !== undefined ? (d.enabled ? 'up' : 'down') : (d.admin_state || 'unknown'),
        ips,
        in_errors: counters.in_errors || 0,
        out_errors: counters.out_errors || 0,
        in_discards: counters.in_discards || 0,
        in_octets: counters.in_octets || 0,
        out_octets: counters.out_octets || 0,
        bandwidth: d.bandwidth || null,
        mtu: d.mtu || null,
        type: d.type || '',
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name));
}

function extractHealthData(snapData) {
  if (!snapData) return null;
  const health = {};

  // BGP neighbors
  const bgp = snapData.bgp || {};
  const bgpNeighbors = [];
  for (const inst of Object.values(bgp.instance || {})) {
    if (!inst || typeof inst !== 'object') continue;
    for (const [vrfName, vrf] of Object.entries(inst.vrf || {})) {
      if (!vrf || typeof vrf !== 'object') continue;
      for (const [ip, ndata] of Object.entries(vrf.neighbor || {})) {
        if (!ndata || typeof ndata !== 'object') continue;
        bgpNeighbors.push({
          ip,
          vrf: vrfName,
          remote_as: ndata.remote_as || '?',
          state: ndata.session_state || 'Unknown',
        });
      }
    }
  }
  health.bgp = bgpNeighbors;

  // OSPF neighbors
  const ospf = snapData.ospf || {};
  const ospfAreas = [];
  for (const [key, inst] of Object.entries(ospf)) {
    if (!inst || typeof inst !== 'object') continue;
    const areas = inst.areas || {};
    for (const [areaId, area] of Object.entries(areas)) {
      if (!area || typeof area !== 'object') continue;
      const intfNames = Object.keys(area.interfaces || {});
      if (intfNames.length) ospfAreas.push({ area: areaId, interfaces: intfNames });
    }
  }
  health.ospf = ospfAreas;

  // Interface summary
  const intfs = snapData.interface || {};
  let up = 0, down = 0, total = 0;
  for (const d of Object.values(intfs)) {
    if (!d || typeof d !== 'object') continue;
    total++;
    if (d.oper_status === 'up') up++;
    else down++;
  }
  health.interfaces = { up, down, total };

  // Routing
  const routing = snapData.routing || {};
  let routeCount = 0;
  for (const vrf of Object.values(routing.vrf || {})) {
    if (!vrf || typeof vrf !== 'object') continue;
    for (const af of Object.values(vrf.address_family || {})) {
      if (!af || typeof af !== 'object') continue;
      routeCount += Object.keys(af.routes || {}).length;
    }
  }
  health.routes = routeCount;

  // VLANs
  const vlan = snapData.vlan || {};
  const vlans = vlan.vlans || {};
  health.vlans = Object.keys(vlans).length;

  // ARP
  const arp = snapData.arp || {};
  let arpCount = 0;
  for (const iface of Object.values(arp.interfaces || {})) {
    if (!iface || typeof iface !== 'object') continue;
    arpCount += Object.keys(iface.ipv4?.neighbors || {}).length;
  }
  health.arp = arpCount;

  return health;
}

function DetailPanel({ device, onClose }) {
  const [activeTab, setActiveTab] = useState('CONFIG');
  const [copied, setCopied] = useState(false);
  const [snapshot, setSnapshot] = useState(null);
  const [snapLoading, setSnapLoading] = useState(true);
  const [unmonitored, setUnmonitored] = useState([]);
  const status = getDeviceStatus(device);
  const compliance = getComplianceInfo(device);

  useEffect(() => {
    let cancelled = false;
    setSnapLoading(true);
    setSnapshot(null);
    setUnmonitored([]);

    Promise.all([
      api.deviceSnapshot(device.id).catch(() => null),
      api.deviceUnmonitored(device.id).catch(() => ({ interfaces: [] })),
    ]).then(([snap, um]) => {
      if (cancelled) return;
      setSnapshot(snap);
      setUnmonitored(um?.interfaces || []);
      setSnapLoading(false);
    });

    return () => { cancelled = true; };
  }, [device.id]);

  const snapData = snapshot?.snapshot_data || null;
  const interfaces = extractInterfaces(snapData);
  const platformMetrics = extractPlatformMetrics(snapData);
  const healthData = extractHealthData(snapData);

  const toggleUnmonitored = useCallback(
    (intfName) => {
      const next = unmonitored.includes(intfName)
        ? unmonitored.filter((n) => n !== intfName)
        : [...unmonitored, intfName];
      setUnmonitored(next);
      api.setDeviceUnmonitored(device.id, next).catch(() => {});
    },
    [device.id, unmonitored]
  );

  const configText = snapData
    ? `Features learned: ${(snapshot.features_learned || []).join(', ')}\nSnapshot taken: ${snapshot.created_at}\n\n` +
      (snapData.config?.running_config || 'No running config captured in snapshot.\nUse Python learn(\'config\') to capture.')
    : null;

  const handleCopy = () => {
    if (!configText) return;
    navigator.clipboard.writeText(configText).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="w-96 border-l border-outline/10 bg-surface-container-low shadow-[-4px_0_24px_rgba(0,0,0,0.04)] flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-5 pt-5 pb-4 border-b border-outline/10">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
            {device.device_type || 'Device'}
          </span>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-surface-container-high transition-colors"
          >
            <Icon name="close" className="text-lg text-on-surface-variant" />
          </button>
        </div>
        <h2 className="text-xl font-extrabold text-on-surface">{device.hostname}</h2>
        <div className="flex items-center gap-2 mt-1.5">
          <span
            className={`w-2 h-2 rounded-full ${
              status === 'ONLINE' ? 'bg-secondary animate-pulse' : 'bg-error'
            }`}
          />
          <span className="text-xs text-on-surface-variant">
            {device.tags?.model || device.platform || '--'} &middot; {device.management_ip}
          </span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex px-5 gap-5 border-b border-outline/10">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`py-3 text-xs font-bold transition-colors ${
              activeTab === tab
                ? 'text-primary border-b-2 border-primary'
                : 'text-on-surface-variant hover:text-on-surface'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {snapLoading && (
          <div className="flex items-center justify-center py-12">
            <div className="w-5 h-5 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
          </div>
        )}

        {!snapLoading && !snapData && (
          <div className="flex flex-col items-center justify-center py-12 text-on-surface-variant">
            <Icon name="cloud_off" className="text-3xl mb-2 opacity-40" />
            <p className="text-xs font-semibold">No snapshot data</p>
            <p className="text-[10px] mt-1 opacity-60">Trigger a snapshot to collect data</p>
          </div>
        )}

        {!snapLoading && snapData && activeTab === 'CONFIG' && (
          <>
            {/* Running Config / Snapshot info */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
                  {snapData.config?.running_config ? 'Running Config' : 'Snapshot Info'}
                </span>
                <button
                  onClick={handleCopy}
                  className="flex items-center gap-1 text-[10px] font-bold text-primary hover:text-primary/80 transition-colors"
                >
                  <Icon name={copied ? 'check' : 'content_copy'} className="text-sm" />
                  {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
              <pre className="bg-slate-900 rounded-lg p-3.5 font-mono text-[11px] text-slate-300 overflow-x-auto leading-relaxed max-h-48 overflow-y-auto">
                {configText}
              </pre>
            </div>

            {/* Quick Metrics from snapshot */}
            <div>
              <span className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
                Quick Metrics
              </span>
              <div className="grid grid-cols-2 gap-2 mt-2">
                {platformMetrics.length > 0 ? (
                  platformMetrics.map((m) => (
                    <div
                      key={m.label}
                      className="flex items-center gap-2.5 bg-surface-container-lowest rounded-lg px-3 py-2.5"
                    >
                      <Icon name={m.icon} className="text-base text-on-surface-variant" />
                      <div>
                        <div className="text-xs font-bold text-on-surface truncate max-w-[120px]">{m.value}</div>
                        <div className="text-[10px] text-on-surface-variant">{m.label}</div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="col-span-2 text-[10px] text-on-surface-variant">No platform data in snapshot</div>
                )}
              </div>
            </div>

            {/* Compliance banner */}
            <div className="flex items-center gap-3 bg-secondary/5 rounded-lg px-4 py-3">
              <Icon name="verified_user" className="text-xl text-secondary" fill />
              <div>
                <div className="text-xs font-bold text-on-surface">{compliance.label}</div>
                <div className="text-[10px] text-on-surface-variant">
                  Snapshot: {new Date(snapshot.created_at).toLocaleString()}
                </div>
              </div>
            </div>
          </>
        )}

        {!snapLoading && snapData && activeTab === 'INTERFACES' && (
          <div className="space-y-2">
            {interfaces.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-on-surface-variant">
                <Icon name="lan" className="text-3xl mb-2 opacity-40" />
                <p className="text-xs font-semibold">No interface data</p>
              </div>
            ) : (
              interfaces.map((intf) => {
                const isUnmonitored = unmonitored.includes(intf.name);
                const isUp = intf.oper_status === 'up';
                return (
                  <div
                    key={intf.name}
                    className={`bg-surface-container-lowest rounded-lg px-4 py-3 ${isUnmonitored ? 'opacity-50' : ''}`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <Icon name="lan" className="text-base text-on-surface-variant shrink-0" />
                        <div className="min-w-0">
                          <div className="text-xs font-bold text-on-surface truncate">{intf.name}</div>
                          <div className="text-[10px] text-on-surface-variant truncate">
                            {intf.ips.length > 0 ? intf.ips.join(', ') : 'No IP'}
                            {intf.mtu ? ` · MTU ${intf.mtu}` : ''}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <StatusChip
                          variant={isUp ? 'success' : 'error'}
                          dot
                        >
                          {isUp ? 'UP' : 'DOWN'}
                        </StatusChip>
                      </div>
                    </div>
                    {/* Error counters if non-zero */}
                    {(intf.in_errors > 0 || intf.out_errors > 0 || intf.in_discards > 0) && (
                      <div className="flex gap-3 mt-1.5 ml-[30px]">
                        {intf.in_errors > 0 && (
                          <span className="text-[10px] text-error font-bold">In Err: {intf.in_errors}</span>
                        )}
                        {intf.out_errors > 0 && (
                          <span className="text-[10px] text-error font-bold">Out Err: {intf.out_errors}</span>
                        )}
                        {intf.in_discards > 0 && (
                          <span className="text-[10px] text-tertiary font-bold">Discards: {intf.in_discards}</span>
                        )}
                      </div>
                    )}
                    {/* Unmonitored toggle */}
                    <div className="flex items-center gap-1.5 mt-1.5 ml-[30px]">
                      <button
                        onClick={() => toggleUnmonitored(intf.name)}
                        className={`text-[10px] font-bold transition-colors ${
                          isUnmonitored
                            ? 'text-primary hover:text-primary/80'
                            : 'text-on-surface-variant hover:text-error'
                        }`}
                      >
                        {isUnmonitored ? 'Enable monitoring' : 'Mark unmonitored'}
                      </button>
                      {isUnmonitored && (
                        <span className="text-[10px] text-on-surface-variant italic">unmonitored</span>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}

        {!snapLoading && snapData && activeTab === 'HEALTH' && healthData && (
          <div className="space-y-4">
            {/* Interface summary */}
            <div>
              <span className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
                Interfaces
              </span>
              <div className="flex items-center gap-3 mt-2 bg-surface-container-lowest rounded-lg px-4 py-3">
                <div className="flex-1">
                  <div className="flex items-center gap-2 text-sm font-bold text-on-surface">
                    <span className="text-secondary">{healthData.interfaces.up} up</span>
                    <span className="text-on-surface-variant">/</span>
                    <span className="text-error">{healthData.interfaces.down} down</span>
                    <span className="text-on-surface-variant">/</span>
                    <span>{healthData.interfaces.total} total</span>
                  </div>
                  <div className="w-full h-1.5 bg-outline/10 rounded-full mt-2 overflow-hidden">
                    <div
                      className="h-full bg-secondary rounded-full"
                      style={{
                        width: `${healthData.interfaces.total ? (healthData.interfaces.up / healthData.interfaces.total) * 100 : 0}%`,
                      }}
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* BGP Neighbors */}
            {healthData.bgp.length > 0 && (
              <div>
                <span className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
                  BGP Neighbors
                </span>
                <div className="space-y-1.5 mt-2">
                  {healthData.bgp.map((n) => (
                    <div key={n.ip} className="flex items-center justify-between bg-surface-container-lowest rounded-lg px-4 py-2.5">
                      <div>
                        <div className="text-xs font-bold text-on-surface font-mono">{n.ip}</div>
                        <div className="text-[10px] text-on-surface-variant">AS{n.remote_as} · {n.vrf}</div>
                      </div>
                      <StatusChip
                        variant={n.state.toLowerCase() === 'established' ? 'success' : 'error'}
                        dot
                      >
                        {n.state}
                      </StatusChip>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* OSPF Areas */}
            {healthData.ospf.length > 0 && (
              <div>
                <span className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
                  OSPF Areas
                </span>
                <div className="space-y-1.5 mt-2">
                  {healthData.ospf.map((a) => (
                    <div key={a.area} className="bg-surface-container-lowest rounded-lg px-4 py-2.5">
                      <div className="text-xs font-bold text-on-surface">Area {a.area}</div>
                      <div className="text-[10px] text-on-surface-variant">{a.interfaces.join(', ')}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Quick stats */}
            <div>
              <span className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
                Summary
              </span>
              <div className="grid grid-cols-3 gap-2 mt-2">
                {[
                  { label: 'Routes', value: healthData.routes, icon: 'alt_route' },
                  { label: 'VLANs', value: healthData.vlans, icon: 'account_tree' },
                  { label: 'ARP', value: healthData.arp, icon: 'hub' },
                ].map((m) => (
                  <div key={m.label} className="flex flex-col items-center bg-surface-container-lowest rounded-lg px-3 py-2.5">
                    <Icon name={m.icon} className="text-lg text-on-surface-variant" />
                    <div className="text-sm font-bold text-on-surface mt-1">{m.value}</div>
                    <div className="text-[10px] text-on-surface-variant">{m.label}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Footer buttons */}
      <div className="px-5 py-4 border-t border-outline/10 flex gap-2">
        <button className="flex-1 flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-lg bg-secondary/10 text-secondary text-xs font-bold hover:bg-secondary/15 transition-colors">
          <Icon name="camera" className="text-base" />
          SNAPSHOT
        </button>
        <button className="flex-1 flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-lg bg-primary text-white text-xs font-bold hover:bg-primary/90 transition-colors">
          <Icon name="terminal" className="text-base" />
          SSH
        </button>
      </div>
    </div>
  );
}

export default function Devices() {
  const { data: devices, loading, error, refetch } = useApi(api.devices);
  const [selectedDevice, setSelectedDevice] = useState(null);
  const [activeFilter, setActiveFilter] = useState('ALL');

  const deviceList = Array.isArray(devices) ? devices : [];
  const filteredDevices = filterDevices(deviceList, activeFilter);

  return (
    <div className="flex h-full overflow-hidden">
      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 p-6 overflow-y-auto">
        {/* Filters bar */}
        <div className="flex items-center justify-between mb-5">
          {/* Left: title + count */}
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-extrabold text-on-surface">Inventory</h1>
            <span className="flex items-center justify-center min-w-[28px] h-7 px-2 bg-surface-container-high rounded-full text-xs font-bold text-on-surface-variant">
              {filteredDevices.length}
            </span>
          </div>

          {/* Right: filters + actions */}
          <div className="flex items-center gap-3">
            {/* Toggle buttons */}
            <div className="flex bg-surface-container-low rounded-lg p-1">
              {FILTERS.map((f) => (
                <button
                  key={f}
                  onClick={() => setActiveFilter(f)}
                  className={`px-3.5 py-1.5 rounded-md text-[11px] font-bold transition-all ${
                    activeFilter === f
                      ? 'bg-white shadow-sm text-on-surface'
                      : 'text-on-surface-variant hover:text-on-surface'
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>

            {/* Filter button */}
            <button
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-outline/20 text-xs font-bold text-on-surface-variant hover:bg-surface-container-low transition-colors"
            >
              <Icon name="filter_list" className="text-base" />
              Filter
            </button>

            {/* Add Device button */}
            <button className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-white text-xs font-bold hover:bg-primary/90 transition-colors">
              <Icon name="add" className="text-base" />
              Add Device
            </button>
          </div>
        </div>

        {/* Loading state */}
        {loading && (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
          </div>
        )}

        {/* Error state */}
        {error && (
          <div className="flex items-center gap-3 bg-error/5 border border-error/20 rounded-xl px-5 py-4 mb-4">
            <Icon name="error" className="text-xl text-error" />
            <div>
              <p className="text-sm font-bold text-error">Failed to load devices</p>
              <p className="text-xs text-on-surface-variant mt-0.5">{error.message}</p>
            </div>
            <button
              onClick={refetch}
              className="ml-auto px-3 py-1.5 rounded-lg bg-error/10 text-error text-xs font-bold hover:bg-error/15 transition-colors"
            >
              Retry
            </button>
          </div>
        )}

        {/* Table */}
        {!loading && !error && (
          <DeviceTable
            devices={filteredDevices}
            selectedDevice={selectedDevice}
            onSelect={setSelectedDevice}
          />
        )}
      </div>

      {/* Right detail panel */}
      {selectedDevice && (
        <DetailPanel device={selectedDevice} onClose={() => setSelectedDevice(null)} />
      )}
    </div>
  );
}
