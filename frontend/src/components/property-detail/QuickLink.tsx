import { Link } from "react-router-dom";
import { Button } from "../ui";

/** A single quicklink button styled like a bordered nav pill. */
export function QuickLink({ to, label }: { to: string; label: string }) {
  return (
    <Button asChild variant="secondary" size="sm">
      <Link to={to}>{label}</Link>
    </Button>
  );
}
