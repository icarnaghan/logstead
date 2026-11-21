import type { Line12ImpactYear } from "../../api/loans";
import { formatMoneyWholeDollars } from "../../lib/money";
import { Card } from "../ui";

export interface SupersededInterestNoticeProps {
  years: Line12ImpactYear[];
}

/**
 * One notice per tax year in which loan interest supersedes manually entered
 * mortgage interest (Requirement 9.16). Each notice states the tax year, the
 * superseded amount, and how to restore the manual figures. Renders nothing
 * when there are no affected years.
 */
export function SupersededInterestNotice({ years }: SupersededInterestNoticeProps) {
  if (years.length === 0) return null;

  return (
    <ul className="flex flex-col gap-2" aria-label="Superseded mortgage interest notices">
      {years.map((year) => (
        <Card as="li" key={year.tax_year} role="note" className="p-3 text-sm text-fg-muted">
          <p>
            <strong className="font-medium text-fg">Tax year {year.tax_year}:</strong>{" "}
            loan interest replaces{" "}
            {formatMoneyWholeDollars(year.superseded_manual_interest.amount)} of manually
            entered mortgage interest on Schedule E Line 12. Turn Report_Inclusion off for the
            loan to restore the manual figures.
          </p>
        </Card>
      ))}
    </ul>
  );
}
