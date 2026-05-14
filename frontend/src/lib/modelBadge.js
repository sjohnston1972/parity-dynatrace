// Map a Gemini model id (or any historical model name) to a Tailwind
// badge class. Used on Approvals, Insights, Executions, Pipeline pages
// so the colour scheme stays consistent across the UI.
//
// `variant`: 'ring' (default) adds ring-1 ring-<colour>/30; 'light' is
// the slimmer style used in Insights' compact rows.
export function modelBadgeClass(model, variant = 'ring') {
  if (!model) return 'bg-surface-container-high text-on-surface-variant';
  const m = model.toLowerCase();

  // flash-lite is most specific, must check before 'flash'.
  let palette;
  if (m.includes('flash-lite')) {
    palette = { bg: 'bg-amber-500/15', text: 'text-amber-400', ring: 'ring-amber-500/30' };
  } else if (m.includes('pro')) {
    palette = { bg: 'bg-purple-500/15', text: 'text-purple-400', ring: 'ring-purple-500/30' };
  } else if (m.includes('flash')) {
    palette = { bg: 'bg-emerald-500/15', text: 'text-emerald-400', ring: 'ring-emerald-500/30' };
  } else if (m.includes('pyats')) {
    palette = { bg: 'bg-cyan-500/15', text: 'text-cyan-400', ring: 'ring-cyan-500/30' };
  } else {
    return 'bg-surface-container-high text-on-surface-variant';
  }

  if (variant === 'light') {
    return `${palette.bg} ${palette.text}`;
  }
  return `${palette.bg} ${palette.text} ring-1 ${palette.ring}`;
}
