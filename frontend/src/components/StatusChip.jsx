const variants = {
  success: 'bg-secondary/10 text-secondary',
  warning: 'bg-orange-400/10 text-orange-400',
  error: 'bg-error/10 text-error',
  info: 'bg-primary/10 text-primary',
  neutral: 'bg-outline-variant/20 text-on-surface-variant',
};

export default function StatusChip({ variant = 'neutral', dot = false, pulse = false, children }) {
  const cls = variants[variant] || variants.neutral;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold ${cls}`}>
      {dot && (
        <span className={`w-1.5 h-1.5 rounded-full bg-current ${pulse ? 'animate-pulse' : ''}`} />
      )}
      {children}
    </span>
  );
}
