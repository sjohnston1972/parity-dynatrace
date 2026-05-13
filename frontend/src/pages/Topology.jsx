import { useState, useMemo, useRef, useCallback, useEffect } from 'react';
import { useApi } from '../hooks/useApi';
import { api } from '../api/client';
import Icon from '../components/Icon';

// ── Layout helpers ───────────────────────────────────────────

function layoutNodes(nodes, edges) {
  const tiers = { firewall: 0, router: 1, switch: 2, segment: 3, unknown: 2 };
  const grouped = {};
  nodes.forEach((n) => {
    const tier = n._isSegment ? 3 : (tiers[n.device_type] ?? 2);
    (grouped[tier] = grouped[tier] || []).push(n);
  });
  Object.values(grouped).forEach((g) => g.sort((a, b) => a.hostname.localeCompare(b.hostname)));

  const positions = {};
  const tierKeys = Object.keys(grouped).sort((a, b) => a - b);
  const TIER_Y_GAP = 180;
  const NODE_X_GAP = 160;
  const SEG_X_GAP = 140;
  const PADDING_X = 80;
  const START_Y = 60;
  const maxWidth = Math.max(...tierKeys.map((t) => {
    const gap = grouped[t][0]?._isSegment ? SEG_X_GAP : NODE_X_GAP;
    return (grouped[t].length - 1) * gap;
  }));

  tierKeys.forEach((tier, tierIdx) => {
    const group = grouped[tier];
    const isSegTier = group[0]?._isSegment;
    const gap = isSegTier ? SEG_X_GAP : NODE_X_GAP;
    const tierWidth = (group.length - 1) * gap;
    const offsetX = PADDING_X + (maxWidth - tierWidth) / 2;
    const y = START_Y + tierIdx * TIER_Y_GAP;
    group.forEach((node, i) => {
      positions[node.id] = { x: offsetX + i * gap, y };
    });
  });
  return positions;
}

// ── View configuration ──────────────────────────────────────

const VIEWS = {
  bgp: {
    key: 'bgp',
    label: 'Layer 3',
    icon: 'swap_horiz',
    edgeField: 'bgp_edges',
    color: '#0063eb',
    description: 'BGP peering relationships',
    edgeStyle: { dash: undefined, width: 2.5 },
  },
  l2: {
    key: 'l2',
    label: 'Layer 2',
    icon: 'cable',
    edgeField: 'l2_edges',
    color: '#7b1fa2',
    description: 'ARP/MAC adjacencies',
    edgeStyle: { dash: '3 2', width: 1.5 },
  },
};

const DEVICE_ICONS = {
  router: 'router',
  switch: 'lan',
  firewall: 'shield',
  unknown: 'device_unknown',
};

const EDGE_HEALTH_COLORS = {
  optimal: '#006c4f',
  congested: '#e88a0c',
  critical: '#ba1a1a',
};

const ZONE_COLORS = [
  { fill: 'rgba(0, 99, 235, 0.06)', stroke: 'rgba(0, 99, 235, 0.25)', text: '#0063eb' },
  { fill: 'rgba(0, 108, 79, 0.06)', stroke: 'rgba(0, 108, 79, 0.25)', text: '#006c4f' },
  { fill: 'rgba(232, 138, 12, 0.06)', stroke: 'rgba(232, 138, 12, 0.25)', text: '#b86e00' },
  { fill: 'rgba(156, 39, 176, 0.06)', stroke: 'rgba(156, 39, 176, 0.25)', text: '#7b1fa2' },
  { fill: 'rgba(0, 150, 136, 0.06)', stroke: 'rgba(0, 150, 136, 0.25)', text: '#00796b' },
  { fill: 'rgba(186, 26, 26, 0.06)', stroke: 'rgba(186, 26, 26, 0.25)', text: '#ba1a1a' },
];

// ── Sub-components ──────────────────────────────────────────

function ToolbarButton({ icon, onClick, label, active }) {
  return (
    <button
      onClick={onClick}
      title={label}
      className={`w-10 h-10 flex items-center justify-center rounded-lg transition-colors ${
        active ? 'bg-primary/10 text-primary' : 'hover:bg-outline-variant/30 text-on-surface-variant'
      }`}
    >
      <Icon name={icon} className="text-[20px]" />
    </button>
  );
}

function SegmentNode({ node, pos, selected, onClick, onDragStart }) {
  const memberCount = node._memberCount || 0;
  return (
    <g
      transform={`translate(${pos.x}, ${pos.y})`}
      onClick={(e) => onClick(node, e)}
      onMouseDown={(e) => onDragStart(e, node.id)}
      className="cursor-grab active:cursor-grabbing"
    >
      <rect
        x={-52} y={-18} width={104} height={36} rx={8}
        className={selected ? 'fill-[#7b1fa2]/10 stroke-[#7b1fa2]' : 'fill-surface-container-lowest stroke-outline-variant/60'}
        strokeWidth={selected ? 2 : 1}
      />
      <text y={1} textAnchor="middle" className="text-[10px] font-bold font-mono fill-current text-on-surface select-none">
        {node.hostname}
      </text>
      <text y={13} textAnchor="middle" className="text-[8px] fill-current text-on-surface-variant select-none">
        {memberCount} device{memberCount !== 1 ? 's' : ''}
      </text>
    </g>
  );
}

