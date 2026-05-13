import { useState, useRef, useEffect, useCallback } from 'react';
import { api } from '../api/client';
import Icon from './Icon';

const MODELS = [
  { id: 'claude-haiku-4-5-20251001', label: 'Haiku', desc: 'Fast' },
  { id: 'claude-sonnet-4-6', label: 'Sonnet', desc: 'Balanced' },
];

const MIN_W = 360;
const MIN_H = 300;
const DEFAULT_W = 440;
const DEFAULT_H = 600;

function Markdown({ text }) {
  const parts = text.split(/(```[\s\S]*?```|`[^`]+`)/g);
  return (
    <div className="text-sm leading-relaxed whitespace-pre-wrap">
      {parts.map((part, i) => {
        if (part.startsWith('```')) {
          const inner = part.replace(/^```\w*\n?/, '').replace(/\n?```$/, '');
          return (
            <pre key={i} className="bg-slate-900 text-slate-200 rounded-lg px-3 py-2 my-2 text-xs font-mono overflow-x-auto">
              {inner}
            </pre>
          );
        }
        if (part.startsWith('`') && part.endsWith('`')) {
          return (
            <code key={i} className="bg-surface-container-high text-primary px-1 py-0.5 rounded text-xs font-mono">
              {part.slice(1, -1)}
            </code>
          );
        }
        return (
          <span key={i} dangerouslySetInnerHTML={{
            __html: part
              .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
              .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
          }} />
        );
      })}
    </div>
  );
}

