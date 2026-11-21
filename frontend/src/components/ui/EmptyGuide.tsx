import { Link } from "react-router-dom";
import { Button } from "./Button";
import { StateBlock, type StateBlockAction } from "./StateBlock";

export interface EmptyGuideProps {
  /** Heading of the empty state. */
  title: string;
  /** One sentence on what the page records and how it reaches Schedule E. */
  description: string;
  /** Primary action: a button (`onClick`) or a link (`to`). */
  primary: StateBlockAction;
  /** Optional secondary action rendered below the block. */
  secondary?: StateBlockAction;
}

/**
 * Empty-state guidance (ui-polish Requirements 25.4, 27.5).
 *
 * Wraps `StateBlock kind="empty"` and adds an optional secondary action. It
 * renders no landmark, so it sits inside the page's `main`.
 */
export function EmptyGuide({
  title,
  description,
  primary,
  secondary,
}: EmptyGuideProps) {
  return (
    <div>
      <StateBlock
        kind="empty"
        title={title}
        description={description}
        action={primary}
      />
      {secondary ? (
        <div className="mt-3 text-center">
          {secondary.to ? (
            <Button variant="secondary" size="sm" asChild>
              <Link to={secondary.to}>{secondary.label}</Link>
            </Button>
          ) : (
            <Button variant="secondary" size="sm" onClick={secondary.onClick}>
              {secondary.label}
            </Button>
          )}
        </div>
      ) : null}
    </div>
  );
}
