import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import Icon from './Icon';

const DialogContext = createContext(null);

const VARIANT_STYLES = {
  primary: {
    iconBg: 'bg-primary/10',
    iconColor: 'text-primary',
    icon: 'help_outline',
    confirmBtn: 'bg-primary text-on-primary hover:bg-primary/90',
  },
  danger: {
    iconBg: 'bg-error/10',
    iconColor: 'text-error',
    icon: 'warning',
    confirmBtn: 'bg-error text-white hover:bg-error/90',
  },
  warning: {
    iconBg: 'bg-tertiary/10',
    iconColor: 'text-tertiary',
    icon: 'error',
    confirmBtn: 'bg-tertiary text-white hover:bg-tertiary/90',
  },
  info: {
    iconBg: 'bg-primary/10',
    iconColor: 'text-primary',
    icon: 'info',
    confirmBtn: 'bg-primary text-on-primary hover:bg-primary/90',
  },
};

function normalize(input) {
  return typeof input === 'string' ? { message: input } : (input || {});
}

export function DialogProvider({ children }) {
  // state shape: { type: 'confirm'|'alert', options, resolve }
  const [state, setState] = useState(null);

  const confirm = useCallback((opts) => {
    const options = normalize(opts);
    return new Promise((resolve) => {
      setState({ type: 'confirm', options, resolve });
    });
  }, []);

  const alertFn = useCallback((opts) => {
    const options = normalize(opts);
    return new Promise((resolve) => {
      setState({ type: 'alert', options, resolve });
    });
  }, []);

  const close = useCallback((value) => {
    setState((s) => {
      if (s) s.resolve(value);
      return null;
    });
  }, []);

  // Esc closes (cancels confirm, dismisses alert)
  useEffect(() => {
    if (!state) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') close(state.type === 'alert' ? undefined : false);
      if (e.key === 'Enter') close(state.type === 'alert' ? undefined : true);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [state, close]);

  const value = { confirm, alert: alertFn };

  return (
    <DialogContext.Provider value={value}>
      {children}
      {state && <DialogModal state={state} onClose={close} />}
    </DialogContext.Provider>
  );
}

function DialogModal({ state, onClose }) {
  const { type, options } = state;
  const variant = VARIANT_STYLES[options.variant] || VARIANT_STYLES.primary;
  const confirmLabel = options.confirmLabel || (type === 'alert' ? 'OK' : 'Confirm');
  const cancelLabel = options.cancelLabel || 'Cancel';
  const title = options.title || (type === 'alert' ? 'Notice' : 'Are you sure?');

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm animate-[fadeIn_120ms_ease-out]"
      onClick={() => onClose(type === 'alert' ? undefined : false)}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        className="w-full max-w-md bg-surface-container-lowest rounded-2xl shadow-2xl overflow-hidden animate-[slideUp_140ms_ease-out]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-6">
          <div className="flex items-start gap-4">
            <div className={`w-11 h-11 rounded-xl ${variant.iconBg} flex items-center justify-center shrink-0`}>
              <Icon name={variant.icon} className={`text-2xl ${variant.iconColor}`} fill />
            </div>
            <div className="flex-1 min-w-0 pt-1">
              <h3 id="dialog-title" className="text-base font-bold text-on-surface mb-1.5">
                {title}
              </h3>
              {options.message && (
                <p className="text-sm text-on-surface-variant whitespace-pre-wrap">{options.message}</p>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 bg-surface-container-low border-t border-outline/10">
          {type === 'confirm' && (
            <button
              type="button"
              autoFocus
              onClick={() => onClose(false)}
              className="px-4 py-2 rounded-lg text-sm font-bold text-on-surface-variant hover:bg-surface-container-high transition-colors"
            >
              {cancelLabel}
            </button>
          )}
          <button
            type="button"
            autoFocus={type === 'alert'}
            onClick={() => onClose(type === 'alert' ? undefined : true)}
            className={`px-4 py-2 rounded-lg text-sm font-bold transition-colors ${variant.confirmBtn}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
      <style>{`
        @keyframes fadeIn { from { opacity: 0 } to { opacity: 1 } }
        @keyframes slideUp { from { transform: translateY(8px); opacity: 0 } to { transform: translateY(0); opacity: 1 } }
      `}</style>
    </div>
  );
}

export function useDialog() {
  const ctx = useContext(DialogContext);
  if (!ctx) {
    throw new Error('useDialog must be used inside <DialogProvider>');
  }
  return ctx;
}
