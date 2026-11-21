import type { ItemizedLineSource, ItemizedSummary } from "../../api/itemized";
import { formatMoney, toCents } from "../../lib/money";
import { Badge, Card } from "../ui";

interface ItemizedSummaryPanelProps {
  summary: ItemizedSummary;
  /** Schedule E line number used in the source label, e.g. 14. */
  line: number;
}

/** Source label text (Requirement 7.5). */
export function sourceLabel(source: ItemizedLineSource, line: number): string {
  switch (source) {
    case "entered_total":
      return `Line ${line} uses: entered total`;
    case "itemized":
      return `Line ${line} uses: itemized entries`;
    default:
      return `Line ${line} has no amount for this year`;
  }
}

/**
 * Description list of the year's figures (Requirements 7.1 to 7.6, 7.9, 7.11,
 * 16.5). A `dl` makes screen readers announce each label with its value. The
 * negative remainder is flagged with text and a badge in addition to color.
 */
export function ItemizedSummaryPanel({
  summary,
  line,
}: ItemizedSummaryPanelProps) {
  const remainderNegative =
    summary.remainder !== null && toCents(summary.remainder) < 0;
  const entryNoun = summary.itemized_count === 1 ? "entry" : "entries";

  return (
    <Card as="section" aria-labelledby="itemized-summary-heading" className="p-card">
      <h2 id="itemized-summary-heading" className="text-sm font-medium text-fg-subtle">
        Summary for {summary.tax_year}
      </h2>
      <dl className="mt-2 grid gap-3 sm:grid-cols-2">
        <div>
          <dt className="text-sm text-fg-muted">Entered total</dt>
          <dd className="tabular-nums text-fg">
            {summary.entered_total === null
              ? "No total entered"
              : formatMoney(summary.entered_total)}
          </dd>
        </div>
        <div>
          <dt className="text-sm text-fg-muted">Itemized sum</dt>
          <dd className="tabular-nums text-fg">
            {formatMoney(summary.itemized_sum)}{" "}
            <span className="text-fg-muted">
              ({summary.itemized_count} {entryNoun})
            </span>
          </dd>
        </div>
        {summary.remainder !== null ? (
          <div>
            <dt className="text-sm text-fg-muted">Unitemized remainder</dt>
            <dd className="tabular-nums text-fg">
              <span className={remainderNegative ? "text-warning" : undefined}>
                {formatMoney(summary.remainder)}
              </span>
              {remainderNegative ? (
                <span className="ml-2 inline-flex flex-wrap items-center gap-2">
                  <Badge className="border-warning-subtle bg-warning-subtle text-warning">
                    Over total
                  </Badge>
                  <span className="text-small text-warning">
                    Itemized entries exceed the entered total
                  </span>
                </span>
              ) : null}
            </dd>
          </div>
        ) : null}
        <div>
          <dt className="text-sm text-fg-muted">Line {line} total</dt>
          <dd className="tabular-nums text-lg font-semibold text-fg">
            {formatMoney(summary.line_total)}
          </dd>
          <dd className="text-small text-fg-muted">
            {sourceLabel(summary.line_source, line)}
          </dd>
        </div>
      </dl>
    </Card>
  );
}
