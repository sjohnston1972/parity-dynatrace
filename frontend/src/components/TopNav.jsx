import { NavLink } from 'react-router-dom';
import Icon from './Icon';

const navLinks = [
  { to: '/', label: 'Overview' },
  { to: '/topology', label: 'Topology' },
  { to: '/devices', label: 'Devices' },
  { to: '/insights', label: 'AI Insights' },
];

export default function TopNav() {
  return (
    <header className="flex items-center justify-between px-6 w-full sticky top-0 z-40 bg-white h-16 shadow-sm text-sm font-medium tracking-tight">
      <div className="flex items-center gap-8">
        <div className="flex items-center gap-2">
          <span className="text-xl font-bold tracking-tighter text-slate-900">Parity</span>
          <span className="hidden md:inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest text-slate-500 border-l border-slate-300 pl-2 ml-1">
            <span className="w-1.5 h-1.5 rounded-full bg-[#1496FF]" />
            on Dynatrace
          </span>
        </div>
        <div className="hidden md:flex items-center gap-6">
          {navLinks.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.to === '/'}
              className={({ isActive }) =>
                isActive
                  ? 'text-blue-600 border-b-2 border-blue-600 py-5 px-2'
                  : 'text-slate-500 hover:bg-slate-50 transition-colors py-5 px-2'
              }
            >
              {link.label}
            </NavLink>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div className="relative hidden lg:block">
          <Icon name="search" className="absolute left-3 top-1/2 -translate-y-1/2 text-outline text-lg" />
          <input
            className="bg-surface-container-low border-none rounded-lg pl-10 pr-4 py-2 w-64 text-sm focus:ring-2 focus:ring-primary/20 focus:outline-none"
            placeholder="Search resources..."
            type="text"
          />
        </div>
        <button className="p-2 text-outline hover:bg-slate-50 rounded-full transition-colors relative">
          <Icon name="notifications" />
          <span className="absolute top-2 right-2 w-2 h-2 bg-error rounded-full border-2 border-white" />
        </button>
        <NavLink to="/settings" className="p-2 text-outline hover:bg-slate-50 rounded-full transition-colors">
          <Icon name="settings" />
        </NavLink>
        <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-white text-xs font-bold">
          K
        </div>
      </div>
    </header>
  );
}
