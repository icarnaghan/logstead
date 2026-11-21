import { Fragment } from "react";
import { highlightSegments } from "../../lib/highlight";

export interface HighlightedTextProps {
  text: string;
  tokens: readonly string[];
}

/**
 * Renders `text` with matched parts in `mark` elements. Only text nodes are
 * created, so record text is never interpreted as HTML (Requirement 11.9).
 */
export function HighlightedText({ text, tokens }: HighlightedTextProps) {
  return (
    <>
      {highlightSegments(text, tokens).map((segment, i) =>
        segment.match ? (
          <mark key={i} className="rounded-sm bg-warning-subtle px-0.5 text-fg">
            {segment.text}
          </mark>
        ) : (
          <Fragment key={i}>{segment.text}</Fragment>
        ),
      )}
    </>
  );
}
