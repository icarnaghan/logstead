/** Plain-text brand name used when the logo artwork is unavailable. No amber or gold. */
export function WordmarkFallback() {
  return (
    <span role="img" aria-label="Logstead" className="text-xl font-semibold tracking-tight text-fg">
      logstead
    </span>
  );
}