function DeviceNode({ node, pos, selected, onClick, onDragStart }) {
  const isFirewall = node.device_type === 'firewall';
  const hasSnap = node.has_snapshot;
  const icon = DEVICE_ICONS[node.device_type] || DEVICE_ICONS.unknown;

  let ringCls, bgCls, iconCls;
  if (selected) {
    ringCls = 'ring-4 ring-primary/30';
    bgCls = 'bg-primary';
    iconCls = 'text-on-primary';
  } else if (!hasSnap) {
    ringCls = 'ring-1 ring-outline-variant/50';
    bgCls = 'bg-surface-container-high';
    iconCls = 'text-on-surface-variant';
  } else if (isFirewall) {
    ringCls = 'ring-2 ring-amber-400/40';
    bgCls = 'bg-amber-400/10';
    iconCls = 'text-amber-500';
  } else {
    ringCls = 'ring-1 ring-outline-variant';
    bgCls = 'bg-surface-container-lowest';
    iconCls = 'text-on-surface-variant';
  }

  return (
    <g
      transform={`translate(${pos.x}, ${pos.y})`}
      onClick={(e) => onClick(node, e)}
      onMouseDown={(e) => onDragStart(e, node.id)}
      className="cursor-grab active:cursor-grabbing"
    >
      <circle cx={0} cy={0} r={28} className={`fill-current ${selected ? 'text-primary/5' : 'text-transparent'}`} />
      <foreignObject x={-24} y={-24} width={48} height={48}>
        <div className={`w-12 h-12 rounded-xl ${bgCls} ${ringCls} flex items-center justify-center shadow-sm transition-all hover:scale-110 hover:shadow-md`}>
          <Icon name={icon} className={`text-[22px] ${iconCls}`} />
        </div>
      </foreignObject>
      <text y={40} textAnchor="middle" className="text-[11px] font-bold fill-current text-on-surface-variant select-none">
        {node.hostname}
      </text>
      {!hasSnap && (
        <foreignObject x={14} y={-30} width={18} height={18}>
          <div className="w-4 h-4 rounded-full bg-outline-variant/40 flex items-center justify-center">
            <Icon name="cloud_off" className="text-[10px] text-on-surface-variant" />
          </div>
        </foreignObject>
      )}
    </g>
  );
}

function EdgeLine({ edge, fromPos, toPos, showLabels, viewConfig }) {
  const style = viewConfig.edgeStyle;
  const color = EDGE_HEALTH_COLORS[edge.health] || viewConfig.color;

  const mx = (fromPos.x + toPos.x) / 2;
  const my = (fromPos.y + toPos.y) / 2;

  const fromLx = fromPos.x + (toPos.x - fromPos.x) * 0.18;
  const fromLy = fromPos.y + (toPos.y - fromPos.y) * 0.18;
  const toLx = fromPos.x + (toPos.x - fromPos.x) * 0.82;
  const toLy = fromPos.y + (toPos.y - fromPos.y) * 0.82;

  const dx = toPos.x - fromPos.x;
  const dy = toPos.y - fromPos.y;
  const len = Math.sqrt(dx * dx + dy * dy) || 1;
  const perpX = (-dy / len) * 10;
  const perpY = (dx / len) * 10;

  const centerLabel = edge.label || '';
  const subnetLabel = edge.subnet && edge.subnet !== edge.label ? edge.subnet : '';
  const centerLines = [centerLabel, subnetLabel].filter(Boolean);
  const centerHeight = centerLines.length * 12 + 6;

  return (
    <g>
      <line
        x1={fromPos.x} y1={fromPos.y} x2={toPos.x} y2={toPos.y}
        stroke={color} strokeWidth={style.width} strokeOpacity={0.5} strokeDasharray={style.dash}
      />
      {showLabels && (
        <>
          {centerLines.length > 0 && (
            <>
              <rect
                x={mx - 48} y={my - centerHeight / 2} width={96} height={centerHeight}
                rx={4} fill="white" fillOpacity={0.92} stroke={color} strokeWidth={0.5}
              />
              {centerLines.map((line, i) => (
                <text
                  key={i} x={mx} y={my - ((centerLines.length - 1) * 6) + i * 12 + 4}
                  textAnchor="middle"
                  className={`select-none ${i === 0 ? 'text-[9px] font-bold' : 'text-[8px] font-medium'}`}
                  fill={i === 0 ? color : '#6b7280'}
                >
                  {line}
                </text>
              ))}
            </>
          )}
          {edge.from_intf && (
            <text x={fromLx + perpX} y={fromLy + perpY} textAnchor="middle" className="text-[8px] font-mono font-semibold select-none" fill="#6b7280">
              {edge.from_intf}
            </text>
          )}
          {edge.to_intf && (
            <text x={toLx + perpX} y={toLy + perpY} textAnchor="middle" className="text-[8px] font-mono font-semibold select-none" fill="#6b7280">
              {edge.to_intf}
            </text>
          )}
        </>
      )}
    </g>
  );
}

