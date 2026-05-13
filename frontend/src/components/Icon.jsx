export default function Icon({ name, className = '', fill = false }) {
  return (
    <span
      className={`material-symbols-outlined ${className}`}
      style={fill ? { fontVariationSettings: "'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 24" } : undefined}
    >
      {name}
    </span>
  );
}
