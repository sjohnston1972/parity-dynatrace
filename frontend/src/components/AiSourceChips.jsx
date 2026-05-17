/* eslint-disable react/prop-types */
/**
 * Shared GeminiChip + DavisChip components.
 *
 * Used by every surface that labels a finding / incident / event /
 * activity / log entry with which AI produced or reviewed it
 * (Anomalies Timeline, Insights cards, Incident Log, Approvals,
 * Execution Log, Davis Event Timeline, Pipeline activity feed, etc.).
 *
 * Hard-pinned to identical h-5 (20px) chips with leading-none so a
 * font-glyph icon (Gemini's auto_awesome sparkle) and an <img>
 * (Dynatrace cube) sit at the same baseline despite their different
 * intrinsic line-box behaviours. The inner glyph wrapper is the same
 * w-3 h-3 inline-flex centre in both chips so swap-in / swap-out
 * never affects vertical alignment.
 *
 * Both chips accept an optional `label` override. The Gemini chip
 * also accepts a `model` prop (e.g. "gemini-2.5-flash") which is
 * shown as the label when provided.
 */

import dynatraceCube from '../assets/dynatrace-logo-cube.png';
import Icon from './Icon';

const BASE_CHIP =
  'inline-flex items-center gap-1 text-[10px] font-bold px-2 h-5 leading-none rounded-md text-white';
const GLYPH_BOX =
  'inline-flex items-center justify-center w-3 h-3 shrink-0';

const GEMINI_GRADIENT =
  'linear-gradient(135deg, #4285F4 0%, #34A853 50%, #FBBC04 100%)';
const DAVIS_GRADIENT =
  'linear-gradient(135deg, #1496FF 0%, #0066B7 100%)';

/**
 * Gemini chip — Google four-colour gradient + filled auto_awesome
 * sparkle. Default label "Gemini"; pass `model` to show e.g.
 * "gemini-2.5-flash", or `label` to fully override.
 */
export function GeminiChip({ model, label, title, className = '' }) {
  const text = label || model || 'Gemini';
  return (
    <span
      className={`${BASE_CHIP} ${className}`}
      style={{ background: GEMINI_GRADIENT }}
      title={title || 'Primary reasoning by Google Gemini'}
    >
      <span className={GLYPH_BOX}>
        <Icon name="auto_awesome" className="text-[12px] leading-none" fill />
      </span>
      {text}
    </span>
  );
}

/**
 * Davis chip — Dynatrace blue gradient + cube glyph. Default label
 * "Davis"; pass `label="Davis Copilot"` etc. to override.
 *
 * For an INTERACTIVE chip (one that opens the Davis modal) use the
 * DynatracePill component instead — same outward styling, click
 * handler attached.
 */
export function DavisChip({ label, title, className = '' }) {
  return (
    <span
      className={`${BASE_CHIP} ${className}`}
      style={{ background: DAVIS_GRADIENT }}
      title={title || 'Davis Copilot reviewed this via Dynatrace MCP'}
    >
      <span className={GLYPH_BOX}>
        <img src={dynatraceCube} alt="" className="w-3 h-3 object-contain" />
      </span>
      {label || 'Davis'}
    </span>
  );
}

/**
 * Convenience: render both chips side-by-side for a finding/incident.
 * Davis chip only renders when `hasDavis` is true (typical pattern:
 * pass `!!finding.evidence?.davis_assessment` or similar).
 */
export function AiSourceChips({
  geminiModel,
  geminiLabel,
  hasDavis,
  davisLabel = 'Davis Copilot',
  className = '',
}) {
  return (
    <span className={`inline-flex items-center gap-2 flex-wrap ${className}`}>
      <GeminiChip model={geminiModel} label={geminiLabel} />
      {hasDavis && <DavisChip label={davisLabel} />}
    </span>
  );
}

export default AiSourceChips;
