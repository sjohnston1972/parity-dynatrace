import { NavLink } from 'react-router-dom';
import Icon from './Icon';
import dynatraceCube from '../assets/dynatrace-logo-cube.png';

const navItems = [
  { to: '/', icon: 'dashboard', label: 'Overview' },
  { to: '/topology', icon: 'hub', label: 'Topology' },
  { to: '/devices', icon: 'router', label: 'Devices' },
  { to: '/snapshots', icon: 'camera', label: 'Snapshots' },
  { to: '/approvals', icon: 'verified_user', label: 'Approvals' },
  { to: '/incidents', icon: 'history', label: 'Incident Log' },
  { to: '/insights', icon: 'psychology', label: 'AI Insights' },
  { to: '/pipeline', icon: 'account_tree', label: 'AI Pipeline' },
  { to: '/executions', icon: 'terminal', label: 'Executions' },
  { to: '/dynatrace', icon: 'hexagon', label: 'Dynatrace', image: dynatraceCube },
];

const bottomItems = [
  { to: '/settings', icon: 'settings', label: 'Settings' },
];

function SideLink({ to, icon, label, collapsed, image }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      title={collapsed ? label : undefined}
      className={({ isActive }) =>
        `flex items-center ${collapsed ? 'justify-center px-0' : 'gap-3 px-4'} py-3 rounded-lg transition-all duration-200 text-sm font-semibold ${
          isActive
            ? 'text-blue-700 bg-blue-50/50'
            : 'text-slate-600 hover:bg-slate-200/50'
        }`
      }
    >
      {image ? (
        <img src={image} alt="" className="w-5 h-5 object-contain shrink-0" />
      ) : (
        <Icon name={icon} />
      )}
      {!collapsed && <span>{label}</span>}
    </NavLink>
  );
}

export default function Sidebar({ collapsed = false, onToggle }) {
  return (
    <aside
      className={`fixed left-0 top-0 h-full flex flex-col pt-20 pb-6 bg-slate-50 z-30 transition-[width] duration-200 ${
        collapsed ? 'w-20 px-2' : 'w-64 px-4'
      }`}
    >
      <div className={`mb-8 ${collapsed ? 'px-0' : 'px-4'}`}>
        <div className={`flex items-center ${collapsed ? 'justify-center' : 'gap-3'}`}>
          <div className="w-10 h-10 rounded-lg bg-primary flex items-center justify-center text-white shadow-lg shadow-primary/20 shrink-0">
            <Icon name="compare" />
          </div>
          {!collapsed && (
            <div>
              <h2 className="text-sm font-extrabold tracking-tight text-slate-900">PARITY</h2>
              <p className="text-[10px] uppercase tracking-widest text-secondary font-bold">Stay in Sync</p>
            </div>
          )}
        </div>
      </div>

      <nav className="flex-1 flex flex-col gap-1">
        {navItems.map((item) => (
          <SideLink key={item.to} {...item} collapsed={collapsed} />
        ))}
      </nav>

      <div className="mt-auto border-t border-slate-200 pt-6 flex flex-col gap-1">
        {bottomItems.map((item) => (
          <SideLink key={item.to} {...item} collapsed={collapsed} />
        ))}
        <button
          type="button"
          onClick={onToggle}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className={`flex items-center ${collapsed ? 'justify-center px-0' : 'gap-3 px-4'} py-3 rounded-lg text-sm font-semibold text-slate-600 hover:bg-slate-200/50 transition-all duration-200`}
        >
          <Icon name={collapsed ? 'chevron_right' : 'chevron_left'} />
          {!collapsed && <span>Collapse</span>}
        </button>
      </div>
    </aside>
  );
}
