import { useId } from "react";
import {
  BARS,
  CHIMNEY_PATH,
  GRADIENTS,
  HOUSE_PATH,
  HOUSE_STROKE_WIDTH,
  LOCKUP_HEIGHT,
  LOCKUP_VIEWBOX,
  LOCKUP_WIDTH,
  MARK_TRANSFORM,
  TAGLINE_PATH,
  WORDMARK_PATH,
} from "../../assets/brand/brand-paths";

export interface LogoProps {
  /** Render the tagline. Only use where it is legible (the sign-in splash at 640px and wider). */
  tagline?: boolean;
  /** Hide from assistive tech when adjacent text already names the brand. */
  decorative?: boolean;
  className?: string;
}

/**
 * Inline SVG lockup. No network fetch, and the aspect ratio reserves the box
 * so there is no layout shift. Wordmark follows the theme via currentColor.
 */
export function Logo({ tagline = false, decorative = false, className = "" }: LogoProps) {
  // useId returns characters such as ":" that are awkward in url(#...); strip them.
  const prefix = `logo-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const gid = (id: string) => `${prefix}-${id}`;

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox={LOCKUP_VIEWBOX}
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : "Logstead"}
      aria-hidden={decorative || undefined}
      focusable="false"
      className={`text-fg ${className}`.trim()}
      style={{ aspectRatio: `${LOCKUP_WIDTH} / ${LOCKUP_HEIGHT}` }}
    >
      <defs>
        {GRADIENTS.map((g) => (
          <linearGradient key={g.id} id={gid(g.id)} x1={g.x1} y1={g.y1} x2={g.x2} y2={g.y2}>
            <stop offset="0%" stopColor={g.from} />
            <stop offset="100%" stopColor={g.to} />
          </linearGradient>
        ))}
      </defs>
      <g transform={MARK_TRANSFORM}>
        <path
          d={CHIMNEY_PATH}
          fill="none"
          stroke={`url(#${gid("house")})`}
          strokeWidth={HOUSE_STROKE_WIDTH}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d={HOUSE_PATH}
          fill="none"
          stroke={`url(#${gid("house")})`}
          strokeWidth={HOUSE_STROKE_WIDTH}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {BARS.map((b) => (
          <rect
            key={b.gradient}
            x={b.x}
            y={b.y}
            width={b.width}
            height={b.height}
            rx={b.rx}
            fill={`url(#${gid(b.gradient)})`}
          />
        ))}
      </g>
      <path d={WORDMARK_PATH} fill="currentColor" />
      {tagline ? <path d={TAGLINE_PATH} className="fill-brand-tagline" /> : null}
    </svg>
  );
}