// state: 'closed' | 'minimized' | 'open'
export default function ChatPanel({ state, onStateChange }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [model, setModel] = useState(MODELS[0].id);
  const [size, setSize] = useState({ w: DEFAULT_W, h: DEFAULT_H });
  const bottomRef = useRef(null);
  const inputRef = useRef(null);
  const abortRef = useRef(null);
  const resizing = useRef(null);

  useEffect(() => {
    if (state === 'open' && inputRef.current) inputRef.current.focus();
  }, [state]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Resize handlers
  const onResizeStart = useCallback((e, edge) => {
    e.preventDefault();
    resizing.current = { edge, startX: e.clientX, startY: e.clientY, startW: size.w, startH: size.h };
    const onMove = (e) => {
      if (!resizing.current) return;
      const r = resizing.current;
      let newW = r.startW, newH = r.startH;
      if (r.edge === 'left' || r.edge === 'top-left' || r.edge === 'bottom-left') {
        newW = Math.max(MIN_W, r.startW + (r.startX - e.clientX));
      }
      if (r.edge === 'top' || r.edge === 'top-left' || r.edge === 'top-right') {
        newH = Math.max(MIN_H, r.startH + (r.startY - e.clientY));
      }
      if (r.edge === 'top-right') {
        newW = Math.max(MIN_W, r.startW + (e.clientX - r.startX));
      }
      setSize({ w: newW, h: newH });
    };
    const onUp = () => {
      resizing.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [size]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || streaming) return;

    const userMsg = { role: 'user', content: text };
    const next = [...messages, userMsg];
    setMessages(next);
    setInput('');
    setStreaming(true);

    const assistantIdx = next.length;
    setMessages((prev) => [...prev, { role: 'assistant', content: '', toolCalls: [] }]);

    // Anthropic's Messages API only accepts {role, content} on each entry.
    // Strip our UI-only fields (toolCalls, etc.) before sending the history.
    const wireMessages = next.map(({ role, content }) => ({ role, content }));

    try {
      const controller = new AbortController();
      abortRef.current = controller;
      const resp = await api.chatStream(wireMessages, model);

      if (!resp.ok) {
        const err = await resp.text();
        setMessages((prev) => {
          const copy = [...prev];
          copy[assistantIdx] = { role: 'assistant', content: `Error: ${err}` };
          return copy;
        });
        setStreaming(false);
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const data = line.slice(6);
          if (data === '[DONE]') break;
          try {
            const parsed = JSON.parse(data);
            // New event protocol: tool_use / tool_result / text
            if (parsed.type === 'tool_use') {
              setMessages((prev) => {
                const copy = [...prev];
                const cur = copy[assistantIdx] || { role: 'assistant', content: '', toolCalls: [] };
                copy[assistantIdx] = {
                  ...cur,
                  toolCalls: [...(cur.toolCalls || []), { name: parsed.name, input: parsed.input, status: 'running' }],
                };
                return copy;
              });
            } else if (parsed.type === 'tool_result') {
              setMessages((prev) => {
                const copy = [...prev];
                const cur = copy[assistantIdx] || { role: 'assistant', content: '', toolCalls: [] };
                const calls = [...(cur.toolCalls || [])];
                // Mark the matching most-recent running call as done.
                for (let j = calls.length - 1; j >= 0; j--) {
                  if (calls[j].name === parsed.name && calls[j].status === 'running') {
                    calls[j] = { ...calls[j], status: 'done', preview: parsed.preview };
                    break;
                  }
                }
                copy[assistantIdx] = { ...cur, toolCalls: calls };
                return copy;
              });
            } else if (parsed.type === 'text' || parsed.text) {
              const txt = parsed.text || '';
              setMessages((prev) => {
                const copy = [...prev];
                const cur = copy[assistantIdx] || { role: 'assistant', content: '', toolCalls: [] };
                copy[assistantIdx] = { ...cur, content: (cur.content || '') + txt };
                return copy;
              });
            }
          } catch {}
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setMessages((prev) => {
          const copy = [...prev];
          copy[assistantIdx] = { role: 'assistant', content: `Error: ${err.message}` };
          return copy;
        });
      }
    }
    setStreaming(false);
    abortRef.current = null;
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleClear = () => setMessages([]);

  const lastMsg = messages.filter((m) => m.role === 'assistant').pop();
  const preview = lastMsg?.content?.slice(0, 50) || 'Ask about your network';

  // ── Minimized bar ──
  if (state === 'minimized') {
    return (
      <div
        className="fixed bottom-6 right-6 w-72 bg-surface-container-lowest rounded-2xl shadow-2xl border border-outline-variant/30 z-50 overflow-hidden cursor-pointer hover:shadow-xl transition-shadow"
        onClick={() => onStateChange('open')}
      >
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center shrink-0">
              <Icon name="smart_toy" className="text-on-primary text-[18px]" />
            </div>
            <div className="min-w-0">
              <p className="text-xs font-bold text-on-surface">Parity Assistant</p>
              <p className="text-[10px] text-on-surface-variant truncate">{streaming ? 'Typing...' : preview}</p>
            </div>
          </div>
          <div className="flex items-center gap-0.5 shrink-0">
            <button
              onClick={(e) => { e.stopPropagation(); onStateChange('open'); }}
              className="w-7 h-7 rounded-lg hover:bg-surface-container-high flex items-center justify-center text-on-surface-variant transition-colors"
            >
              <Icon name="open_in_full" className="text-[16px]" />
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onStateChange('closed'); }}
              className="w-7 h-7 rounded-lg hover:bg-surface-container-high flex items-center justify-center text-on-surface-variant transition-colors"
            >
              <Icon name="close" className="text-[16px]" />
            </button>
          </div>
        </div>
        {streaming && <div className="h-0.5 bg-primary/20"><div className="h-full w-1/3 bg-primary rounded-full animate-[shimmer_1.5s_infinite]" /></div>}
      </div>
    );
  }

  // ── Closed ──
  if (state !== 'open') return null;

  // ── Resize edge cursors ──
  const edgeStyle = 'absolute z-10';

  return (
    <div
      className="fixed bottom-6 right-6 bg-surface-container-lowest rounded-2xl shadow-2xl border border-outline-variant/30 flex flex-col z-50 overflow-hidden"
      style={{ width: size.w, height: size.h }}
    >
      {/* Resize handles */}
      <div className={`${edgeStyle} top-0 left-2 right-2 h-1.5 cursor-n-resize`} onMouseDown={(e) => onResizeStart(e, 'top')} />
      <div className={`${edgeStyle} top-2 left-0 bottom-2 w-1.5 cursor-w-resize`} onMouseDown={(e) => onResizeStart(e, 'left')} />
      <div className={`${edgeStyle} top-0 left-0 w-4 h-4 cursor-nw-resize`} onMouseDown={(e) => onResizeStart(e, 'top-left')} />
      <div className={`${edgeStyle} top-0 right-0 w-4 h-4 cursor-ne-resize`} onMouseDown={(e) => onResizeStart(e, 'top-right')} />
      <div className={`${edgeStyle} bottom-0 left-0 w-4 h-4 cursor-sw-resize`} onMouseDown={(e) => onResizeStart(e, 'bottom-left')} />

      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-outline-variant/20 bg-surface-container-low shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
            <Icon name="smart_toy" className="text-on-primary text-[18px]" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-on-surface">Parity Assistant</h3>
            <p className="text-[10px] text-on-surface-variant">Network operations AI</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="text-[10px] font-bold text-on-surface-variant bg-surface-container-high rounded-lg px-2 py-1 border-none outline-none cursor-pointer"
          >
            {MODELS.map((m) => (
              <option key={m.id} value={m.id}>{m.label} — {m.desc}</option>
            ))}
          </select>
          <button
            onClick={handleClear}
            title="Clear chat"
            className="w-8 h-8 rounded-lg hover:bg-surface-container-high flex items-center justify-center text-on-surface-variant transition-colors"
          >
            <Icon name="delete_sweep" className="text-[18px]" />
          </button>
          <button
            onClick={() => onStateChange('minimized')}
            title="Minimize"
            className="w-8 h-8 rounded-lg hover:bg-surface-container-high flex items-center justify-center text-on-surface-variant transition-colors"
          >
            <Icon name="minimize" className="text-[18px]" />
          </button>
          <button
            onClick={() => onStateChange('closed')}
            className="w-8 h-8 rounded-lg hover:bg-surface-container-high flex items-center justify-center text-on-surface-variant transition-colors"
          >
            <Icon name="close" className="text-[18px]" />
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-on-surface-variant gap-3">
            <Icon name="forum" className="text-4xl opacity-30" />
            <p className="text-sm font-semibold">Ask about your network</p>
            <div className="flex flex-wrap gap-2 justify-center max-w-[320px]">
              {[
                'Summarise active incidents',
                'What\'s the BGP state on DC1-R1?',
                'Run "show ip route 10.10.1.0" on S1-R1',
                'Have we seen this kind of issue before?',
              ].map((q) => (
                <button
                  key={q}
                  onClick={() => { setInput(q); setTimeout(() => inputRef.current?.focus(), 0); }}
                  className="text-[11px] px-3 py-1.5 rounded-full bg-surface-container-high text-on-surface-variant hover:bg-primary/10 hover:text-primary transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-2.5 ${
                msg.role === 'user'
                  ? 'bg-primary text-on-primary rounded-br-md'
                  : 'bg-surface-container-low text-on-surface rounded-bl-md'
              }`}
            >
              {msg.role === 'assistant' ? (
                <>
                  {/* Tool-call ribbon: show what the assistant queried */}
                  {(msg.toolCalls && msg.toolCalls.length > 0) && (
                    <div className="mb-2 space-y-1">
                      {msg.toolCalls.map((tc, j) => (
                        <div key={j} className="flex items-start gap-2 text-[11px] text-on-surface-variant">
                          <Icon
                            name={tc.status === 'done' ? 'check_circle' : 'progress_activity'}
                            className={`text-[14px] mt-0.5 shrink-0 ${tc.status === 'done' ? 'text-secondary' : 'text-primary animate-spin'}`}
                          />
                          <div className="flex-1 min-w-0">
                            <span className="font-mono font-semibold text-primary">{tc.name}</span>
                            {tc.input && Object.keys(tc.input).length > 0 && (
                              <span className="text-on-surface-variant/70">
                                {' '}({Object.entries(tc.input).slice(0, 2).map(([k, v]) =>
                                  `${k}=${typeof v === 'string' ? `"${v.length > 30 ? v.slice(0,30)+'…' : v}"` : JSON.stringify(v)}`
                                ).join(', ')})
                              </span>
                            )}
                            {tc.preview && (
                              <div className="text-[10px] text-on-surface-variant/60 italic line-clamp-1 mt-0.5">
                                → {tc.preview}
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  {msg.content ? (
                    <Markdown text={msg.content} />
                  ) : (
                    !msg.toolCalls?.length && (
                      <div className="flex items-center gap-2 py-1">
                        <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                        <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse [animation-delay:150ms]" />
                        <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse [animation-delay:300ms]" />
                      </div>
                    )
                  )}
                </>
              ) : (
                <p className="text-sm">{msg.content}</p>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-outline-variant/20 bg-surface-container-low shrink-0">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your network..."
            rows={1}
            className="flex-1 resize-none bg-surface-container-lowest rounded-xl px-4 py-2.5 text-sm text-on-surface placeholder:text-on-surface-variant/50 outline-none border border-outline-variant/20 focus:border-primary/40 transition-colors max-h-24"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || streaming}
            className="w-10 h-10 rounded-xl bg-primary text-on-primary flex items-center justify-center hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
          >
            <Icon name={streaming ? 'hourglass_empty' : 'send'} className="text-[18px]" />
          </button>
        </div>
      </div>
    </div>
  );
}
