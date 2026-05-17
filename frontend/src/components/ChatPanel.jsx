import { useState, useRef, useEffect, useCallback } from 'react';
import { api } from '../api/client';
import Icon from './Icon';
import { GeminiChip, DavisChip } from './AiSourceChips';
import dynatraceCube from '../assets/dynatrace-logo-cube.png';

const MODELS = [
  { id: 'gemini-2.5-flash-lite', label: 'Flash-Lite', desc: 'Cheapest' },
  { id: 'gemini-2.5-flash', label: 'Flash', desc: 'Balanced' },
  { id: 'gemini-2.5-pro', label: 'Pro', desc: 'Deep reasoning' },
];

const MIN_W = 360;
const MIN_H = 300;
// 572 = 440 * 1.3 (user requested 30% wider default first-open size).
// The resize handles still let the operator drag back narrower if
// they prefer; this just sets the on-first-open footprint.
const DEFAULT_W = 572;
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
  // Stable session id per chat panel mount. Backend uses this to
  // keep the ADK session alive across turns so the agent remembers
  // prior tool calls (e.g. "thats not cdp neighbours" can reference
  // the previous turn). Regenerated only on Clear Chat.
  const [sessionId, setSessionId] = useState(() =>
    typeof crypto !== 'undefined' && crypto.randomUUID
      ? crypto.randomUUID()
      : `s-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
  );
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [model, setModel] = useState(MODELS[0].id);
  const [size, setSize] = useState({ w: DEFAULT_W, h: DEFAULT_H });
  // Opt-in toggle for "Bring Davis into the chat". When true, every
  // turn fans out to Davis Copilot in parallel and its answer shows
  // as a second bubble. Off by default so casual questions stay
  // single-voice + fast — Davis adds ~3s and is most useful when
  // the operator is asking about live Dynatrace state.
  const [davisEnabled, setDavisEnabled] = useState(false);
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

    // The chat API only accepts {role, content} on each entry.
    // Strip our UI-only fields (toolCalls, etc.) before sending the
    // history. Drop Davis bubbles too — they're a UI-only second
    // voice; the ADK session shouldn't see them as turns.
    const wireMessages = next
      .filter((m) => m.role !== 'davis')
      .map(({ role, content }) => ({ role, content }));

    try {
      const controller = new AbortController();
      abortRef.current = controller;
      // Collect a page-context snapshot at send-time. Each page is
      // expected to keep window.parityPageContext up to date as its
      // data loads / filters change. Falls back to bare route + title
      // so the assistant always knows where the user is.
      const pageCtx = {
        route: typeof window !== 'undefined' ? window.location.pathname : '',
        title: typeof document !== 'undefined' ? document.title : '',
        ...(typeof window !== 'undefined' && window.parityPageContext
          ? window.parityPageContext
          : {}),
      };
      const resp = await api.chatStream(wireMessages, model, pageCtx, sessionId, davisEnabled);

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
            } else if (parsed.type === 'text') {
              // ONLY the literal text event — don't fall through on
              // `parsed.text` truthiness, because davis_text events
              // also carry a text field and would land in the
              // Gemini bubble instead of as their own Davis message.
              const txt = parsed.text || '';
              setMessages((prev) => {
                const copy = [...prev];
                const cur = copy[assistantIdx] || { role: 'assistant', content: '', toolCalls: [] };
                copy[assistantIdx] = { ...cur, content: (cur.content || '') + txt };
                return copy;
              });
            } else if (parsed.type === 'davis_text') {
              // Davis "chimes in" as a separate participant in the
              // group chat. Render as its own message bubble after
              // Gemini's, with the same DavisChip styling used on
              // findings/incidents.
              const txt = parsed.text || '';
              if (txt) {
                setMessages((prev) => [
                  ...prev,
                  { role: 'davis', content: txt, label: parsed.label || 'Davis Copilot' },
                ]);
              }
            } else if (parsed.type === 'skip_assistant') {
              // Backend detected the user addressed Davis directly
              // ("Hi Davis ...") — Gemini stays silent this turn.
              // Drop the empty Gemini placeholder we pre-created so
              // the chat doesn't show a blank "Gemini" bubble.
              setMessages((prev) => {
                const copy = [...prev];
                if (copy[assistantIdx] && copy[assistantIdx].role === 'assistant') {
                  copy.splice(assistantIdx, 1);
                }
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

  const handleClear = () => {
    setMessages([]);
    // Roll the session id so the next turn starts a fresh ADK
    // conversation - matches operator expectation that "Clear" means
    // "start over with no memory".
    setSessionId(
      typeof crypto !== 'undefined' && crypto.randomUUID
        ? crypto.randomUUID()
        : `s-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    );
  };

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
            {/* Gemini-branded badge: Google four-colour gradient on the
                auto_awesome sparkle. Consistent with every other Gemini
                chip across the app. */}
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
              style={{ background: 'linear-gradient(135deg, #4285F4 0%, #34A853 50%, #FBBC04 100%)' }}
            >
              <Icon name="auto_awesome" className="text-white text-[18px]" fill />
            </div>
            <div className="min-w-0">
              <p className="text-xs font-bold text-on-surface">Gemini Assistant</p>
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
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ background: 'linear-gradient(135deg, #4285F4 0%, #34A853 50%, #FBBC04 100%)' }}
          >
            <Icon name="auto_awesome" className="text-white text-[18px]" fill />
          </div>
          <div>
            <h3 className="text-sm font-bold text-on-surface">Gemini Assistant</h3>
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
          {/* Davis opt-in toggle. Off → grey pill, "Bring Davis in".
              On → Davis blue gradient pill matching the DavisChip
              styling used everywhere else, "Davis in chat". Click
              to flip; takes effect on the NEXT user turn. */}
          <button
            onClick={() => setDavisEnabled((v) => !v)}
            title={
              davisEnabled
                ? 'Davis Copilot is participating. Click to remove.'
                : 'Bring Davis Copilot into the chat as a second voice.'
            }
            className={`inline-flex items-center gap-1.5 text-[10px] font-bold px-2.5 h-7 leading-none rounded-lg transition-colors ${
              davisEnabled
                ? 'text-white shadow'
                : 'text-on-surface-variant bg-surface-container-high hover:bg-surface-container-highest'
            }`}
            style={
              davisEnabled
                ? { background: 'linear-gradient(135deg, #1496FF 0%, #0066B7 100%)' }
                : undefined
            }
          >
            <img src={dynatraceCube} alt="" className="w-3 h-3 object-contain" />
            {davisEnabled ? 'Davis in chat' : 'Bring Davis in'}
          </button>
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
                  : msg.role === 'davis'
                    // Davis bubble: subtle blue-tinted surface so the
                    // second voice reads as distinct from Gemini's
                    // default-surface bubble without being loud.
                    ? 'bg-[#1496FF]/[0.07] text-on-surface rounded-bl-md border border-[#1496FF]/20'
                    : 'bg-surface-container-low text-on-surface rounded-bl-md'
              }`}
            >
              {msg.role === 'assistant' ? (
                <>
                  {/* Author chip — makes the group-chat attribution
                      explicit. Same GeminiChip used on findings, so
                      the operator always knows which AI spoke. */}
                  <div className="mb-2">
                    <GeminiChip label="Gemini" />
                  </div>
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
              ) : msg.role === 'davis' ? (
                <>
                  <div className="mb-2">
                    <DavisChip label={msg.label || 'Davis Copilot'} />
                  </div>
                  <Markdown text={msg.content} />
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
