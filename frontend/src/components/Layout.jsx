import { useEffect, useRef, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from './Sidebar';
import TopNav from './TopNav';
import ChatPanel from './ChatPanel';
import Icon from './Icon';

export default function Layout() {
  const { pathname } = useLocation();
  const mainRef = useRef(null);
  const [chatState, setChatState] = useState('closed'); // 'closed' | 'minimized' | 'open'
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.localStorage.getItem('parity.sidebarCollapsed') === '1';
  });

  useEffect(() => {
    window.localStorage.setItem('parity.sidebarCollapsed', sidebarCollapsed ? '1' : '0');
  }, [sidebarCollapsed]);

  // Force browser repaint after navigation
  useEffect(() => {
    const el = mainRef.current;
    if (!el) return;
    el.style.willChange = 'contents';
    void el.offsetHeight;
    requestAnimationFrame(() => {
      el.style.willChange = '';
    });
  }, [pathname]);

  return (
    <>
      <TopNav />
      <div className="flex min-h-screen">
        <Sidebar collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed((c) => !c)} />
        <main
          ref={mainRef}
          className={`flex-1 p-8 bg-surface transition-[margin] duration-200 ${
            sidebarCollapsed ? 'ml-20' : 'ml-64'
          }`}
        >
          <Outlet key={pathname} />
        </main>
      </div>

      {/* Chat FAB — visible when chat is fully closed. Branded with
          the Gemini four-colour gradient + filled auto_awesome
          sparkle to match the open panel header and every other
          Gemini chip across the app. */}
      {chatState === 'closed' && (
        <button
          onClick={() => setChatState('open')}
          title="Open Gemini Assistant"
          className="fixed bottom-6 right-6 w-14 h-14 rounded-2xl text-white shadow-lg shadow-primary/30 flex items-center justify-center hover:scale-105 hover:shadow-xl transition-all z-50"
          style={{ background: 'linear-gradient(135deg, #4285F4 0%, #34A853 50%, #FBBC04 100%)' }}
        >
          <Icon name="auto_awesome" className="text-[24px]" fill />
        </button>
      )}

      <ChatPanel state={chatState} onStateChange={setChatState} />
    </>
  );
}