function SegmentDetailPanel({ node, edges, allNodes, onClose }) {
  const nodeMap = {};
  allNodes.forEach((n) => { nodeMap[n.id] = n; });
  const members = node._members || [];

  return (
    <div className="w-[380px] shrink-0 bg-surface-container-low border-l border-outline-variant/40 flex flex-col overflow-y-auto">
      <div className="p-6 pb-4 border-b border-outline-variant/30">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">L2 Segment</span>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-surface-container-high transition-colors">
            <Icon name="close" className="text-lg text-on-surface-variant" />
          </button>
        </div>
        <h2 className="text-xl font-extrabold font-mono text-on-surface">{node.hostname}</h2>
        <p className="text-xs text-on-surface-variant mt-1">{members.length} connected device{members.length !== 1 ? 's' : ''}</p>
      </div>

      <div className="px-6 py-4 flex-1">
        <p className="text-[10px] font-bold tracking-widest text-on-surface-variant uppercase mb-3">Members</p>
        <div className="space-y-2">
          {members.map((m, i) => {
            const dev = nodeMap[m.device_id];
            return (
              <div key={i} className="bg-surface-container-lowest rounded-lg px-4 py-3">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                    <Icon name={DEVICE_ICONS[dev?.device_type] || 'device_unknown'} className="text-base text-primary" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-bold text-on-surface truncate">{dev?.hostname || m.device_id.slice(0, 8)}</div>
                    <div className="text-[10px] text-on-surface-variant font-mono">{m.ip}</div>
                  </div>
                  <span className="text-[10px] font-mono text-on-surface-variant bg-surface-container-high px-2 py-0.5 rounded">{m.intf}</span>
                </div>
                {m.mac && (
                  <div className="mt-1.5 ml-11 text-[10px] font-mono text-on-surface-variant/60">{m.mac}</div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function DetailPanel({ node, edges, allNodes, onClose, viewConfig }) {
  const nodeEdges = edges.filter((e) => e.from === node.id || e.to === node.id);
  const nodeMap = {};
  allNodes.forEach((n) => { nodeMap[n.id] = n; });

  return (
    <div className="w-[380px] shrink-0 bg-surface-container-low border-l border-outline-variant/40 flex flex-col overflow-y-auto">
      <div className="p-6 pb-4 border-b border-outline-variant/30">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
            {node.device_type}
          </span>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-surface-container-high transition-colors">
            <Icon name="close" className="text-lg text-on-surface-variant" />
          </button>
        </div>
        <h2 className="text-xl font-extrabold text-on-surface">{node.hostname}</h2>
        <div className="flex items-center gap-2 mt-1.5">
          <span className="text-xs text-on-surface-variant font-mono">{node.management_ip}</span>
          <span className="text-xs text-outline-variant">|</span>
          <span className="text-xs text-on-surface-variant">{node.platform}</span>
          {node.tags?.site && (
            <>
              <span className="text-xs text-outline-variant">|</span>
              <span className="text-xs text-on-surface-variant">{node.tags.site}</span>
            </>
          )}
        </div>
      </div>

      <div className="p-6 pb-2">
        <p className="text-[10px] font-bold tracking-widest text-on-surface-variant uppercase mb-3">Interfaces</p>
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-surface-container-lowest rounded-xl p-4">
            <p className="text-[11px] text-on-surface-variant mb-1">Up</p>
            <p className="text-2xl font-extrabold text-secondary">{node.interfaces_up}</p>
          </div>
          <div className="bg-surface-container-lowest rounded-xl p-4">
            <p className="text-[11px] text-on-surface-variant mb-1">Total</p>
            <p className="text-2xl font-extrabold text-on-surface">{node.interfaces_total}</p>
          </div>
        </div>
      </div>

      <div className="px-6 py-4 flex-1">
        <p className="text-[10px] font-bold tracking-widest text-on-surface-variant uppercase mb-3">
          {viewConfig.label} Connections ({nodeEdges.length})
        </p>
        <div className="space-y-2">
          {nodeEdges.map((edge, i) => {
            const peerId = edge.from === node.id ? edge.to : edge.from;
            const peer = nodeMap[peerId];
            const healthColor = EDGE_HEALTH_COLORS[edge.health] || viewConfig.color;
            return (
              <div key={i} className="bg-surface-container-lowest rounded-lg px-4 py-3">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                    <Icon name={DEVICE_ICONS[peer?.device_type] || 'device_unknown'} className="text-base text-primary" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-bold text-on-surface truncate">
                      {peer?.hostname || peerId.slice(0, 8)}
                    </div>
                    <div className="text-[10px] text-on-surface-variant">{edge.label}</div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: healthColor }} />
                    <span className="text-[10px] font-bold text-on-surface-variant capitalize">{edge.type}</span>
                  </div>
                </div>
                {(edge.from_intf || edge.to_intf || edge.subnet) && (
                  <div className="mt-2 ml-11 flex flex-wrap items-center gap-x-3 gap-y-1">
                    {(() => {
                      const localIntf = edge.from === node.id ? edge.from_intf : edge.to_intf;
                      const remoteIntf = edge.from === node.id ? edge.to_intf : edge.from_intf;
                      return (
                        <>
                          {localIntf && (
                            <span className="text-[10px] font-mono text-on-surface-variant">
                              <span className="text-[9px] text-outline-variant">local</span> {localIntf}
                            </span>
                          )}
                          {remoteIntf && (
                            <span className="text-[10px] font-mono text-on-surface-variant">
                              <span className="text-[9px] text-outline-variant">remote</span> {remoteIntf}
                            </span>
                          )}
                          {edge.subnet && (
                            <span className="text-[10px] font-mono text-on-surface-variant/70">{edge.subnet}</span>
                          )}
                          {edge.mac && (
                            <span className="text-[10px] font-mono text-on-surface-variant/70">{edge.mac}</span>
                          )}
                        </>
                      );
                    })()}
                  </div>
                )}
              </div>
            );
          })}
          {nodeEdges.length === 0 && (
            <div className="flex flex-col items-center py-6 text-on-surface-variant">
              <Icon name="link_off" className="text-2xl mb-2 opacity-40" />
              <p className="text-xs font-semibold">No {viewConfig.label.toLowerCase()} connections detected</p>
              <p className="text-[10px] mt-1 opacity-60">Take a snapshot to discover neighbors</p>
            </div>
          )}
        </div>
      </div>

      <div className="px-6 py-4 border-t border-outline-variant/30">
        <div className="flex items-center gap-2">
          <Icon
            name={node.has_snapshot ? 'check_circle' : 'cloud_off'}
            className={`text-base ${node.has_snapshot ? 'text-secondary' : 'text-on-surface-variant'}`}
          />
          <span className="text-xs text-on-surface-variant">
            {node.has_snapshot ? 'Snapshot data available' : 'No snapshot — take one to see full topology'}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Topology Canvas (one per view) ──────────────────────────

function TopologyCanvas({ nodes, edges, viewConfig, active }) {
  const [selectedNode, setSelectedNode] = useState(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [showLabels, setShowLabels] = useState(true);
  const [mode, setMode] = useState('pointer');
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const isPanning = useRef(false);
  const lastMouse = useRef({ x: 0, y: 0 });

  const initialPositions = useMemo(() => layoutNodes(nodes, edges), [nodes, edges]);
  const [positions, setPositions] = useState({});
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [selRect, setSelRect] = useState(null);
  const [zones, setZones] = useState([]);
  const [editingZone, setEditingZone] = useState(null);
  const dragging = useRef(null);
  const selecting = useRef(null);
  const drawingZone = useRef(null);
  const serverLayout = useRef(null);
  const layoutReady = useRef(false);
  const userModified = useRef(false);
  const [layoutLoaded, setLayoutLoaded] = useState(0); // bumped when layout arrives

  // Load saved layout for this view
  useEffect(() => {
    layoutReady.current = false;
    userModified.current = false;
    api.topologyLayout(viewConfig.key).then((data) => {
      serverLayout.current = data;
      if (data.zones?.length) setZones(data.zones);
      layoutReady.current = true;
      setLayoutLoaded((c) => c + 1); // trigger positions re-sync
    }).catch(() => { layoutReady.current = true; setLayoutLoaded((c) => c + 1); });
  }, [viewConfig.key]);

  // Sync positions when topology data or saved layout changes
  useEffect(() => {
    const saved = serverLayout.current?.positions || {};
    setPositions(() => {
      const next = { ...initialPositions };
      for (const id in saved) {
        if (next[id]) next[id] = { ...saved[id], _dragged: true };
      }
      return next;
    });
  }, [initialPositions, layoutLoaded]);

  // Save helper — builds payload and sends to API
  const doSave = useCallback((pos, z) => {
    const dragged = {};
    for (const id in pos) {
      if (pos[id]._dragged) dragged[id] = { x: pos[id].x, y: pos[id].y };
    }
    api.saveTopologyLayout(viewConfig.key, { positions: dragged, zones: z }).catch(() => {});
  }, [viewConfig.key]);

  // Debounced save on position/zone changes
  const saveTimer = useRef(null);
  useEffect(() => {
    if (!layoutReady.current || !userModified.current) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => doSave(positions, zones), 800);
    return () => clearTimeout(saveTimer.current);
  }, [positions, zones, doSave]);

  // Keep latest values in refs for unmount flush
  const positionsRef = useRef(positions);
  const zonesRef = useRef(zones);
  positionsRef.current = positions;
  zonesRef.current = zones;
  const doSaveRef = useRef(doSave);
  doSaveRef.current = doSave;

  // Flush pending save on unmount
  useEffect(() => {
    return () => {
      if (saveTimer.current) {
        clearTimeout(saveTimer.current);
        if (userModified.current) doSaveRef.current(positionsRef.current, zonesRef.current);
      }
    };
  }, []);

  // ViewBox
  const viewBox = useMemo(() => {
    const xs = Object.values(positions).map((p) => p.x);
    const ys = Object.values(positions).map((p) => p.y);
    if (!xs.length) return { x: 0, y: 0, w: 1200, h: 700 };
    const pad = 100;
    return {
      x: Math.min(...xs) - pad, y: Math.min(...ys) - pad,
      w: Math.max(...xs) - Math.min(...xs) + pad * 2,
      h: Math.max(...ys) - Math.min(...ys) + pad * 2 + 50,
    };
  }, [positions]);

  // Zoom-to-fit on initial load
  const hasFitted = useRef(false);
  useEffect(() => {
    if (!active) return;
    hasFitted.current = false;
  }, [viewConfig.key, active]);

  useEffect(() => {
    if (hasFitted.current || !active) return;
    const container = containerRef.current;
    if (!container || Object.keys(positions).length === 0) return;
    hasFitted.current = true;
    requestAnimationFrame(() => {
      const rect = container.getBoundingClientRect();
      const cw = rect.width;
      const ch = rect.height;
      if (!cw || !ch || !viewBox.w || !viewBox.h) return;
      const scaleX = cw / viewBox.w;
      const scaleY = ch / viewBox.h;
      const fitZoom = Math.min(scaleX, scaleY, 1.5) * 0.9;
      const contentCx = viewBox.x + viewBox.w / 2;
      const contentCy = viewBox.y + viewBox.h / 2;
      setZoom(fitZoom);
      setPan({ x: cw / 2 - contentCx * fitZoom, y: ch / 2 - contentCy * fitZoom });
    });
  }, [positions, viewBox, active]);

  const [, forceRender] = useState(0);
  const stateRef = useRef({ pan, zoom, positions, selectedIds, mode, zones, selRect });
  stateRef.current = { pan, zoom, positions, selectedIds, mode, zones, selRect };

  const didDrag = useRef(false);

  const handleNodeDragStart = useCallback((e, nodeId) => {
    e.stopPropagation();
    didDrag.current = false;
    const { positions: pos, selectedIds: sel } = stateRef.current;
    const ids = sel.has(nodeId) && sel.size > 1 ? [...sel] : [nodeId];
    const origins = {};
    ids.forEach((id) => { origins[id] = { x: pos[id]?.x ?? 0, y: pos[id]?.y ?? 0 }; });
    dragging.current = { ids, startX: e.clientX, startY: e.clientY, origins };
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const getSvgPt = (clientX, clientY) => {
      const rect = svgRef.current?.getBoundingClientRect() || { left: 0, top: 0 };
      const { pan: p, zoom: z } = stateRef.current;
      return { x: (clientX - rect.left - p.x) / z, y: (clientY - rect.top - p.y) / z };
    };

    const onMouseDown = (e) => {
      if (e.button !== 0 || dragging.current) return;
      const clientX = e.clientX, clientY = e.clientY;
      requestAnimationFrame(() => {
        if (dragging.current) return;
        const { mode: m } = stateRef.current;
        if (m === 'select') {
          const pt = getSvgPt(clientX, clientY);
          selecting.current = true;
          setSelRect({ x1: pt.x, y1: pt.y, x2: pt.x, y2: pt.y });
        } else if (m === 'zone') {
          const pt = getSvgPt(clientX, clientY);
          drawingZone.current = true;
          setSelRect({ x1: pt.x, y1: pt.y, x2: pt.x, y2: pt.y });
        } else {
          isPanning.current = true;
          lastMouse.current = { x: clientX, y: clientY };
        }
      });
    };

    const onMouseMove = (e) => {
      if (dragging.current) {
        didDrag.current = true;
        const d = dragging.current;
        const z = stateRef.current.zoom;
        const dx = (e.clientX - d.startX) / z;
        const dy = (e.clientY - d.startY) / z;
        setPositions((prev) => {
          const next = { ...prev };
          d.ids.forEach((id) => {
            const orig = d.origins[id];
            if (orig) { next[id] = { x: orig.x + dx, y: orig.y + dy, _dragged: true }; userModified.current = true; }
          });
          return next;
        });
        return;
      }
      if (selecting.current || drawingZone.current) {
        const pt = getSvgPt(e.clientX, e.clientY);
        setSelRect((prev) => prev ? { ...prev, x2: pt.x, y2: pt.y } : prev);
        return;
      }
      if (isPanning.current) {
        const dx = e.clientX - lastMouse.current.x;
        const dy = e.clientY - lastMouse.current.y;
        lastMouse.current = { x: e.clientX, y: e.clientY };
        setPan((p) => ({ x: p.x + dx, y: p.y + dy }));
      }
    };

    const onMouseUp = (e) => {
      if (dragging.current) { dragging.current = null; return; }
      const sr = stateRef.current.selRect;
      if (drawingZone.current && sr) {
        const w = Math.abs(sr.x2 - sr.x1);
        const h = Math.abs(sr.y2 - sr.y1);
        if (w > 20 && h > 20) {
          const zs = stateRef.current.zones;
          const newZone = {
            id: `zone-${Date.now()}`, x: Math.min(sr.x1, sr.x2), y: Math.min(sr.y1, sr.y2), w, h,
            label: 'New Zone', color: ZONE_COLORS[zs.length % ZONE_COLORS.length],
          };
          setZones((prev) => [...prev, newZone]);
          userModified.current = true;
          setEditingZone(newZone.id);
        }
        drawingZone.current = null;
        setSelRect(null);
        return;
      }
      if (selecting.current && sr) {
        const minX = Math.min(sr.x1, sr.x2), maxX = Math.max(sr.x1, sr.x2);
        const minY = Math.min(sr.y1, sr.y2), maxY = Math.max(sr.y1, sr.y2);
        if (Math.abs(sr.x2 - sr.x1) > 2 || Math.abs(sr.y2 - sr.y1) > 2) {
          const pos = stateRef.current.positions;
          const inside = new Set();
          for (const id in pos) {
            const p = pos[id];
            if (p.x >= minX && p.x <= maxX && p.y >= minY && p.y <= maxY) inside.add(id);
          }
          if (e.shiftKey) setSelectedIds((prev) => new Set([...prev, ...inside]));
          else setSelectedIds(inside);
        }
        selecting.current = null;
        setSelRect(null);
        return;
      }
      isPanning.current = false;
    };

    const onWheel = (e) => {
      e.preventDefault();
      setZoom((z) => Math.min(2.5, Math.max(0.3, z - e.deltaY * 0.001)));
    };

    container.addEventListener('mousedown', onMouseDown);
    container.addEventListener('mousemove', onMouseMove);
    container.addEventListener('mouseup', onMouseUp);
    container.addEventListener('mouseleave', onMouseUp);
    container.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      container.removeEventListener('mousedown', onMouseDown);
      container.removeEventListener('mousemove', onMouseMove);
      container.removeEventListener('mouseup', onMouseUp);
      container.removeEventListener('mouseleave', onMouseUp);
      container.removeEventListener('wheel', onWheel);
    };
  }, []);

  const handleZoomIn = () => setZoom((z) => Math.min(z + 0.2, 2.5));
  const handleZoomOut = () => setZoom((z) => Math.max(z - 0.2, 0.3));
  const handleReset = () => {
    setZoom(1); setPan({ x: 0, y: 0 }); setPositions(initialPositions); setZones([]);
    userModified.current = true;
    api.saveTopologyLayout(viewConfig.key, { positions: {}, zones: [] }).catch(() => {});
  };

  const edgeCounts = {};
  edges.forEach((e) => {
    edgeCounts[e.from] = (edgeCounts[e.from] || 0) + 1;
    edgeCounts[e.to] = (edgeCounts[e.to] || 0) + 1;
  });

  const snappedCount = nodes.filter((n) => n.has_snapshot).length;

  return (
    <div className="flex h-full">
      <div ref={containerRef} className="flex-1 relative bg-surface-container-low topology-grid overflow-hidden" style={{ isolation: 'isolate' }}>
        {/* Toolbar */}
        <div className="absolute top-4 left-4 z-20 bg-surface/95 rounded-xl shadow-lg border border-outline-variant/30 flex flex-col gap-0.5 p-1.5">
          <ToolbarButton icon="zoom_in" onClick={handleZoomIn} label="Zoom in" />
          <ToolbarButton icon="zoom_out" onClick={handleZoomOut} label="Zoom out" />
          <div className="h-px bg-outline-variant/40 mx-1.5 my-0.5" />
          <ToolbarButton icon="center_focus_strong" onClick={handleReset} label="Reset view" />
          <ToolbarButton icon="label" onClick={() => setShowLabels(!showLabels)} label="Toggle labels" active={showLabels} />
          <div className="h-px bg-outline-variant/40 mx-1.5 my-0.5" />
          <ToolbarButton icon="arrow_selector_tool" onClick={() => setMode('pointer')} label="Pointer mode" active={mode === 'pointer'} />
          <ToolbarButton icon="select_all" onClick={() => setMode('select')} label="Window select" active={mode === 'select'} />
          <ToolbarButton icon="rectangle" onClick={() => setMode('zone')} label="Add zone" active={mode === 'zone'} />
        </div>

        {/* Stats bar */}
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 bg-surface/95 rounded-full shadow-md border border-outline-variant/30 px-5 py-2 flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full animate-pulse" style={{ backgroundColor: viewConfig.color }} />
            <span className="text-xs font-bold text-on-surface">
              {nodes.filter((n) => !n._isSegment).length} Devices
              {viewConfig.key === 'l2' ? ` / ${nodes.filter((n) => n._isSegment).length} Segments` : ''}
            </span>
          </div>
          <span className="text-outline-variant">|</span>
          <span className="text-[11px] text-on-surface-variant">{edges.length} Links</span>
          <span className="text-outline-variant">|</span>
          <span className="text-[11px] text-on-surface-variant">{snappedCount}/{nodes.length} Snapped</span>
          {selectedIds.size > 0 && (
            <>
              <span className="text-outline-variant">|</span>
              <span className="text-[11px] font-bold text-primary">{selectedIds.size} Selected</span>
            </>
          )}
        </div>

        {/* Legend */}
        <div className="absolute bottom-4 left-4 z-10 bg-surface/95 rounded-xl shadow-lg border border-outline-variant/30 px-4 py-3">
          <p className="text-[10px] font-bold tracking-widest text-on-surface-variant uppercase mb-2">{viewConfig.label} Topology</p>
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2">
              <span className="w-5 h-0.5 rounded-full" style={{ backgroundColor: viewConfig.color, borderTop: viewConfig.edgeStyle.dash ? `2px dashed ${viewConfig.color}` : undefined }} />
              <span className="text-[11px] text-on-surface-variant">{viewConfig.description}</span>
            </div>
            {viewConfig.key === 'l2' && (
              <div className="flex items-center gap-2">
                <span className="inline-block w-5 h-3 rounded border border-outline-variant/60 bg-surface-container-lowest" />
                <span className="text-[11px] text-on-surface-variant">Subnet segment</span>
              </div>
            )}
            <div className="flex items-center gap-2">
              <span className="w-5 h-0.5 rounded-full bg-error" />
              <span className="text-[11px] text-on-surface-variant">Critical</span>
            </div>
          </div>
        </div>

        {/* SVG */}
        <svg
          ref={svgRef}
          className={`absolute inset-0 w-full h-full ${mode === 'select' || mode === 'zone' ? 'cursor-crosshair' : 'cursor-grab active:cursor-grabbing'}`}
          onClick={(e) => {
            if (mode === 'pointer' && e.target === svgRef.current) {
              setSelectedIds(new Set());
              setSelectedNode(null);
            }
          }}
        >
          <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
            {/* Zones */}
            {zones.map((zone) => (
              <g key={zone.id}>
                <rect x={zone.x} y={zone.y} width={zone.w} height={zone.h} fill={zone.color.fill} stroke={zone.color.stroke} strokeWidth={1.5} rx={12} />
                {editingZone === zone.id ? (
                  <foreignObject x={zone.x} y={zone.y - 2} width={zone.w} height={32}>
                    <input
                      autoFocus
                      className="w-full bg-white/90 border border-outline-variant/40 rounded-t-xl px-3 py-1 text-xs font-bold outline-none"
                      style={{ color: zone.color.text }}
                      defaultValue={zone.label}
                      onBlur={(e) => {
                        const val = e.target.value.trim();
                        setZones((prev) => prev.map((z) => z.id === zone.id ? { ...z, label: val || zone.label } : z));
                        userModified.current = true;
                        setEditingZone(null);
                      }}
                      onKeyDown={(e) => { if (e.key === 'Enter') e.target.blur(); if (e.key === 'Escape') setEditingZone(null); }}
                      onClick={(e) => e.stopPropagation()}
                      onMouseDown={(e) => e.stopPropagation()}
                    />
                  </foreignObject>
                ) : (
                  <text x={zone.x + 12} y={zone.y + 18} className="text-[11px] font-bold select-none cursor-pointer" fill={zone.color.text}
                    onDoubleClick={(e) => { e.stopPropagation(); setEditingZone(zone.id); }}>
                    {zone.label}
                  </text>
                )}
                <foreignObject x={zone.x + zone.w - 24} y={zone.y + 2} width={22} height={22}>
                  <div className="w-5 h-5 rounded-full bg-white/80 border border-outline-variant/40 flex items-center justify-center shadow-sm cursor-pointer hover:bg-error/10 hover:border-error/40 transition-colors"
                    onClick={(e) => { e.stopPropagation(); setZones((prev) => prev.filter((z) => z.id !== zone.id)); userModified.current = true; }}
                    onMouseDown={(e) => e.stopPropagation()}>
                    <Icon name="close" className="text-[12px] text-on-surface-variant" />
                  </div>
                </foreignObject>
              </g>
            ))}

            {/* Edges */}
            {edges.map((edge, i) => {
              const fromPos = positions[edge.from];
              const toPos = positions[edge.to];
              if (!fromPos || !toPos) return null;
              return <EdgeLine key={i} edge={edge} fromPos={fromPos} toPos={toPos} showLabels={showLabels} viewConfig={viewConfig} />;
            })}

            {/* Selection rect */}
            {selRect && (
              <rect
                x={Math.min(selRect.x1, selRect.x2)} y={Math.min(selRect.y1, selRect.y2)}
                width={Math.abs(selRect.x2 - selRect.x1)} height={Math.abs(selRect.y2 - selRect.y1)}
                fill={mode === 'zone' ? ZONE_COLORS[zones.length % ZONE_COLORS.length].fill : 'rgba(0, 99, 235, 0.08)'}
                stroke={mode === 'zone' ? ZONE_COLORS[zones.length % ZONE_COLORS.length].stroke : 'rgba(0, 99, 235, 0.4)'}
                strokeWidth={mode === 'zone' ? 1.5 : 1} strokeDasharray={mode === 'zone' ? undefined : '4 2'} rx={mode === 'zone' ? 12 : 4}
              />
            )}

            {/* Nodes */}
            {nodes.map((node) => {
              const pos = positions[node.id];
              if (!pos) return null;
              const NodeComponent = node._isSegment ? SegmentNode : DeviceNode;
              return (
                <NodeComponent
                  key={node.id} node={node} pos={pos}
                  selected={selectedNode?.id === node.id || selectedIds.has(node.id)}
                  onClick={(n, e) => {
                    if (didDrag.current) return;
                    if (e.ctrlKey || e.metaKey) {
                      setSelectedIds((prev) => { const next = new Set(prev); next.has(n.id) ? next.delete(n.id) : next.add(n.id); return next; });
                    } else {
                      setSelectedIds(new Set());
                      setSelectedNode(n);
                    }
                  }}
                  onDragStart={handleNodeDragStart}
                />
              );
            })}
          </g>
        </svg>
      </div>

      {/* Detail panel */}
      {selectedNode && (
        selectedNode._isSegment
          ? <SegmentDetailPanel node={selectedNode} edges={edges} allNodes={nodes} onClose={() => setSelectedNode(null)} />
          : <DetailPanel node={selectedNode} edges={edges} allNodes={nodes} onClose={() => setSelectedNode(null)} viewConfig={viewConfig} />
      )}
    </div>
  );
}

// ── Main component ──────────────────────────────────────────

export default function Topology() {
  const { data: topologyData, loading, refetch } = useApi(api.topology);
  const [activeView, setActiveView] = useState('bgp');

  const baseNodes = topologyData?.nodes || [];

  // Transform L2 segments into virtual hub nodes + spoke edges
  const l2Data = useMemo(() => {
    const segments = topologyData?.l2_segments || [];
    const segNodes = [];
    const segEdges = [];
    for (const seg of segments) {
      segNodes.push({
        id: seg.id,
        hostname: seg.subnet,
        device_type: 'segment',
        has_snapshot: true,
        interfaces_up: seg.members.length,
        interfaces_total: seg.members.length,
        _isSegment: true,
        _memberCount: seg.members.length,
        _members: seg.members,
        tags: {},
      });
      for (const m of seg.members) {
        segEdges.push({
          from: m.device_id,
          to: seg.id,
          type: 'l2',
          health: 'optimal',
          label: m.ip,
          from_intf: m.intf,
          to_intf: '',
          mac: m.mac || '',
        });
      }
    }
    return { nodes: segNodes, edges: segEdges };
  }, [topologyData]);

  const nodesByView = useMemo(() => ({
    bgp: baseNodes,
    l2: [...baseNodes, ...l2Data.nodes],
  }), [baseNodes, l2Data]);

  const edgesByView = useMemo(() => ({
    bgp: topologyData?.bgp_edges || [],
    l2: l2Data.edges,
  }), [topologyData, l2Data]);

  const viewConfig = VIEWS[activeView];
  const currentNodes = nodesByView[activeView];
  const currentEdges = edgesByView[activeView];

  return (
    <div className="flex flex-col h-[calc(100vh-10rem)]">
      {/* View tabs */}
      <div className="flex items-center gap-1 mb-3">
        {Object.values(VIEWS).map((v) => {
          const count = v.key === 'l2' ? l2Data.nodes.length : (edgesByView[v.key]?.length || 0);
          const isActive = activeView === v.key;
          return (
            <button
              key={v.key}
              onClick={() => setActiveView(v.key)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-bold transition-all ${
                isActive
                  ? 'bg-surface-container-lowest shadow-md border border-outline-variant/30 text-on-surface'
                  : 'text-on-surface-variant hover:bg-surface-container-high/60'
              }`}
            >
              <Icon name={v.icon} className="text-lg" style={isActive ? { color: v.color } : undefined} />
              <span>{v.label}</span>
              <span className={`ml-1 px-2 py-0.5 rounded-full text-[10px] font-extrabold ${
                isActive ? 'text-white' : 'bg-outline-variant/20 text-on-surface-variant'
              }`} style={isActive ? { backgroundColor: v.color } : undefined}>
                {count}
              </span>
            </button>
          );
        })}
        <div className="flex-1" />
        <button onClick={refetch} className="p-2 rounded-lg hover:bg-surface-container-high transition-colors" title="Refresh topology">
          <Icon name="refresh" className="text-lg text-on-surface-variant" />
        </button>
      </div>

      {/* Canvas */}
      <div className="flex-1 rounded-xl overflow-hidden border border-outline-variant/20" style={{ contain: 'strict' }}>
        {loading && (
          <div className="flex items-center justify-center h-full bg-surface-container-low">
            <div className="flex flex-col items-center gap-3">
              <div className="w-8 h-8 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
              <span className="text-sm font-semibold text-on-surface-variant">Building topology...</span>
            </div>
          </div>
        )}
        {!loading && (
          <TopologyCanvas
            key={activeView}
            nodes={currentNodes}
            edges={currentEdges}
            viewConfig={viewConfig}
            active={true}
          />
        )}
      </div>
    </div>
  );
}
