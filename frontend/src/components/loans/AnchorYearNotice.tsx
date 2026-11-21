import { Card } from "../ui";

export interface AnchorYearNoticeProps {
  /** The loan's anchor date, YYYY-MM-DD. */
  anchorDate: string;
}

/**
 * Tells the user which years the generated schedule does not cover and what to
 * enter for them (Requirement 11.4). Rendered as a note, not an alert.
 */
export function AnchorYearNotice({ anchorDate }: AnchorYearNoticeProps) {
  const anchorYear = anchorDate.slice(0, 4);
  return (
    <Card role="note" className="p-3 text-sm text-fg-muted">
      <p>
        <strong className="font-medium text-fg">Anchor year: {anchorYear}.</strong>{" "}
        Generated interest for {anchorYear} covers only payments after the
        anchor date ({anchorDate}). Enter the interest from your Form 1098 as
        an interest override for {anchorYear} and for earlier years.
      </p>
    </Card>
  );
}
